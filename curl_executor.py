from flask import Flask, request, jsonify, render_template, send_from_directory
import json
import re
import subprocess
import pandas as pd
import os
import tempfile
import uuid
import time
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static')
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['RESULTS_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # 禁用静态文件缓存

# 确保上传和结果目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['RESULTS_FOLDER'], exist_ok=True)


@app.route('/')
def index():
    return render_template('index.html')


@app.after_request
def add_no_cache_headers(response):
    # 减少浏览器缓存，确保前端 JS/CSS 更新后能立即生效
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/results/<path:filename>')
def result_file(filename):
    return send_from_directory(app.config['RESULTS_FOLDER'], filename)


@app.route('/upload_excel', methods=['POST'])
def upload_excel():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'error': 'File must be an Excel file'}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    # 读取Excel文件的前几行预览
    try:
        df = pd.read_excel(filepath, nrows=5)
        preview = df.to_dict('records')
        columns = df.columns.tolist()
        # 计算总行数
        try:
            df_all = pd.read_excel(filepath)
            total_rows = len(df_all)
        except Exception:
            total_rows = None
        return jsonify({
            'success': True,
            'filename': filename,
            'filepath': filepath,
            'preview': preview,
            'columns': columns,
            'total_rows': total_rows
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# def replace_variables(text, variables):
#     # 查找所有 {{变量名}} 格式的变量（仅字母数字下划线）
#     pattern = r'\{\{(\w+)\}\}'

#     def replace_match(match):
#         var_name = match.group(1)
#         if var_name in variables:
#             return str(variables[var_name])
#         return match.group(0)  # 如果变量不存在，保持原样

#     return re.sub(pattern, replace_match, text)
def replace_variables(text, variables):
    """
    替换 {{变量名}}，并自动对 JSON 值做 CMD/Bash 兼容转义
    """

    # 判断文本整体属于 CMD 还是 Bash 风格
    def detect_shell_type(cmd: str) -> str:
        if re.search(r"\^(\s|$)|\^\"", cmd):
            return "cmd"
        if re.search(r"\\(\s|$)|'(.*?)'", cmd):
            return "bash"
        return "bash"  # 默认当成 bash

    shell_type = detect_shell_type(text)

    def escape_value(value):
        # 如果是 dict/list，先转 JSON
        if isinstance(value, (dict, list)):
            json_text = json.dumps(value, ensure_ascii=False)
            if shell_type == "cmd":
                return f'^"{json_text.replace("\"", "\\\"")}^"'
            else:
                return f"'{json_text}'"
        else:
            # 普通字符串，直接返回
            return str(value)

    # 匹配 {{变量名}}
    pattern = r'\{\{(\w+)\}\}'

    def replace_match(match):
        var_name = match.group(1)
        if var_name in variables:
            return escape_value(variables[var_name])
        return match.group(0)  # 不存在保持原样

    return re.sub(pattern, replace_match, text)


def evaluate_assertion(assertion, response_data):
    # 简单的断言评估器：暴露 response 对象和安全的内置函数
    try:
        # 创建一个类来支持点表示法
        class DotDict:
            def __init__(self, data):
                self.__dict__.update(data)
        
        # 将字典转换为支持点表示法的对象
        dot_response = DotDict(response_data)
        
        # 创建一个安全的内置函数子集
        safe_builtins = {
            'len': len,
            'str': str,
            'int': int,
            'float': float,
            'bool': bool,
            'list': list,
            'dict': dict,
            'set': set,
            'max': max,
            'min': min,
            'sum': sum,
            'abs': abs,
            'round': round,
            'all': all,
            'any': any
        }
        
        local_vars = {'response': dot_response}
        result = eval(assertion, {"__builtins__": safe_builtins}, local_vars)
        return {
            'assertion': assertion,
            'result': bool(result),
            'success': bool(result)
        }
    except Exception as e:
        return {
            'assertion': assertion,
            'result': False,
            'error': str(e),
            'success': False
        }


def _ensure_verbose(curl_cmd: str) -> str:
    # 如果没有 -v / --verbose，则加上 -v
    if (' -v' not in curl_cmd) and (' --verbose' not in curl_cmd):
        return curl_cmd.replace('curl', 'curl -v', 1)
    return curl_cmd


def _run_curl_script(curl_cmd: str):
    """创建临时脚本执行 curl，返回 subprocess.CompletedProcess"""
    curl_cmd = _ensure_verbose(curl_cmd)
    temp_name = None
    try:
        # 创建临时脚本
        with tempfile.NamedTemporaryFile(suffix=('.bat' if os.name == 'nt' else '.sh'), delete=False) as temp:
            if os.name == 'nt':  # Windows
                # 关闭回显，避免命令自身被输出污染 stdout
                script_content = "@echo off\r\n" + curl_cmd
            else:  # Unix/Linux
                script_content = "#!/bin/bash\n" + curl_cmd
            temp.write(script_content.encode())
            temp_name = temp.name

        # 设置可执行权限（Unix/Linux）
        if os.name != 'nt':
            os.chmod(temp_name, 0o755)

        # 执行
        proc = subprocess.run(
            temp_name if os.name == 'nt' else ['/bin/bash', temp_name],
            shell=True if os.name == 'nt' else False,
            capture_output=True,
            text=True
        )
        return proc
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except Exception:
                pass


def _extract_status_code(stdout: str, stderr: str):
    # 从输出中提取所有 HTTP 行，取最后一个状态码（处理重定向、多次握手）
    combined = f"{stderr or ''}\n{stdout or ''}"
    codes = re.findall(r'HTTP/\d\.\d\s+(\d{3})', combined)
    return int(codes[-1]) if codes else None


_seq_counter = 0

def _generate_result_id(is_batch: bool = False) -> str:
    """生成 ID：时间格式 YYYYHHMM-XXX，例如 20251712-009；batch 前缀保留。"""
    global _seq_counter
    _seq_counter = (_seq_counter + 1) % 1000
    t = time.localtime()
    base = f"{t.tm_year}{t.tm_mon:02d}{t.tm_mday:02d}-{t.tm_hour:02d}{t.tm_min:02d}{t.tm_sec:02d}-{_seq_counter:03d}"
    return (f"BATCH{base}" if is_batch else base)

def _parse_curl_request(curl_cmd: str):
    """从 curl 命令里解析请求信息: method/url/headers/body/query params"""
    method = 'GET'
    url = ''
    headers = {}
    body_parts = []

    # 简单切分，考虑引号包裹
    # 注意：这不是完全可靠的 shell 解析，但对常见用法有效
    token_pattern = r"(?:'[^']*'|\"[^\"]*\"|[^\s])+"
    tokens = re.findall(token_pattern, curl_cmd)

    # 去掉引号的辅助函数
    def unquote(s: str):
        if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
            return s[1:-1]
        return s

    # 找到 URL（第一个非 - 开头且包含 :// 的 token，或紧随 --url 之后）
    for i, t in enumerate(tokens):
        if t in ('-X', '--request') and i + 1 < len(tokens):
            method = unquote(tokens[i + 1]).upper()
        if t in ('--url',) and i + 1 < len(tokens):
            url = unquote(tokens[i + 1])
        if not url and not t.startswith('-') and '://' in t:
            url = unquote(t)
        if t in ('-H', '--header') and i + 1 < len(tokens):
            header_raw = unquote(tokens[i + 1])
            if ':' in header_raw:
                k, v = header_raw.split(':', 1)
                headers[k.strip()] = v.strip()
        if t in ('-d', '--data', '--data-raw', '--data-binary') and i + 1 < len(tokens):
            body_parts.append(unquote(tokens[i + 1]))
            method='POST'

    body = '\n'.join([p for p in body_parts if p is not None]) if body_parts else ''

    # 解析查询参数
    params = {}
    if url and '?' in url:
        query = url.split('?', 1)[1]
        for pair in query.split('&'):
            if not pair:
                continue
            if '=' in pair:
                k, v = pair.split('=', 1)
                params[k] = v
            else:
                params[pair] = ''

    return {
        'method': method,
        'url': url,
        'headers': headers,
        'body': body,
        'params': params
    }


def _parse_response_parts(stdout: str, stderr: str):
    """从 curl -v 输出中提取最后一次响应 header 与响应 body。
    curl -v 会在 stderr 打印形如：
      < HTTP/1.1 200 OK
      < Content-Type: application/json
    我们基于以 "< " 开头的行解析最后一个响应头块。
    """
    response_headers = {}
    lines = (stderr or '').splitlines()
    # 收集所有以"< HTTP"开头的位置，选择最后一个
    status_indices = [i for i, line in enumerate(lines) if line.startswith('< HTTP/')]
    start_idx = status_indices[-1] if status_indices else None
    if start_idx is not None:
        # 从状态行之后的下一行开始，直到遇到空行或非"< "开头
        for j in range(start_idx + 1, len(lines)):
            line = lines[j]
            if not line.startswith('< '):
                # 可能是空行或其它，视为 header 结束
                if line.strip() == '':
                    break
                else:
                    break
            header_line = line[2:]  # 去掉前缀"< "
            if ':' in header_line:
                k, v = header_line.split(':', 1)
                response_headers[k.strip()] = v.strip()

    # body 在 stdout；若因 Windows echo 污染，这里已通过 @echo off 规避
    response_body = stdout or ''
    return response_headers, response_body


@app.route('/execute_curl', methods=['POST'])
def execute_curl():
    data = request.json or {}
    curl_command = data.get('curl_command', '')
    variables = data.get('variables', {})
    assertions = data.get('assertions', [])
    iterations = int(data.get('iterations') or 1)
    if iterations < 1:
        iterations = 1

    if not curl_command:
        return jsonify({'error': 'No curl command provided'}), 400

    # 支持 JSON 根为数组：批量执行
    try:
        if isinstance(variables, list):
            batch_id = _generate_result_id(is_batch=True)
            batch_results = []
            loop_items = variables[:iterations] if iterations and iterations <= len(variables) else variables
            for index, vars_item in enumerate(loop_items):
                try:
                    current_cmd = replace_variables(curl_command, vars_item)
                    parsed_req = _parse_curl_request(current_cmd)
                    result = _run_curl_script(current_cmd)
                    stdout = result.stdout or ''
                    stderr = result.stderr or ''
                    status_code = _extract_status_code(stdout, stderr)
                    resp_headers, resp_body = _parse_response_parts(stdout, stderr)
                    response_data = {
                        'code': status_code,
                        'stdout': stdout,
                        'stderr': stderr,
                        'returncode': result.returncode,
                        'raw': (stdout + "\n" + stderr).strip(),
                        'headers': resp_headers,
                        'body': resp_body
                    }
                    assertion_results = []
                    for assertion in assertions:
                        if isinstance(assertion, str) and assertion.strip():
                            assertion_results.append(evaluate_assertion(assertion, response_data))
                    row_result = {
                        'row_index': index + 1,
                        'variables': vars_item,
                        'curl_command': current_cmd,
                        'request': parsed_req,
                        'response': response_data,
                        'assertions': assertion_results,
                        'success': all(a.get('success', False) for a in assertion_results) if assertion_results else None
                    }
                    batch_results.append(row_result)
                except Exception as e:
                    batch_results.append({
                        'row_index': index + 1,
                        'variables': vars_item,
                        'error': str(e),
                        'success': False
                    })

            # 保存批量结果（标记为 batch 以复用前端/历史逻辑）
            batch_result_file = os.path.join(app.config['RESULTS_FOLDER'], f"{batch_id}.json")
            with open(batch_result_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'batch_id': batch_id,
                    'timestamp': time.time(),
                    'source': 'json_array',
                    'curl_command_template': curl_command,
                    'assertions': assertions,
                    'results': batch_results,
                    'total_rows': len(batch_results),
                    'success_count': sum(1 for r in batch_results if r.get('success', False)),
                    'failure_count': sum(1 for r in batch_results if r.get('success') is False)
                }, f, indent=2, ensure_ascii=False)

            return jsonify({
                'success': True,
                'batch_id': batch_id,
                'total_rows': len(batch_results),
                'success_count': sum(1 for r in batch_results if r.get('success', False)),
                'failure_count': sum(1 for r in batch_results if r.get('success') is False),
                'results': batch_results
            })

        # 单次/重复执行（KV 或 JSON 对象）
        if iterations > 1:
            batch_id = _generate_result_id(is_batch=True)
            batch_results = []
            for i in range(iterations):
                current_cmd = replace_variables(curl_command, variables)
                parsed_req = _parse_curl_request(current_cmd)
                result = _run_curl_script(current_cmd)
                stdout = result.stdout or ''
                stderr = result.stderr or ''
                status_code = _extract_status_code(stdout, stderr)
                resp_headers, resp_body = _parse_response_parts(stdout, stderr)
                response_data = {
                    'code': status_code,
                    'stdout': stdout,
                    'stderr': stderr,
                    'returncode': result.returncode,
                    'raw': (stdout + "\n" + stderr).strip(),
                    'headers': resp_headers,
                    'body': resp_body
                }
                assertion_results = []
                for assertion in assertions:
                    if isinstance(assertion, str) and assertion.strip():
                        assertion_results.append(evaluate_assertion(assertion, response_data))
                batch_results.append({
                    'row_index': i + 1,
                    'variables': variables,
                    'curl_command': current_cmd,
                    'request': parsed_req,
                    'response': response_data,
                    'assertions': assertion_results,
                    'success': all(a.get('success', False) for a in assertion_results) if assertion_results else None
                })

            batch_result_file = os.path.join(app.config['RESULTS_FOLDER'], f"{batch_id}.json")
            with open(batch_result_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'batch_id': batch_id,
                    'timestamp': time.time(),
                    'source': 'repeat_single',
                    'curl_command_template': curl_command,
                    'assertions': assertions,
                    'results': batch_results,
                    'total_rows': len(batch_results),
                    'success_count': sum(1 for r in batch_results if r.get('success', False)),
                    'failure_count': sum(1 for r in batch_results if r.get('success') is False)
                }, f, indent=2, ensure_ascii=False)

            return jsonify({
                'success': True,
                'batch_id': batch_id,
                'total_rows': len(batch_results),
                'success_count': sum(1 for r in batch_results if r.get('success', False)),
                'failure_count': sum(1 for r in batch_results if r.get('success') is False),
                'results': batch_results
            })

        curl_command = replace_variables(curl_command, variables)
        parsed_req = _parse_curl_request(curl_command)
        result = _run_curl_script(curl_command)

        stdout = result.stdout or ''
        stderr = result.stderr or ''
        status_code = _extract_status_code(stdout, stderr)
        resp_headers, resp_body = _parse_response_parts(stdout, stderr)

        response_data = {
            'code': status_code,
            'stdout': stdout,
            'stderr': stderr,
            'returncode': result.returncode,
            'raw': (stdout + "\n" + stderr).strip(),
            'headers': resp_headers,
            'body': resp_body
        }

        # 执行断言
        assertion_results = []
        for assertion in assertions:
            if isinstance(assertion, str) and assertion.strip():
                assertion_results.append(evaluate_assertion(assertion, response_data))

        # 生成唯一的结果ID
        result_id = _generate_result_id(is_batch=False)

        # 保存结果到文件
        result_file = os.path.join(app.config['RESULTS_FOLDER'], f"result_{result_id}.json")
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump({
                'id': result_id,
                'timestamp': time.time(),
                'curl_command': curl_command,
                'request': parsed_req,
                'variables': variables,
                'response': response_data,
                'assertions': assertion_results,
                'success': all(a.get('success', False) for a in assertion_results) if assertion_results else None
            }, f, indent=2, ensure_ascii=False)

        return jsonify({
            'success': True,
            'result_id': result_id,
            'stdout': stdout,
            'stderr': stderr,
            'returncode': result.returncode,
            'status_code': status_code,
            'assertions': assertion_results,
            'all_assertions_passed': all(a.get('success', False) for a in assertion_results) if assertion_results else None
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/execute_batch', methods=['POST'])
def execute_batch():
    data = request.json or {}
    excel_file = data.get('excel_file')
    curl_command_template = data.get('curl_command')
    assertions = data.get('assertions', [])
    limit = data.get('iterations')  # 可选限制执行次数

    if not excel_file or not curl_command_template:
        return jsonify({'error': 'Missing excel file or curl command'}), 400

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], excel_file)
    if not os.path.exists(filepath):
        return jsonify({'error': 'Excel file not found'}), 404

    try:
        df = pd.read_excel(filepath)
        if isinstance(limit, int) and limit > 0:
            df = df.head(limit)
    except Exception as e:
        return jsonify({'error': f'Failed to read Excel: {e}'}), 500

    batch_id = _generate_result_id(is_batch=True)
    batch_results = []

    try:
        for index, row in df.iterrows():
            variables = row.to_dict()
            # 填充模板
            current_cmd = replace_variables(curl_command_template, variables)

            try:
                result = _run_curl_script(current_cmd)

                stdout = result.stdout or ''
                stderr = result.stderr or ''
                status_code = _extract_status_code(stdout, stderr)

                resp_headers, resp_body = _parse_response_parts(stdout, stderr)
                response_data = {
                    'code': status_code,
                    'stdout': stdout,
                    'stderr': stderr,
                    'returncode': result.returncode,
                    'raw': (stdout + "\n" + stderr).strip(),
                    'headers': resp_headers,
                    'body': resp_body
                }

                assertion_results = []
                for assertion in assertions:
                    if isinstance(assertion, str) and assertion.strip():
                        assertion_results.append(evaluate_assertion(assertion, response_data))

                row_result = {
                    'row_index': index + 1,
                    'variables': variables,
                    'curl_command': current_cmd,
                    'request': _parse_curl_request(current_cmd),
                    'response': {
                        'stdout': stdout,
                        'stderr': stderr,
                        'returncode': result.returncode,
                        'status_code': status_code,
                        'headers': resp_headers,
                        'body': resp_body
                    },
                    'assertions': assertion_results,
                    'success': all(a.get('success', False) for a in assertion_results) if assertion_results else None
                }
                batch_results.append(row_result)

            except Exception as e:
                batch_results.append({
                    'row_index': index + 1,
                    'variables': variables,
                    'error': str(e),
                    'success': False
                })

        # 循环结束后统一保存与返回
        batch_result_file = os.path.join(app.config['RESULTS_FOLDER'], f"{batch_id}.json")
        with open(batch_result_file, 'w', encoding='utf-8') as f:
            json.dump({
                'batch_id': batch_id,
                'timestamp': time.time(),
                'excel_file': excel_file,
                'curl_command_template': curl_command_template,
                'assertions': assertions,
                'results': batch_results,
                'total_rows': len(batch_results),
                'success_count': sum(1 for r in batch_results if r.get('success', False)),
                'failure_count': sum(1 for r in batch_results if r.get('success') is False)
            }, f, indent=2, ensure_ascii=False)

        return jsonify({
            'success': True,
            'batch_id': batch_id,
            'total_rows': len(batch_results),
            'success_count': sum(1 for r in batch_results if r.get('success', False)),
            'failure_count': sum(1 for r in batch_results if r.get('success') is False),
            'results': batch_results
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/get_results', methods=['GET'])
def get_results():
    results_dir = app.config['RESULTS_FOLDER']
    result_files = [f for f in os.listdir(results_dir) if f.endswith('.json')]
    results = []

    for file in result_files:
        try:
            with open(os.path.join(results_dir, file), 'r', encoding='utf-8') as f:
                data = json.load(f)
                results.append({
                    'id': data.get('id') or data.get('batch_id'),
                    'timestamp': data.get('timestamp'),
                    'is_batch': 'batch_id' in data,
                    'success': data.get('success'),
                    'total_rows': data.get('total_rows'),
                    'success_count': data.get('success_count'),
                    'failure_count': data.get('failure_count'),
                    'filename': file
                })
        except Exception:
            pass

    # 按时间戳排序，最新的在前
    results.sort(key=lambda x: x.get('timestamp', 0) or 0, reverse=True)

    return jsonify({'success': True, 'results': results})


@app.route('/clear_results', methods=['POST'])
def clear_results():
    # 清理 results 目录下的所有结果文件（不仅是 .json）
    removed = 0
    errors = []
    results_dir = app.config['RESULTS_FOLDER']
    for name in os.listdir(results_dir):
        path = os.path.join(results_dir, name)
        try:
            if os.path.isfile(path):
                os.remove(path)
                removed += 1
            else:
                # 目录则尝试递归删除
                for root, dirs, files in os.walk(path, topdown=False):
                    for f in files:
                        try:
                            os.remove(os.path.join(root, f))
                            removed += 1
                        except Exception as e:
                            errors.append(str(e))
                    for d in dirs:
                        try:
                            os.rmdir(os.path.join(root, d))
                        except Exception:
                            pass
                try:
                    os.rmdir(path)
                except Exception:
                    pass
        except Exception as e:
            errors.append(str(e))

    return jsonify({'success': True, 'removed': removed, 'errors': errors})


@app.route('/get_result/<result_id>', methods=['GET'])
def get_result(result_id):
    results_dir = app.config['RESULTS_FOLDER']

    # 查找匹配的结果文件
    result_file = None
    for file in os.listdir(results_dir):
        if result_id in file and file.endswith('.json'):
            result_file = file
            break

    if not result_file:
        return jsonify({'error': 'Result not found'}), 404

    try:
        with open(os.path.join(results_dir, result_file), 'r', encoding='utf-8') as f:
            data = json.load(f)
            return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    # Flask 3.x 默认不再支持 use_reloader=True 与 debug=1 的某些旧行为；
    # 在容器或生产中建议 debug=False。这里保持和你原来一致。
    app.run(debug=False, host='0.0.0.0', port=5000)
