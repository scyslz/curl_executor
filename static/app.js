// 全局变量
let currentVariables = {};
let currentExcelFile = null;
let curlEditor, jsonEditor;
let historyAutoRefreshTimer = null;

// 初始化页面
document.addEventListener('DOMContentLoaded', function() {
    // 初始化CodeMirror编辑器
    curlEditor = CodeMirror.fromTextArea(document.getElementById('curlCommand'), {
        mode: 'shell',
        theme: 'monokai',
        lineNumbers: true,
        lineWrapping: true
    });
    
    jsonEditor = CodeMirror.fromTextArea(document.getElementById('jsonVariables'), {
        mode: { name: 'javascript', json: true },
        theme: 'monokai',
        lineNumbers: false,
        lineWrapping: true
    });
    
    // 添加初始断言
    addAssertion();
    
    // 添加初始KV变量
    addKvEntry();
    
    // 应用初始JSON变量
    applyJsonVariables();
    
    // 绑定事件处理程序
    bindEventHandlers();
    
    // 加载历史记录
    loadHistory();
});

// 绑定事件处理程序
function bindEventHandlers() {
    // 执行按钮
    const execBtn = document.getElementById('executeBtn');
    if (execBtn) execBtn.addEventListener('click', executeCurl);

    // 变量面板中的循环执行按钮
    const loopBtn = document.getElementById('loopExecuteBtn');
    if (loopBtn) loopBtn.addEventListener('click', executeBatch);
    
    // 应用JSON变量按钮
    // 去除“应用JSON变量”按钮后，改为实时解析：在 JSON 编辑器 blur 时刷新次数
    jsonEditor.on('blur', applyJsonVariables);
    
    // 添加KV变量按钮
    const addKvBtn = document.getElementById('addKvBtn');
    if (addKvBtn) addKvBtn.addEventListener('click', addKvEntry);
    
    // 应用KV变量按钮
    // 去除“应用KV变量”按钮：在 KV 输入 blur 时更新 currentVariables
    document.addEventListener('blur', function(e) {
        if (e.target && (e.target.classList.contains('kv-key') 
            || e.target.classList.contains('kv-value'))) {
            applyKvVariables();
        }
    }, true);

    // 鼠标离开“执行次数”输入时归一化
    const itElBlur = document.getElementById('iterationsInput');
    if (itElBlur) {
        itElBlur.addEventListener('blur', function() {
            const v = Math.max(1, parseInt(this.value || '1', 10));
            this.value = v;
        });
    }
    
    // 添加断言按钮
    const addAssertionBtn = document.getElementById('addAssertionBtn');
    if (addAssertionBtn) addAssertionBtn.addEventListener('click', addAssertion);
    
    // Excel文件上传
    const excelFile = document.getElementById('excelFile');
    if (excelFile) excelFile.addEventListener('change', handleExcelUpload);
    
    // 刷新历史按钮
    const refreshBtn = document.getElementById('refreshHistoryBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', loadHistory);

    // 清理历史按钮
    const clearBtn = document.getElementById('clearHistoryBtn');
    if (clearBtn) clearBtn.addEventListener('click', clearHistory);

    // 自动刷新开关
    const autoChk = document.getElementById('autoRefreshHistory');
    if (autoChk) autoChk.addEventListener('change', function(e) {
        if (e.target.checked) {
            startHistoryAutoRefresh();
        } else {
            stopHistoryAutoRefresh();
        }
    });

    // 主Tab切换时，确保批量结果面板只在“变量设置”页可见
    const mainTabs = document.getElementById('mainTabs');
    if (mainTabs) {
        mainTabs.addEventListener('shown.bs.tab', function(e) {
            const target = e.target && e.target.getAttribute('data-bs-target');
            const batchPanel = document.getElementById('batchResultsPanel');
            if (!batchPanel) return;
            if (target === '#variables') {
                batchPanel.classList.add('show');
                batchPanel.classList.add('active');
            } else {
                batchPanel.classList.remove('show');
                batchPanel.classList.remove('active');
            }
        });
    }

    // 执行次数输入变化时，更新显示但不强制改变 JSON/Excel 计数来源
    const itElInput = document.getElementById('iterationsInput');
    if (itElInput) {
        itElInput.addEventListener('input', function() {
            const v = Math.max(1, parseInt(this.value || '1', 10));
            this.value = v;
        });
    }
}

// 添加KV变量条目
function addKvEntry() {
    const container = document.getElementById('kvContainer');
    const entryDiv = document.createElement('div');
    entryDiv.className = 'input-group mb-2';
    
    entryDiv.innerHTML = `
        <input type="text" class="form-control kv-key" placeholder="变量名">
        <input type="text" class="form-control kv-value" placeholder="变量值">
        <button class="btn btn-outline-danger delete-kv-btn" type="button">删除</button>
    `;
    
    container.appendChild(entryDiv);
    
    // 绑定删除按钮事件
    entryDiv.querySelector('.delete-kv-btn').addEventListener('click', function() {
        if (container.children.length > 1) {
            container.removeChild(entryDiv);
        }
    });
}

// 添加断言条目
function addAssertion() {
    const container = document.getElementById('assertionsContainer');
    const assertionDiv = document.createElement('div');
    assertionDiv.className = 'assertion-item';
    
    assertionDiv.innerHTML = `
        <input type="text" class="form-control assertion-input" placeholder="例如: response.code == 200">
        <button class="btn btn-outline-danger delete-assertion-btn">删除</button>
    `;
    
    container.appendChild(assertionDiv);
    
    // 绑定删除按钮事件
    assertionDiv.querySelector('.delete-assertion-btn').addEventListener('click', function() {
        container.removeChild(assertionDiv);
    });
}

// 应用JSON变量
function applyJsonVariables() {
    try {
        const jsonText = jsonEditor.getValue();
        if (jsonText.trim()) {
            currentVariables = JSON.parse(jsonText);
            // 更新计划次数
            const planned = Array.isArray(currentVariables) ? currentVariables.length : 1;
            const el = document.getElementById('jsonPlannedCount');
            if (el) el.textContent = planned;
            const itEl = document.getElementById('iterationsInput');
            if (itEl) itEl.value = planned;
            const plannedTotal = document.getElementById('plannedTotal');
            if (plannedTotal) plannedTotal.textContent = planned;
        }
    } catch (e) {
        // 忽略临时输入错误，直到用户点击格式化或执行
    }
}

// 应用KV变量
function applyKvVariables() {
    currentVariables = {};
    const keyInputs = document.querySelectorAll('.kv-key');
    const valueInputs = document.querySelectorAll('.kv-value');
    for (let i = 0; i < keyInputs.length; i++) {
        const key = keyInputs[i].value.trim();
        const value = valueInputs[i].value;
        if (key) currentVariables[key] = value;
    }
}

// 更新变量预览
function updateVariablesPreview() { /* 已移除当前变量预览，函数保留避免报错 */ }

// 处理Excel上传
function handleExcelUpload(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    const formData = new FormData();
    formData.append('file', file);
    
    // 显示加载状态
    document.getElementById('excelFile').disabled = true;
    
    fetch('/upload_excel', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            currentExcelFile = data.filename;
            
            // 显示Excel预览
            const previewDiv = document.getElementById('excelPreview');
            previewDiv.classList.remove('d-none');
            
            // 设置表头
            const headerRow = document.getElementById('excelPreviewHeader');
            headerRow.innerHTML = '';
            const headerTr = document.createElement('tr');
            
            data.columns.forEach(column => {
                const th = document.createElement('th');
                th.textContent = column;
                headerTr.appendChild(th);
            });
            
            headerRow.appendChild(headerTr);
            
            // 设置表体
            const tableBody = document.getElementById('excelPreviewBody');
            tableBody.innerHTML = '';
            
            data.preview.forEach(row => {
                const tr = document.createElement('tr');
                
                data.columns.forEach(column => {
                    const td = document.createElement('td');
                    td.textContent = row[column] !== undefined ? row[column] : '';
                    tr.appendChild(td);
                });
                
                tableBody.appendChild(tr);
            });
            // 显示预计执行次数
            const plannedEl = document.getElementById('excelPlannedCount');
            if (plannedEl && data.total_rows !== undefined && data.total_rows !== null) {
                plannedEl.textContent = data.total_rows;
            }
            const itEl = document.getElementById('iterationsInput');
            if (itEl && data.total_rows) itEl.value = data.total_rows;
            const plannedTotal = document.getElementById('plannedTotal');
            if (plannedTotal && data.total_rows) plannedTotal.textContent = data.total_rows;
        } else {
            alert('上传Excel失败: ' + data.error);
        }
    })
    .catch(error => {
        alert('上传Excel出错: ' + error);
    })
    .finally(() => {
        document.getElementById('excelFile').disabled = false;
    });
}

// 执行curl命令
function executeCurl() {
    const curlCommand = curlEditor.getValue();
    if (!curlCommand.trim()) {
        alert('请输入curl命令');
        return;
    }
    
    // 获取断言
    const assertions = [];
    document.querySelectorAll('.assertion-input').forEach(input => {
        const assertion = input.value.trim();
        if (assertion) {
            assertions.push(assertion);
        }
    });
    

    
    // 显示加载状态
    const executeBtn = document.getElementById('executeBtn');
    executeBtn.classList.add('loading');
    executeBtn.disabled = true;
    
    fetch('/execute_curl', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            curl_command: curlCommand,
            variables: Array.isArray(currentVariables) && currentVariables.length > 0 ? currentVariables[0] : currentVariables,
            assertions: assertions,
            use_python: false  // 添加开关状态
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // 如果是 JSON 数组变量引发的批量执行，填充批量结果区
            if (data.results && Array.isArray(data.results)) {
                document.getElementById('totalRowsResult').textContent = data.total_rows;
                document.getElementById('successCountResult').textContent = data.success_count;
                document.getElementById('failureCountResult').textContent = data.failure_count;

                const tableBody = document.getElementById('batchResultsBody');
                tableBody.innerHTML = '';

                data.results.forEach(result => {
                    const tr = document.createElement('tr');

                    const tdRow = document.createElement('td');
                    tdRow.textContent = result.row_index;
                    tr.appendChild(tdRow);

                    const tdVars = document.createElement('td');
                    tdVars.innerHTML = `<pre class="m-0" style="max-height: 100px; overflow: auto;">${JSON.stringify(result.variables, null, 2)}</pre>`;
                    tr.appendChild(tdVars);

                    const tdStatus = document.createElement('td');
                    if (result.response && result.response.code) {
                        tdStatus.textContent = result.response.code;
                    } else if (result.response && result.response.status_code) {
                        tdStatus.textContent = result.response.status_code;
                    } else if (result.error) {
                        tdStatus.innerHTML = `<span class="text-danger">错误</span>`;
                    } else {
                        tdStatus.textContent = '未知';
                    }
                    tr.appendChild(tdStatus);

                    const tdAssert = document.createElement('td');
                    if (result.success === true) {
                        tdAssert.innerHTML = `<span class="result-success">通过</span>`;
                    } else if (result.success === false) {
                        tdAssert.innerHTML = `<span class="result-failure">失败</span>`;
                    } else {
                        tdAssert.textContent = '无断言';
                    }
                    tr.appendChild(tdAssert);

                    const tdAction = document.createElement('td');
                    const viewBtn = document.createElement('button');
                    viewBtn.className = 'btn btn-sm btn-info';
                    viewBtn.textContent = '查看详情';
                    viewBtn.addEventListener('click', () => {
                        showDetail(result);
                    });
                    tdAction.appendChild(viewBtn);
                    tr.appendChild(tdAction);

                    tableBody.appendChild(tr);
                });
                // 显示变量页下方批量结果面板
                const variablesTab = new bootstrap.Tab(document.getElementById('variables-tab'));
                variablesTab.show();
                document.getElementById('batchResultsPanel').classList.add('show');
                document.getElementById('batchResultsPanel').classList.add('active');
            } else {
                // 在命令输入页下方展示单次输出
                const panel = document.getElementById('singleResultPanel');
                panel.classList.remove('d-none');
                document.getElementById('singleStdout').textContent = data.stdout || '(无输出)';
                document.getElementById('singleStderr').textContent = data.stderr || '(无错误)';
                document.getElementById('singleReturnCode').textContent = data.returncode;
                document.getElementById('singleStatusCode').textContent = 
                    data.status_code ? data.status_code : '未知';
            }

        
            // 顶部行内断言汇总
            const inlineEl = document.getElementById('singleAssertionsInline');
            if (inlineEl) {
                if (data.assertions && data.assertions.length) {
                    const allPassed = data.all_assertions_passed;
                    inlineEl.className = allPassed ? 'result-success' : 'result-failure';
                    inlineEl.textContent = allPassed ? '全部通过' : '部分失败';
                } else {
                    inlineEl.className = 'text-muted';
                    inlineEl.textContent = '无断言';
                }
            }
            
            // 在命令输入页结果卡片下追加断言结果
            const panel = document.getElementById('singleResultPanel');
            let assertBlock = document.getElementById('singleAssertions');
            if (!assertBlock) {
                assertBlock = document.createElement('div');
                assertBlock.id = 'singleAssertions';
                assertBlock.className = 'mt-3';
                panel.querySelector('.card-body').appendChild(assertBlock);
            }
            assertBlock.innerHTML = '';

            if (data.assertions && data.assertions.length > 0) {
                const title = document.createElement('h6');
                title.textContent = '断言结果';
                assertBlock.appendChild(title);
                data.assertions.forEach(assertion => {
                    const div = document.createElement('div');
                    div.className = 'mb-2';
                    const resultClass = assertion.success ? 'result-success' : 'result-failure';
                    const resultText = assertion.success ? '通过' : '失败';
                    div.innerHTML = `
                        <strong>断言:</strong> <code>${assertion.assertion}</code>
                        <span class="${resultClass} ms-2">${resultText}</span>
                        ${assertion.error ? `<div class="text-danger">错误: ${assertion.error}</div>` : ''}
                    `;
                    assertBlock.appendChild(div);
                });
                const overall = document.createElement('div');
                const allPassed = data.all_assertions_passed;
                overall.innerHTML = `<strong>总体结果:</strong> <span class="${allPassed ? 'result-success' : 'result-failure'}">${allPassed ? '全部通过' : '部分失败'}</span>`;
                assertBlock.appendChild(overall);
            } else {
                assertBlock.textContent = '无断言';
            }
        } else {
            alert('执行失败: ' + data.error);
        }
    })
    .catch(error => {
        alert('执行出错: ' + error);
    })
    .finally(() => {
        executeBtn.classList.remove('loading');
        executeBtn.disabled = false;
    });
}

// 执行批量命令
function executeBatch() {
    const curlCommand = curlEditor.getValue();
    if (!curlCommand.trim()) {
        alert('请输入curl命令');
        return;
    }
    
    // 获取断言
    const assertions = [];
    document.querySelectorAll('.assertion-input').forEach(input => {
        const assertion = input.value.trim();
        if (assertion) {
            assertions.push(assertion);
        }
    });
    
    // 基于当前激活的变量来源来取值，避免切换 tab 后状态不同步
    const source = (function(){
        const jsonPane = document.getElementById('json');
        const kvPane = document.getElementById('kv');
        const excelPane = document.getElementById('excel');
        if (jsonPane && jsonPane.classList.contains('active')) return 'json';
        if (kvPane && kvPane.classList.contains('active')) return 'kv';
        if (excelPane && excelPane.classList.contains('active')) return 'excel';
        return 'json';
    })();

    let localVariables = currentVariables;
    if (source === 'json') {
        try {
            const txt = jsonEditor.getValue();
            localVariables = txt && txt.trim() ? JSON.parse(txt) : {};
        } catch (e) {
            alert('JSON格式无效: ' + e.message);
            return;
        }
    } else if (source === 'kv') {
        // 从 DOM 读取最新 KV
        localVariables = {};
        const keyInputs = document.querySelectorAll('.kv-key');
        const valueInputs = document.querySelectorAll('.kv-value');
        for (let i = 0; i < keyInputs.length; i++) {
            const key = (keyInputs[i].value || '').trim();
            const val = valueInputs[i] ? valueInputs[i].value : '';
            if (key) localVariables[key] = val;
        }
    } else if (source === 'excel') {
        // 保持使用 excel 文件
    }

    const useJsonArray = Array.isArray(localVariables) && localVariables.length > 0;
    const hasExcel = !!currentExcelFile && source === 'excel';

    const iterations = Math.max(1, parseInt((document.getElementById('iterationsInput') || {}).value || '1', 10));
    const payload = { curl_command: curlCommand, assertions, iterations };
    let url = '';
    if (useJsonArray) {
        url = '/execute_curl';
        payload.variables = localVariables;
    } else if (hasExcel) {
        url = '/execute_batch';
        payload.excel_file = currentExcelFile;
        payload.iterations = iterations; // 限制前 N 行
    } else {
        if (Object.keys(localVariables || {}).length > 0 && iterations > 1) {
            url = '/execute_curl';
            payload.variables = [JSON.parse(JSON.stringify(localVariables))];
            payload.iterations = iterations;
        } else {
            url = '/execute_curl';
            payload.variables = [JSON.parse(JSON.stringify(localVariables))];
        }
    }

    fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // 显示批量结果统计（变量页下方）
            document.getElementById('totalRowsResult').textContent = data.total_rows;
            document.getElementById('successCountResult').textContent = data.success_count;
            document.getElementById('failureCountResult').textContent = data.failure_count;
            
            // 显示批量结果详情
            const tableBody = document.getElementById('batchResultsBody');
            tableBody.innerHTML = '';
            
            data.results.forEach(result => {
                const tr = document.createElement('tr');
                
                // 行号
                const tdRow = document.createElement('td');
                tdRow.textContent = result.row_index;
                tr.appendChild(tdRow);
                
                // 变量
                const tdVars = document.createElement('td');
                tdVars.innerHTML = `<pre class="m-0" style="max-height: 100px; overflow: auto;">${JSON.stringify(result.variables, null, 2)}</pre>`;
                tr.appendChild(tdVars);
                
                // 状态码
                const tdStatus = document.createElement('td');
                if (result.response && result.response.status_code) {
                    tdStatus.textContent = result.response.status_code;
                } else if (result.error) {
                    tdStatus.innerHTML = `<span class="text-danger">错误</span>`;
                } else {
                    tdStatus.textContent = '未知';
                }
                tr.appendChild(tdStatus);
                
                // 断言结果
                const tdAssert = document.createElement('td');
                if (result.success === true) {
                    tdAssert.innerHTML = `<span class="result-success">通过</span>`;
                } else if (result.success === false) {
                    tdAssert.innerHTML = `<span class="result-failure">失败</span>`;
                } else {
                    tdAssert.textContent = '无断言';
                }
                tr.appendChild(tdAssert);
                
                // 操作
                const tdAction = document.createElement('td');
                const viewBtn = document.createElement('button');
                viewBtn.className = 'btn btn-sm btn-info';
                viewBtn.textContent = '查看详情';
                viewBtn.addEventListener('click', () => {
                    showDetail(result);
                });
                tdAction.appendChild(viewBtn);
                tr.appendChild(tdAction);
                
                tableBody.appendChild(tr);
            });
            // 切回变量Tab并展示批量结果面板
            const variablesTabBtn = document.getElementById('variables-tab');
            if (variablesTabBtn) new bootstrap.Tab(variablesTabBtn).show();
            const panel = document.getElementById('batchResultsPanel');
            if (panel) { panel.classList.add('show'); panel.classList.add('active'); }
            
            // 加载历史记录
            loadHistory();
        } else {
            alert('批量执行失败: ' + data.error);
        }
    })
    .catch(error => {
        alert('批量执行出错: ' + error);
    })
    .finally(() => {
        const loopBtn = document.getElementById('loopExecuteBtn');
        if (loopBtn) {
            loopBtn.classList.remove('loading');
            loopBtn.disabled = false;
        }
    });
}

function clearHistory() {
    if (!confirm('确定清理所有历史记录吗？')) return;
    fetch('/clear_results', { method: 'POST' })
    .then(r => r.json())
    .then(d => {
        if (d.success) {
            loadHistory();
        } else {
            alert('清理失败');
        }
    })
    .catch(e => alert('清理出错: ' + e));
}

function startHistoryAutoRefresh() {
    if (historyAutoRefreshTimer) return;
    historyAutoRefreshTimer = setInterval(loadHistory, 3000);
}

function stopHistoryAutoRefresh() {
    if (historyAutoRefreshTimer) {
        clearInterval(historyAutoRefreshTimer);
        historyAutoRefreshTimer = null;
    }
}

// 加载历史记录
function loadHistory() {
    fetch('/get_results')
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            const tableBody = document.getElementById('historyTableBody');
            tableBody.innerHTML = '';
            
            data.results.forEach(result => {
                const tr = document.createElement('tr');
                
                // ID
                const tdId = document.createElement('td');
                tdId.textContent = result.id;
                tr.appendChild(tdId);
                
                // 时间
                const tdTime = document.createElement('td');
                const date = new Date(result.timestamp * 1000);
                tdTime.textContent = date.toLocaleString();
                tr.appendChild(tdTime);
                
                // 类型
                const tdType = document.createElement('td');
                tdType.textContent = result.is_batch ? '批量执行' : '单次执行';
                tr.appendChild(tdType);
                
                // 结果
                const tdResult = document.createElement('td');
                if (result.success === true) {
                    tdResult.innerHTML = `<span class="result-success">成功</span>`;
                } else if (result.success === false) {
                    tdResult.innerHTML = `<span class="result-failure">失败</span>`;
                } else if (result.total_rows) {
                    tdResult.innerHTML = `<span class="result-success">${result.success_count}</span>/<span class="result-failure">${result.failure_count}</span>/${result.total_rows}`;
                } else {
                    tdResult.textContent = '未知';
                }
                tr.appendChild(tdResult);
                
                // 操作
                const tdAction = document.createElement('td');
                const viewBtn = document.createElement('button');
                viewBtn.className = 'btn btn-sm btn-info';
                viewBtn.textContent = '查看';
                viewBtn.addEventListener('click', () => {
                    loadResultDetail(result.id);
                });
                tdAction.appendChild(viewBtn);
                tr.appendChild(tdAction);
                
                tableBody.appendChild(tr);
            });
        } else {
            alert('加载历史记录失败');
        }
    })
    .catch(error => {
        alert('加载历史记录出错: ' + error);
    });
}

// 加载结果详情
function loadResultDetail(resultId) {
    fetch(`/get_result/${resultId}`)
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showDetail(data.data);
        } else {
            alert('加载结果详情失败: ' + data.error);
        }
    })
    .catch(error => {
        alert('加载结果详情出错: ' + error);
    });
}

// 显示详情模态框
function showDetail(data) {
    // 优化显示：将请求与响应分区展示，headers/body/params 等
    const detailContent = document.getElementById('detailContent');
    let viewModel;
    // 批量
    if (data && data.results && Array.isArray(data.results)) {
        viewModel = {
            type: 'batch',
            batch_id: data.batch_id,
            timestamp: data.timestamp,
            curl_command_template: data.curl_command_template,
            assertions: data.assertions,
            total_rows: data.total_rows,
            success_count: data.success_count,
            failure_count: data.failure_count,
            results: data.results.map(r => ({
                row_index: r.row_index,
                variables: r.variables,
                request: r.request || {},
                response: r.response || {},
                assertions: r.assertions || [],
                success: r.success
            }))
        };
    } else {
        // 单次
        viewModel = {
            type: 'single',
            id: data.id,
            timestamp: data.timestamp,
            curl_command: data.curl_command,
            request: data.request || {},
            variables: data.variables,
            response: data.response || {},
            assertions: data.assertions || [],
            success: data.success
        };
    }
    detailContent.textContent = JSON.stringify(viewModel, null, 2);
    
    const modal = new bootstrap.Modal(document.getElementById('detailModal'));
    modal.show();
}