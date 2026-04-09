/**
 * 策略监控 - 监控控制模块（入口文件）
 * 功能：监控控制、事件监听、页面初始化
 * 
 * 依赖：
 * - monitor-socket.js (WebSocket 连接)
 * - strategy-panel.js (监控启动对话框)
 * - signal-display.js (信号展示)
 * - plate-overview.js (板块概览、股票池)
 */

// ==================== 全局状态 ====================
const AppState = {
    socket: null,
    isMonitoring: false,
    stocks: [],
    todaySignals: [],
    historySignals: [],
    plates: new Set()
};

// ==================== 页面初始化 ====================
document.addEventListener('DOMContentLoaded', function() {
    console.log('[初始化] 页面加载完成，开始初始化...');
    initSocket();
    initEventListeners();
    initVisibilityListener();
    loadPlateOverview();
    loadStockPool();
    loadTodaySignals();
    loadHistorySignals();
    checkMonitorStatus();
});

// ==================== 页面可见性监听 ====================
function initVisibilityListener() {
    document.addEventListener('visibilitychange', function() {
        if (!document.hidden) {
            console.log('[可见性] 页面变为可见，检查并刷新数据');
            refreshDataOnVisible();
        }
    });
    
    window.addEventListener('popstate', function() {
        console.log('[导航] 检测到导航变化，刷新数据');
        refreshDataOnVisible();
    });
}

async function refreshDataOnVisible() {
    try {
        await checkMonitorStatus();
        await loadStockPool();
        await loadSignalHistory();
        if (AppState.socket && AppState.socket.connected) {
            AppState.socket.emit('request_update');
        }
        console.log('[可见性] 数据刷新完成');
    } catch (error) {
        console.error('[可见性] 数据刷新失败:', error);
    }
}

// ==================== 事件监听 ====================
function initEventListeners() {
    const startBtn = document.getElementById('start-monitor-btn');
    const stopBtn = document.getElementById('stop-monitor-btn');
    if (startBtn) startBtn.addEventListener('click', startMonitor);
    if (stopBtn) stopBtn.addEventListener('click', stopMonitor);
    
    const stockSearch = document.getElementById('stock-search');
    const plateFilter = document.getElementById('plate-filter');
    const signalFilter = document.getElementById('signal-filter');
    if (stockSearch) stockSearch.addEventListener('input', filterStocks);
    if (plateFilter) plateFilter.addEventListener('change', filterStocks);
    if (signalFilter) signalFilter.addEventListener('change', filterStocks);
    
    const clearBtn = document.getElementById('clear-history-btn');
    if (clearBtn) clearBtn.addEventListener('click', clearHistory);
    
    const refreshHistoryBtn = document.getElementById('refresh-history-btn');
    if (refreshHistoryBtn) refreshHistoryBtn.addEventListener('click', loadHistorySignals);
    
    const historyDaysSelect = document.getElementById('history-days-select');
    if (historyDaysSelect) historyDaysSelect.addEventListener('change', loadHistorySignals);
    
    const updateHeatBtn = document.getElementById('update-heat-btn');
    if (updateHeatBtn) updateHeatBtn.addEventListener('click', updateHotStocks);
}

// ==================== 监控控制 ====================
async function checkMonitorStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        if (data.success) {
            AppState.isMonitoring = data.data.is_running;
            updateMonitorButtons();
            updateMonitorHint();
        }
    } catch (error) {
        console.error('检查监控状态失败:', error);
    }
}

function updateMonitorHint() {
    const hint = document.getElementById('monitor-hint');
    if (!hint) return;
    if (AppState.isMonitoring) {
        hint.textContent = '监控运行中，正在对所有已启用策略执行信号检测';
        hint.style.color = '#28a745';
    } else {
        hint.textContent = '监控开启后，所有已启用策略将执行信号检测';
        hint.style.color = '#6c757d';
    }
}

async function startMonitor() {
    const btn = document.getElementById('start-monitor-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">⏳</span><span>启动中...</span>';
    showMonitorStartDialog();
    
    try {
        const response = await fetch('/api/monitor/start', { method: 'POST' });
        const data = await response.json();
        if (data.success) {
            AppState.isMonitoring = true;
            updateMonitorStartStatus({ phase: 'completed' });
            setTimeout(() => {
                hideMonitorStartDialog();
                showToast('监控已启动', 'success');
                loadStockPool();
            }, 1000);
        } else {
            hideMonitorStartDialog();
            showToast(data.message || '启动失败', 'error');
        }
    } catch (error) {
        console.error('启动监控失败:', error);
        hideMonitorStartDialog();
        showToast('启动监控失败', 'error');
    } finally {
        updateMonitorButtons();
    }
}

async function stopMonitor() {
    const btn = document.getElementById('stop-monitor-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">⏳</span><span>停止中...</span>';
    
    try {
        const response = await fetch('/api/monitor/stop', { method: 'POST' });
        const data = await response.json();
        if (data.success) {
            AppState.isMonitoring = false;
            showToast('监控已停止', 'info');
        } else {
            showToast(data.message || '停止失败', 'error');
        }
    } catch (error) {
        console.error('停止监控失败:', error);
        showToast('停止监控失败', 'error');
    } finally {
        updateMonitorButtons();
    }
}

function updateMonitorButtons() {
    const startBtn = document.getElementById('start-monitor-btn');
    const stopBtn = document.getElementById('stop-monitor-btn');
    
    if (AppState.isMonitoring) {
        if (startBtn) { startBtn.disabled = true; startBtn.innerHTML = '<span class="btn-icon">✅</span><span>监控中</span>'; }
        if (stopBtn) { stopBtn.disabled = false; stopBtn.innerHTML = '<span class="btn-icon">⏹️</span><span>停止监控</span>'; }
    } else {
        if (startBtn) { startBtn.disabled = false; startBtn.innerHTML = '<span class="btn-icon">▶️</span><span>启动监控</span>'; }
        if (stopBtn) { stopBtn.disabled = true; stopBtn.innerHTML = '<span class="btn-icon">⏹️</span><span>停止监控</span>'; }
    }
    updateMonitorHint();
}

// ==================== 报价和条件更新 ====================
function updateStocksWithQuotes(quotes) {
    if (!quotes || quotes.length === 0) return;
    const quoteMap = new Map();
    quotes.forEach(q => quoteMap.set(q.stock_code, q));
    
    let updated = false;
    AppState.stocks.forEach(stock => {
        const quote = quoteMap.get(stock.stock_code);
        if (quote) {
            stock.cur_price = quote.cur_price ?? stock.cur_price;
            stock.change_pct = quote.change_pct ?? stock.change_pct;
            stock.volume = quote.volume ?? stock.volume;
            stock.turnover = quote.turnover ?? stock.turnover;
            updated = true;
        }
    });
    if (updated) renderStocksTable(getFilteredStocks());
}

function updateStocksWithConditions(conditions) {
    if (!conditions || conditions.length === 0) return;
    const conditionMap = new Map();
    conditions.forEach(c => conditionMap.set(c.stock_code, c));
    
    let updated = false;
    AppState.stocks.forEach(stock => {
        const condition = conditionMap.get(stock.stock_code);
        if (condition) {
            stock.trading_conditions = { ...stock.trading_conditions, ...condition };
            updated = true;
        }
    });
    if (updated) {
        renderStocksTable(getFilteredStocks());
        updateSignalCountsFromStocks(AppState.stocks);
    }
}

// ==================== 工具函数 ====================
function viewStockDetail(stockCode) { window.open(`/kline?stock=${encodeURIComponent(stockCode)}`, '_blank'); }
function openKlinePage(stockCode) { window.open(`/kline?stock=${encodeURIComponent(stockCode)}`, '_blank'); }
function goToTrading(stockCode) { window.open(`/trading?code=${encodeURIComponent(stockCode)}`, '_blank'); }
function playSignalSound() { return; }

// ==================== 导出全局函数 ====================
window.AppState = AppState;
window.viewStockDetail = viewStockDetail;
window.openKlinePage = openKlinePage;
window.goToTrading = goToTrading;
window.updateStocksWithQuotes = updateStocksWithQuotes;
window.updateStocksWithConditions = updateStocksWithConditions;
