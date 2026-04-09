/**
 * 交易条件监控页面 JavaScript
 * 从 conditions.html 提取并优化
 */

// 全局变量
let socket = null;
let isConnected = false;
let currentFilter = 'all';
let conditionsData = [];

// 初始化
document.addEventListener('DOMContentLoaded', function() {
    console.log('交易条件监控页面初始化...');
    
    // 初始化 TradeUtils
    TradeUtils.init();
    
    // 绑定事件
    bindEvents();
    
    // 连接WebSocket
    connectWebSocket();
    
    // 加载初始数据
    loadInitialData();
    
    console.log('交易条件监控页面初始化完成');
});

/**
 * 绑定事件
 */
function bindEvents() {
    // 刷新按钮
    document.getElementById('refresh-quota').addEventListener('click', loadQuotaData);
    document.getElementById('refresh-conditions').addEventListener('click', loadConditionsData);
    
    // 筛选按钮
    document.querySelectorAll('[data-filter]').forEach(btn => {
        btn.addEventListener('click', handleFilterClick);
    });
}

/**
 * 处理筛选点击
 */
function handleFilterClick(event) {
    const filter = event.target.closest('[data-filter]').dataset.filter;
    
    // 更新按钮状态
    document.querySelectorAll('[data-filter]').forEach(btn => {
        btn.classList.remove('active');
    });
    event.target.closest('[data-filter]').classList.add('active');
    
    currentFilter = filter;
    renderConditions();
}

/**
 * 连接WebSocket
 */
function connectWebSocket() {
    try {
        socket = io();
        
        socket.on('connect', function() {
            console.log('WebSocket已连接');
            isConnected = true;
            TradeUtils.updateConnectionStatus(true);
        });
        
        socket.on('disconnect', function() {
            console.log('WebSocket已断开');
            isConnected = false;
            TradeUtils.updateConnectionStatus(false);
        });
        
        socket.on('conditions_update', function(data) {
            console.log('收到条件更新:', data);
            if (data.quota) {
                updateQuotaDisplay(data.quota);
            }
            if (data.conditions) {
                conditionsData = data.conditions;
                renderConditions();
            }
        });
        
    } catch (error) {
        console.error('WebSocket连接失败:', error);
    }
}

/**
 * 加载初始数据
 */
async function loadInitialData() {
    await Promise.all([
        loadSystemStatus(),
        loadQuotaData(),
        loadConditionsData()
    ]);
}

/**
 * 加载系统状态
 */
async function loadSystemStatus() {
    try {
        const result = await TradeUtils.get('/api/status');
        
        if (result.success) {
            updateSystemStatusDisplay(result.data);
        }
    } catch (error) {
        console.error('加载系统状态失败:', error);
    }
}

/**
 * 加载K线额度数据
 */
async function loadQuotaData() {
    try {
        const button = document.getElementById('refresh-quota');
        button.classList.add('data-updating');
        
        const result = await TradeUtils.get('/api/quota');
        
        if (result.success) {
            updateQuotaDisplay(result.data);
        } else {
            showToast('错误', `获取额度失败: ${result.message}`, 'danger');
        }
        
    } catch (error) {
        console.error('获取K线额度失败:', error);
        showToast('错误', '获取K线额度失败', 'danger');
    } finally {
        const button = document.getElementById('refresh-quota');
        button.classList.remove('data-updating');
    }
}

/**
 * 加载交易条件数据
 */
async function loadConditionsData() {
    try {
        const button = document.getElementById('refresh-conditions');
        button.classList.add('data-updating');
        
        const result = await TradeUtils.get('/api/trading-conditions');
        
        if (result.success) {
            conditionsData = result.data || [];
            renderConditions();
        } else {
            showToast('错误', `获取交易条件失败: ${result.message}`, 'danger');
        }
        
    } catch (error) {
        console.error('获取交易条件失败:', error);
        showToast('错误', '获取交易条件失败', 'danger');
    } finally {
        const button = document.getElementById('refresh-conditions');
        button.classList.remove('data-updating');
    }
}

/**
 * 更新系统状态显示
 */
function updateSystemStatusDisplay(data) {
    const systemStatus = document.getElementById('system-status');
    const icon = systemStatus.querySelector('i');
    
    if (data.is_running) {
        icon.className = 'fas fa-circle text-success';
        systemStatus.innerHTML = icon.outerHTML + ' 系统状态: 运行中';
    } else {
        icon.className = 'fas fa-circle text-danger';
        systemStatus.innerHTML = icon.outerHTML + ' 系统状态: 已停止';
    }
    
    const futuStatus = document.getElementById('futu-status');
    const futuIcon = futuStatus.querySelector('i');
    
    if (data.futu_connected) {
        futuIcon.className = 'fas fa-plug text-success';
        futuStatus.innerHTML = futuIcon.outerHTML + ' 富途: 已连接';
    } else {
        futuIcon.className = 'fas fa-plug text-warning';
        futuStatus.innerHTML = futuIcon.outerHTML + ' 富途: 模拟数据';
    }
}

/**
 * 更新额度显示
 */
function updateQuotaDisplay(quotaData) {
    document.getElementById('used-quota').textContent = quotaData.used || 0;
    document.getElementById('remaining-quota').textContent = quotaData.remaining || 0;
    document.getElementById('total-quota').textContent = quotaData.total || 0;
    
    const usagePercent = quotaData.total > 0 ? Math.round((quotaData.used / quotaData.total) * 100) : 0;
    document.getElementById('usage-percent').textContent = usagePercent + '%';
    
    // 更新进度条
    const progressBar = document.getElementById('quota-progress-bar');
    const quotaInfo = document.getElementById('quota-info');
    
    progressBar.style.width = usagePercent + '%';
    
    if (usagePercent < 50) {
        progressBar.className = 'progress-bar bg-success';
    } else if (usagePercent < 80) {
        progressBar.className = 'progress-bar bg-warning';
    } else {
        progressBar.className = 'progress-bar bg-danger';
    }
    
    quotaInfo.textContent = `${quotaData.used}/${quotaData.total} (${usagePercent}%)`;
    
    document.getElementById('quota-last-update').textContent = 
        formatTimestamp(quotaData.last_update || new Date().toISOString());
}

/**
 * 渲染条件列表
 */
function renderConditions() {
    const container = document.getElementById('conditions-container');
    const countBadge = document.getElementById('conditions-count');
    
    let filteredData = conditionsData;
    
    if (currentFilter === 'pass') {
        filteredData = conditionsData.filter(item => item.condition_passed);
    } else if (currentFilter === 'fail') {
        filteredData = conditionsData.filter(item => !item.condition_passed);
    }
    
    countBadge.textContent = filteredData.length;
    
    if (filteredData.length === 0) {
        container.innerHTML = `
            <div class="text-center py-5">
                <i class="fas fa-info-circle fa-3x text-muted mb-3"></i>
                <div class="text-muted">
                    ${currentFilter === 'all' ? '暂无交易条件数据' : 
                      currentFilter === 'pass' ? '暂无符合条件的股票' : '暂无不符合条件的股票'}
                </div>
            </div>
        `;
        return;
    }
    
    const conditionsHtml = filteredData.map(condition => {
        const cardClass = condition.condition_passed ? 'condition-pass' : 'condition-fail';
        const iconClass = condition.condition_passed ? 'pass' : 'fail';
        const iconName = condition.condition_passed ? 'fa-check-circle' : 'fa-times-circle';
        
        // 显示状态文本
        const statusText = condition.condition_passed ? '符合条件' : '不符合条件';
        const statusBadgeClass = condition.condition_passed ? 'bg-success' : 'bg-danger';
        
        // 交易信号显示
        let signalBadge = '';
        if (condition.buy_signal) {
            signalBadge = '<span class="badge bg-primary ms-2">买入信号</span>';
        } else if (condition.sell_signal) {
            signalBadge = '<span class="badge bg-warning ms-2">卖出信号</span>';
        }
        
        return `
            <div class="condition-card ${cardClass} mb-3">
                <div class="card-body">
                    <div class="row align-items-center">
                        <div class="col-md-1 text-center">
                            <i class="fas ${iconName} condition-status-icon ${iconClass}"></i>
                        </div>
                        <div class="col-md-3">
                            <h6 class="mb-1">${condition.stock_code}</h6>
                            <small class="text-muted">${condition.stock_name || '-'}</small>
                            ${condition.plate_name ? `<br><small class="text-info">${condition.plate_name}</small>` : ''}
                        </div>
                        <div class="col-md-2">
                            <small class="text-muted">策略</small>
                            <div>${condition.strategy_name || '低吸高抛策略'}</div>
                            <span class="badge ${statusBadgeClass}">${statusText}</span>${signalBadge}
                        </div>
                        <div class="col-md-6">
                            <small class="text-muted">条件详情</small>
                            <div class="condition-details">
                                ${renderConditionDetails(condition)}
                            </div>
                        </div>
                    </div>
                    ${condition.reason ? `
                        <div class="row mt-2">
                            <div class="col-12">
                                <small class="text-muted">
                                    <i class="fas fa-comment me-1"></i>
                                    <strong>详细说明：</strong>${condition.reason}
                                </small>
                            </div>
                        </div>
                    ` : ''}
                    ${condition.timestamp ? `
                        <div class="row mt-1">
                            <div class="col-12">
                                <small class="text-muted">
                                    <i class="fas fa-clock me-1"></i>
                                    检查时间：${formatTimestamp(condition.timestamp)}
                                </small>
                            </div>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }).join('');
    
    container.innerHTML = conditionsHtml;
}

/**
 * 渲染条件详情
 */
function renderConditionDetails(condition) {
    if (!condition.details || condition.details.length === 0) {
        // 如果没有详细信息，显示基本的原因
        return condition.reason ? `<div class="text-muted">${condition.reason}</div>` : '暂无详细信息';
    }
    
    return condition.details.map(detail => {
        const statusIcon = detail.passed ? '✅' : '❌';
        const statusClass = detail.passed ? 'text-success' : 'text-danger';
        
        return `
            <div class="mb-2 p-2 border rounded">
                <div class="d-flex align-items-start">
                    <span class="me-2" style="font-size: 1.2em;">${statusIcon}</span>
                    <div class="flex-grow-1">
                        <strong class="${statusClass}">${detail.name}</strong>
                        <div class="mt-1">
                            <span class="condition-value current">当前值: ${detail.current_value || '-'}</span>
                            <span class="condition-value target">目标值: ${detail.target_value || '-'}</span>
                        </div>
                        ${detail.description ? `<div class="mt-1"><small class="text-muted">${detail.description}</small></div>` : ''}
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

console.log('交易条件监控页面脚本加载完成');
