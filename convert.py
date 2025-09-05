import re
import json

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


# ==== 测试 ====
if __name__ == "__main__":
    cmd_cmd = r'''curl ^"http://localhost:5000/api?age={{age}}^" ^
  -H ^"Content-Type: application/json^" ^
  --data-raw {{body}} ^'''

    cmd_bash = """curl 'http://localhost:5000/api' \
  -H 'Content-Type: application/json' \
  --data-raw {{body}}"""

    vars_data = {"body": {"name": "Tom", "age": 18},"age": 18}

    print("CMD 测试：")
    print(replace_variables(cmd_cmd, vars_data))
    print("-" * 50)
    print("Bash 测试：")
    print(replace_variables(cmd_bash, vars_data))
