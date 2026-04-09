/**
 * 策略监控 - 信号展示模块
 * 功能：信号展示、信号历史、信号处理
 * 
 * 依赖：AppState (全局状态对象)
 */

// ==================== 信号加载 ====================

/**
 * 加载今日实时信号
 */
async function loadTodaySignals() {
    try {
        const response = await fetch('/api/strategy/signals?type=today');
        const data = await response.json();
        
        if (data.success) {
            AppState.todaySignals = data.data.signals || [];
            renderSignalsContainer();
            updateRealtimeSignalCounts(AppState.todaySignals);
            console.log('[今日信号] 加载完成，共', AppState.todaySignals.length, '条');
        }
    } catch (error) {
        console.error('加载今日信号失败:', error);
    }
}

/**
 * 加载历史信号（今日以前的）
 */
async function loadHistorySignals() {
    try {
        const daysSelect = document.getElementById('history-days-select');
        const days = daysSelect ? parseInt(daysSelect.value) || 30 : 30;
        
        const response = await fetch(`/api/strategy/signals?type=history&days=${days}`);
        const data = await response.json();
        
        if (data.success) {
            AppState.historySignals = data.data.signals || [];
            renderHistoryTable();
            console.log('[历史信号] 加载完成，共', AppState.historySignals.length, '条');
        }
    } catch (error) {
        console.error('加载历史信号失败:', error);
    }
}

/**
 * 兼容旧函数
 */
async function loadSignalHistory(type = 'today') {
    if (type === 'today') {
        await loadTodaySignals();
    } else {
        await loadHistorySignals();
    }
}

// ==================== 信号处理 ====================

/**
 * 统一的信号处理函数
 */
function handleSignals(signals) {
    if (!signals || signals.length === 0) return;
    
    console.log('[信号处理] 收到新信号:', signals.length, '个，从数据库刷新今日信号');
    
    playSignalSound();
    loadSignalHistory('today');
    loadStockPool();
}

/**
 * 信号去重（同一批次内去重）
 */
function deduplicateSignals(signals) {
    const signalMap = new Map();
    
    signals.forEach(signal => {
        const key = `${signal.stock_code}_${signal.signal_type}`;
        const existing = signalMap.get(key);
        
        if (!existing) {
            signalMap.set(key, signal);
        } else {
            const existingTime = new Date(existing.timestamp || 0).getTime();
            const newTime = new Date(signal.timestamp || 0).getTime();
            if (newTime > existingTime) {
                signalMap.set(key, signal);
            }
        }
    });
    
    return Array.from(signalMap.values());
}

// ==================== 信号计数 ====================

/**
 * 更新实时信号计数显示
 */
function updateRealtimeSignalCounts(signals) {
    let buyCount = 0;
    let sellCount = 0;
    
    signals.forEach(signal => {
        if (signal.signal_type === 'BUY') {
            buyCount++;
        } else if (signal.signal_type === 'SELL') {
            sellCount++;
        }
    });
    
    const buyCountEl = document.getElementById('buy-signal-count');
    const sellCountEl = document.getElementById('sell-signal-count');
    
    if (buyCountEl) buyCountEl.textContent = buyCount;
    if (sellCountEl) sellCountEl.textContent = sellCount;
    
    console.log('[信号统计] 买入信号:', buyCount, '卖出信号:', sellCount);
}

/**
 * 从股票列表统计信号数量
 */
function updateSignalCountsFromStocks(stocks) {
    let buyCount = 0;
    let sellCount = 0;
    
    stocks.forEach(stock => {
        const conditions = stock.trading_conditions;
        if (conditions) {
            if (conditions.buy_signal || conditions.is_buy_point) {
                buyCount++;
            }
            if (conditions.sell_signal || conditions.is_sell_point) {
                sellCount++;
            }
        }
    });
    
    const buyCountEl = document.getElementById('buy-signal-count');
    const sellCountEl = document.getElementById('sell-signal-count');
    
    if (buyCountEl) buyCountEl.textContent = buyCount;
    if (sellCountEl) sellCountEl.textContent = sellCount;
    
    console.log('[信号统计] 买入信号:', buyCount, '卖出信号:', sellCount);
}

// ==================== 信号渲染 ====================

/**
 * 渲染实时信号卡片
 */
function renderSignalsContainer() {
    const container = document.getElementById('signals-container');
    if (!container) return;
    
    if (!AppState.todaySignals || AppState.todaySignals.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">📭</span>
                <p>暂无今日信号，请启动监控</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = AppState.todaySignals.slice(0, 20).map(signal => {
        const signalClass = signal.signal_type === 'BUY' ? 'buy' : 'sell';
        const signalText = signal.signal_type === 'BUY' ? '买入' : '卖出';
        const signalIcon = signal.signal_type === 'BUY' ? '🟢' : '🔴';
        const time = signal.timestamp ? 
            new Date(signal.timestamp).toLocaleString('zh-CN', { 
                hour: '2-digit', 
                minute: '2-digit' 
            }) : '--';
        
        return `
            <div class="signal-card ${signalClass}" onclick="viewStockDetail('${signal.stock_code}')">
                <div class="signal-card-header">
                    <span class="signal-icon">${signalIcon}</span>
                    <span class="signal-type">${signalText}</span>
                    <span class="signal-time">${time}</span>
                </div>
                <div class="signal-card-body">
                    <div class="stock-info">
                        <span class="stock-code">${signal.stock_code}</span>
                        <span class="stock-name">${signal.stock_name || ''}</span>
                    </div>
                    <div class="signal-price">￥${signal.price ? signal.price.toFixed(2) : '--'}</div>
                </div>
                <div class="signal-card-footer">
                    <span class="signal-reason">${signal.reason || ''}</span>
                </div>
            </div>
        `;
    }).join('');
}

/**
 * 渲染历史信号表格
 */
function renderHistoryTable() {
    const tbody = document.getElementById('history-table-body');
    if (!tbody) return;
    
    if (!AppState.historySignals || AppState.historySignals.length === 0) {
        tbody.innerHTML = `
            <tr class="empty-row">
                <td colspan="6">
                    <div class="empty-state">
                        <span class="empty-icon">📝</span>
                        <p>暂无历史记录</p>
                    </div>
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = AppState.historySignals.map(signal => {
        const signalClass = signal.signal_type === 'BUY' ? 'signal-buy-row' : 'signal-sell-row';
        const signalBadge = signal.signal_type === 'BUY' 
            ? '<span class="badge badge-buy">买入</span>' 
            : '<span class="badge badge-sell">卖出</span>';
        const dateStr = signal.timestamp ? 
            new Date(signal.timestamp).toLocaleString('zh-CN', { 
                year: 'numeric',
                month: '2-digit', 
                day: '2-digit', 
                hour: '2-digit', 
                minute: '2-digit' 
            }) : '--';
        
        return `
            <tr class="${signalClass}" onclick="viewStockDetail('${signal.stock_code}')" style="cursor: pointer;">
                <td>${dateStr}</td>
                <td><strong>${signal.stock_code}</strong></td>
                <td>${signal.stock_name || '--'}</td>
                <td>${signalBadge}</td>
                <td>￥${signal.price ? signal.price.toFixed(2) : '--'}</td>
                <td class="reason-cell" title="${signal.reason || ''}">${signal.reason || '--'}</td>
            </tr>
        `;
    }).join('');
}

/**
 * 渲染历史列表（旧版兼容）
 */
function renderHistoryList() {
    renderSignalsContainer();
    
    const container = document.getElementById('history-list');
    if (!container) return;
    
    if (!AppState.signalHistory || AppState.signalHistory.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">📝</span>
                <p>暂无历史记录</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = AppState.signalHistory.map(signal => {
        const signalClass = signal.signal_type === 'BUY' ? 'signal-buy' : 'signal-sell';
        const signalText = signal.signal_type === 'BUY' ? '买入' : '卖出';
        const time = signal.timestamp ? 
            new Date(signal.timestamp).toLocaleString('zh-CN', { 
                month: '2-digit', 
                day: '2-digit', 
                hour: '2-digit', 
                minute: '2-digit' 
            }) : '--';
        
        return `
            <div class="signal-item ${signalClass}">
                <div class="signal-header">
                    <span class="stock-code">${signal.stock_code}</span>
                    <span class="stock-name">${signal.stock_name || ''}</span>
                    <span class="signal-badge ${signalClass}">${signalText}</span>
                </div>
                <div class="signal-detail">
                    <span class="signal-price">￥${signal.price ? signal.price.toFixed(2) : '--'}</span>
                    <span class="signal-time">${time}</span>
                </div>
                <div class="signal-reason">${signal.reason || ''}</div>
            </div>
        `;
    }).join('');
}

/**
 * 清空历史
 */
async function clearHistory() {
    if (!confirm('确定要清空所有信号历史吗？')) return;
    
    try {
        const response = await fetch('/api/strategy/signals', { method: 'DELETE' });
        const data = await response.json();
        
        if (data.success) {
            AppState.signalHistory = [];
            renderHistoryList();
            showToast('信号历史已清空', 'success');
        } else {
            showToast(data.message || '清空失败', 'error');
        }
    } catch (error) {
        console.error('清空历史失败:', error);
        showToast('清空失败', 'error');
    }
}

// ==================== 导出到全局 ====================
window.loadTodaySignals = loadTodaySignals;
window.loadHistorySignals = loadHistorySignals;
window.loadSignalHistory = loadSignalHistory;
window.handleSignals = handleSignals;
window.deduplicateSignals = deduplicateSignals;
window.updateRealtimeSignalCounts = updateRealtimeSignalCounts;
window.updateSignalCountsFromStocks = updateSignalCountsFromStocks;
window.renderSignalsContainer = renderSignalsContainer;
window.renderHistoryTable = renderHistoryTable;
window.renderHistoryList = renderHistoryList;
window.clearHistory = clearHistory;
