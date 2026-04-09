/**
 * 策略监控首页 JavaScript
 * 功能：监控控制（总开关）、信号展示、股票列表管理
 * 
 * 重构说明：
 * 1. 监控总开关与策略控制分离
 * 2. 启动监控仅控制行情监听的开启/关闭
 * 3. 策略的启用/禁用由策略面板（strategy_panel.js）独立控制
 */

// ==================== 全局状态 ====================
const AppState = {
    socket: null,
    isMonitoring: false,
    // 股票相关
    stocks: [],
    todaySignals: [],        // 今日实时信号
    historySignals: [],      // 历史信号（今日以前）
    plates: new Set()
};

// ==================== 初始化 ====================
document.addEventListener('DOMContentLoaded', function() {
    console.log('[初始化] 页面加载完成，开始初始化...');
    initSocket();
    initEventListeners();
    initVisibilityListener();  // 页面可见性监听
    loadPlateOverview();
    loadStockPool();
    loadTodaySignals();      // 加载今日实时信号
    loadHistorySignals();    // 加载历史信号（今日以前）
    checkMonitorStatus();
});

// ==================== 页面可见性监听 ====================
function initVisibilityListener() {
    document.addEventListener('visibilitychange', function() {
        if (!document.hidden) {
            console.log('[可见性] 页面变为可见，检查并刷新数据');
            // 页面变为可见时刷新数据
            refreshDataOnVisible();
        }
    });
    
    // 监听 popstate 事件（浏览器前进后退）
    window.addEventListener('popstate', function() {
        console.log('[导航] 检测到导航变化，刷新数据');
        refreshDataOnVisible();
    });
}

/**
 * 页面变为可见时刷新数据
 */
async function refreshDataOnVisible() {
    try {
        // 检查监控状态
        await checkMonitorStatus();
        
        // 刷新股票池数据
        await loadStockPool();
        
        // 刷新信号历史
        await loadSignalHistory();
        
        // 如果 WebSocket 已连接，请求最新更新
        if (AppState.socket && AppState.socket.connected) {
            AppState.socket.emit('request_update');
        }
        
        console.log('[可见性] 数据刷新完成');
    } catch (error) {
        console.error('[可见性] 数据刷新失败:', error);
    }
}

// ==================== WebSocket ====================
function initSocket() {
    // 检查 Socket.IO 是否已加载
    if (typeof io === 'undefined') {
        console.error('[WebSocket] Socket.IO 库未加载，无法建立连接');
        updateConnectionStatus(false, 'Socket.IO未加载');
        setTimeout(initSocket, 3000);
        return;
    }
    
    console.log('[WebSocket] 正在初始化 Socket.IO 连接...');
    
    AppState.socket = io({
        reconnection: true,
        reconnectionAttempts: 10,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000,
        transports: ['websocket', 'polling']
    });
    
    // 连接成功
    AppState.socket.on('connect', function() {
        updateConnectionStatus(true);
        console.log('[WebSocket] 连接成功，ID:', AppState.socket.id);
        
        // 【修复】连接成功后主动请求数据刷新
        setTimeout(() => {
            console.log('[WebSocket] 请求最新数据更新');
            AppState.socket.emit('request_update');
            loadStockPool();
            loadSignalHistory();
        }, 500);
    });
    
    // 连接断开
    AppState.socket.on('disconnect', function(reason) {
        updateConnectionStatus(false);
        console.log('[WebSocket] 连接断开，原因:', reason);
        
        if (reason === 'io server disconnect') {
            console.log('[WebSocket] 服务器断开连接，尝试重连...');
            AppState.socket.connect();
        }
    });
    
    // 连接错误
    AppState.socket.on('connect_error', function(error) {
        console.error('[WebSocket] 连接错误:', error.message);
        updateConnectionStatus(false, '连接错误');
    });
    
    // 重连尝试
    AppState.socket.on('reconnect_attempt', function(attemptNumber) {
        console.log('[WebSocket] 第', attemptNumber, '次重连尝试...');
        updateConnectionStatus(false, '重连中(' + attemptNumber + ')');
    });
    
    // 重连成功
    AppState.socket.on('reconnect', function(attemptNumber) {
        console.log('[WebSocket] 重连成功，共尝试', attemptNumber, '次');
        updateConnectionStatus(true);
        
        // 【修复】重连成功后刷新数据
        setTimeout(() => {
            console.log('[WebSocket] 重连后刷新数据');
            AppState.socket.emit('request_update');
            loadStockPool();
            loadSignalHistory();
        }, 500);
    });
    
    // 重连失败
    AppState.socket.on('reconnect_failed', function() {
        console.error('[WebSocket] 重连失败，已达最大重试次数');
        updateConnectionStatus(false, '重连失败');
    });
    
    // 接收策略信号更新
    AppState.socket.on('strategy_signals', function(data) {
        console.log('[WebSocket] 收到策略信号:', data);
        handleSignals(data.signals || []);
    });
    
    // 接收报价更新
    AppState.socket.on('quotes_update', function(data) {
        console.log('[WebSocket] 收到报价更新:', (data.quotes || []).length, '条');
        updateStocksWithQuotes(data.quotes || []);
        
        // 如果有交易信号，也处理它们
        if (data.trade_actions && data.trade_actions.length > 0) {
            console.log('[WebSocket] 从 quotes_update 中提取交易信号:', data.trade_actions.length, '个');
            const signals = data.trade_actions.map(action => ({
                stock_code: action.stock_code,
                stock_name: action.stock_name,
                signal_type: action.signal_type,
                price: action.price,
                reason: action.reason || action.message,
                timestamp: action.timestamp,
                strategy_name: '低吸高抛策略'
            }));
            handleSignals(signals);
        }

        // 多策略分组信号 → 更新策略面板和信号 Tab
        if (data.signals_by_strategy) {
            if (window.StrategyPanel) window.StrategyPanel.updateSignalCounts(data.signals_by_strategy);
            if (window.SignalTabs) window.SignalTabs.updateSignals(data.signals_by_strategy);
        }
    });
    
    // 接收交易条件更新
    AppState.socket.on('conditions_update', function(data) {
        console.log('[WebSocket] 收到交易条件更新:', (data.conditions || []).length, '条');
        updateStocksWithConditions(data.conditions || []);
    });
    
    // 接收状态更新
    AppState.socket.on('status', function(data) {
        console.log('[WebSocket] 收到状态更新:', data);
    });
}

function updateConnectionStatus(connected, customText = null) {
    const statusEl = document.getElementById('connection-status');
    if (statusEl) {
        let statusClass = 'status-indicator ';
        if (connected) {
            statusClass += 'connected';
        } else if (customText) {
            statusClass += 'error';
        } else {
            statusClass += 'disconnected';
        }
        statusEl.className = statusClass;
        
        const textEl = statusEl.querySelector('.status-text');
        if (textEl) {
            if (customText) {
                textEl.textContent = customText;
            } else {
                textEl.textContent = connected ? '已连接' : '未连接';
            }
        }
    }
    
    const systemStatusEl = document.getElementById('system-status');
    if (systemStatusEl) {
        if (connected) {
            systemStatusEl.textContent = 'WebSocket已连接';
            systemStatusEl.style.color = '#28a745';
        } else if (customText) {
            systemStatusEl.textContent = customText;
            systemStatusEl.style.color = '#dc3545';
        } else {
            systemStatusEl.textContent = 'WebSocket未连接';
            systemStatusEl.style.color = '#6c757d';
        }
    }
}

// ==================== 事件监听 ====================
function initEventListeners() {
    // 监控总开关：仅控制行情监听的开启/关闭
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
    
    // 历史信号相关事件监听
    const refreshHistoryBtn = document.getElementById('refresh-history-btn');
    if (refreshHistoryBtn) refreshHistoryBtn.addEventListener('click', loadHistorySignals);
    
    const historyDaysSelect = document.getElementById('history-days-select');
    if (historyDaysSelect) historyDaysSelect.addEventListener('change', loadHistorySignals);
    
    // 更新热门股按钮
    const updateHeatBtn = document.getElementById('update-heat-btn');
    if (updateHeatBtn) updateHeatBtn.addEventListener('click', updateHotStocks);
}

// ==================== 监控控制（总开关） ====================

// ==================== 监控控制（总开关） ====================

let monitorStartState = {
    isStarting: false,
    phase: 'init',
    batchNum: 0,
    totalBatches: 0,
    activeCount: 0,
    waitingSeconds: 0,
    waitIntervalId: null,
    progressIntervalId: null
};

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

/** 更新监控提示文字 */
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
        // 启动监控：仅开启行情监听，策略配置由策略面板独立管理
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

function showMonitorStartDialog() {
    let dialog = document.getElementById('monitor-start-dialog');
    if (!dialog) {
        dialog = document.createElement('div');
        dialog.id = 'monitor-start-dialog';
        dialog.className = 'loading-dialog';
        dialog.innerHTML = `
            <div class="loading-content">
                <div class="loading-spinner"></div>
                <div class="loading-title" id="monitor-start-title">正在启动监控</div>
                <div class="loading-phase">
                    <span class="phase-badge" id="monitor-start-phase">初始化</span>
                </div>
                <div class="loading-detail" id="monitor-start-detail">
                    <div class="detail-row">
                        <span class="detail-label">当前批次:</span>
                        <span id="monitor-batch-num">--</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">活跃股票:</span>
                        <span id="monitor-active-count">--</span>
                    </div>
                </div>
                <div class="loading-wait" id="monitor-wait" style="display:none;">
                    <div class="wait-progress">
                        <div class="wait-bar" id="monitor-wait-bar"></div>
                    </div>
                    <div class="wait-text" id="monitor-wait-text">等待中...</div>
                </div>
                <div class="loading-tip" id="monitor-start-tip">
                    正在订阅股票行情，请稍候...
                </div>
                <div class="loading-notice">
                    <small>⚠️ 首次启动可能需要几分钟（每批90秒等待限制）</small>
                </div>
            </div>
        `;
        document.body.appendChild(dialog);
        addMonitorStartDialogStyles();
    }
    
    dialog.style.display = 'flex';
    
    monitorStartState = {
        isStarting: true,
        phase: 'init',
        batchNum: 0,
        totalBatches: 0,
        activeCount: 0,
        waitingSeconds: 0,
        waitIntervalId: null,
        progressIntervalId: null
    };
    
    startMonitorProgressSimulation();
}

function addMonitorStartDialogStyles() {
    const styleId = 'monitor-start-dialog-styles';
    if (document.getElementById(styleId)) return;
    
    const style = document.createElement('style');
    style.id = styleId;
    style.textContent = `
        .loading-dialog {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 9999;
        }
        .loading-content {
            background: #1e1e1e;
            border-radius: 12px;
            padding: 30px 40px;
            text-align: center;
            min-width: 320px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
        }
        .loading-spinner {
            width: 50px;
            height: 50px;
            border: 4px solid #333;
            border-top: 4px solid #4CAF50;
            border-radius: 50%;
            margin: 0 auto 20px;
            animation: spin 1s linear infinite;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .loading-title {
            font-size: 18px;
            font-weight: 600;
            color: #fff;
            margin-bottom: 10px;
        }
        .loading-phase { margin: 15px 0; }
        .phase-badge {
            display: inline-block;
            padding: 6px 16px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 500;
            background: #e3f2fd;
            color: #1976d2;
            transition: all 0.3s ease;
        }
        .phase-badge.subscribing { background: #fff3e0; color: #f57c00; }
        .phase-badge.filtering { background: #e8f5e9; color: #388e3c; }
        .phase-badge.waiting { background: #fce4ec; color: #c2185b; }
        .phase-badge.completed { background: #e8f5e9; color: #2e7d32; }
        .loading-detail {
            margin: 15px 0;
            padding: 12px;
            background: rgba(255,255,255,0.05);
            border-radius: 8px;
        }
        .detail-row {
            display: flex;
            justify-content: space-between;
            margin: 6px 0;
            font-size: 14px;
            color: #ccc;
        }
        .detail-label { color: #888; }
        .loading-wait {
            margin: 15px 0;
            padding: 12px;
            background: rgba(255,193,7,0.1);
            border-radius: 8px;
            border: 1px solid rgba(255,193,7,0.3);
        }
        .wait-progress {
            height: 8px;
            background: rgba(255,255,255,0.1);
            border-radius: 4px;
            overflow: hidden;
            margin-bottom: 10px;
        }
        .wait-bar {
            height: 100%;
            background: linear-gradient(90deg, #ffc107, #ff9800);
            border-radius: 4px;
            width: 0%;
            transition: width 1s linear;
        }
        .wait-text { font-size: 13px; color: #ffc107; text-align: center; }
        .loading-tip { font-size: 13px; color: #888; margin-top: 15px; }
        .loading-notice {
            margin-top: 15px;
            padding: 10px;
            background: rgba(255,152,0,0.1);
            border-radius: 6px;
            border: 1px dashed rgba(255,152,0,0.3);
        }
        .loading-notice small { color: #ff9800; font-size: 12px; }
    `;
    document.head.appendChild(style);
}

function startMonitorProgressSimulation() {
    let elapsed = 0;
    const phaseSequence = [
        { phase: 'subscribing', time: 0, tip: '正在订阅股票行情...' },
        { phase: 'filtering', time: 5, tip: '正在获取报价数据...' },
        { phase: 'waiting', time: 10, tip: '等待API限制解除中...' }
    ];
    
    let currentPhaseIndex = 0;
    let waitCountdownStarted = false;
    
    const progressInterval = setInterval(() => {
        elapsed++;
        
        if (currentPhaseIndex < phaseSequence.length - 1) {
            const nextPhase = phaseSequence[currentPhaseIndex + 1];
            if (elapsed >= nextPhase.time) {
                currentPhaseIndex++;
                updateMonitorStartStatus({ phase: nextPhase.phase, tip: nextPhase.tip });
                
                if (nextPhase.phase === 'waiting' && !waitCountdownStarted) {
                    waitCountdownStarted = true;
                    startWaitCountdown(90);
                }
            }
        }
        
        if (elapsed % 5 === 0 && monitorStartState.phase === 'filtering') {
            const batchNum = Math.min(Math.ceil(elapsed / 30), 3);
            const activeCount = Math.min(elapsed * 5, 150);
            updateMonitorStartStatus({ batchNum, totalBatches: 3, activeCount });
        }
        
        if (!monitorStartState.isStarting || monitorStartState.phase === 'completed') {
            clearInterval(progressInterval);
        }
        
        if (elapsed > 300) {
            clearInterval(progressInterval);
        }
    }, 1000);
    
    monitorStartState.progressIntervalId = progressInterval;
}

function startWaitCountdown(totalSeconds) {
    const waitEl = document.getElementById('monitor-wait');
    const waitText = document.getElementById('monitor-wait-text');
    const waitBar = document.getElementById('monitor-wait-bar');
    
    if (!waitEl) return;
    
    waitEl.style.display = 'block';
    monitorStartState.waitingSeconds = totalSeconds;
    
    if (monitorStartState.waitIntervalId) {
        clearInterval(monitorStartState.waitIntervalId);
    }
    
    const updateWait = () => {
        const remaining = monitorStartState.waitingSeconds;
        const progress = ((totalSeconds - remaining) / totalSeconds) * 100;
        
        if (waitText) waitText.textContent = `等待反订阅限制解除 (${remaining}秒)`;
        if (waitBar) waitBar.style.width = `${progress}%`;
        
        monitorStartState.waitingSeconds--;
        
        if (remaining <= 0) {
            clearInterval(monitorStartState.waitIntervalId);
            monitorStartState.waitIntervalId = null;
            waitEl.style.display = 'none';
            updateMonitorStartStatus({ phase: 'filtering', tip: '继续处理下一批...' });
        }
    };
    
    updateWait();
    monitorStartState.waitIntervalId = setInterval(updateWait, 1000);
}

function updateMonitorStartStatus(info) {
    if (!info) return;
    
    const titleEl = document.getElementById('monitor-start-title');
    const phaseEl = document.getElementById('monitor-start-phase');
    const tipEl = document.getElementById('monitor-start-tip');
    const batchNumEl = document.getElementById('monitor-batch-num');
    const activeCountEl = document.getElementById('monitor-active-count');
    
    if (info.phase) {
        monitorStartState.phase = info.phase;
        
        if (phaseEl) {
            phaseEl.classList.remove('subscribing', 'filtering', 'waiting', 'completed');
            
            switch (info.phase) {
                case 'subscribing':
                    phaseEl.textContent = '订阅中';
                    phaseEl.classList.add('subscribing');
                    if (titleEl) titleEl.textContent = '正在订阅股票';
                    break;
                case 'filtering':
                    phaseEl.textContent = '筛选中';
                    phaseEl.classList.add('filtering');
                    if (titleEl) titleEl.textContent = '正在筛选活跃股票';
                    break;
                case 'waiting':
                    phaseEl.textContent = '等待中';
                    phaseEl.classList.add('waiting');
                    if (titleEl) titleEl.textContent = '等待API限制';
                    break;
                case 'completed':
                    phaseEl.textContent = '完成';
                    phaseEl.classList.add('completed');
                    if (titleEl) titleEl.textContent = '监控启动完成';
                    if (tipEl) tipEl.textContent = '即将跳转...';
                    break;
                default:
                    phaseEl.textContent = '初始化';
                    if (titleEl) titleEl.textContent = '正在启动监控';
            }
        }
    }
    
    if (info.tip && tipEl) tipEl.textContent = info.tip;
    
    if (info.batchNum !== undefined) {
        monitorStartState.batchNum = info.batchNum;
        if (batchNumEl) batchNumEl.textContent = `${info.batchNum}/${info.totalBatches || '?'}`;
    }
    
    if (info.activeCount !== undefined) {
        monitorStartState.activeCount = info.activeCount;
        if (activeCountEl) activeCountEl.textContent = info.activeCount;
    }
}

function hideMonitorStartDialog() {
    const dialog = document.getElementById('monitor-start-dialog');
    if (dialog) {
        dialog.style.display = 'none';
    }
    
    monitorStartState.isStarting = false;
    
    if (monitorStartState.waitIntervalId) {
        clearInterval(monitorStartState.waitIntervalId);
        monitorStartState.waitIntervalId = null;
    }
    if (monitorStartState.progressIntervalId) {
        clearInterval(monitorStartState.progressIntervalId);
        monitorStartState.progressIntervalId = null;
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
        if (startBtn) {
            startBtn.disabled = true;
            startBtn.innerHTML = '<span class="btn-icon">✅</span><span>监控中</span>';
        }
        if (stopBtn) {
            stopBtn.disabled = false;
            stopBtn.innerHTML = '<span class="btn-icon">⏹️</span><span>停止监控</span>';
        }
    } else {
        if (startBtn) {
            startBtn.disabled = false;
            startBtn.innerHTML = '<span class="btn-icon">▶️</span><span>启动监控</span>';
        }
        if (stopBtn) {
            stopBtn.disabled = true;
            stopBtn.innerHTML = '<span class="btn-icon">⏹️</span><span>停止监控</span>';
        }
    }
    
    // 更新监控提示
    updateMonitorHint();
}

// ==================== 股票池管理 ====================

async function loadStockPool() {
    try {
        const response = await fetch('/api/stocks/pool');
        const data = await response.json();
        
        if (data.success) {
            AppState.stocks = data.data.stocks || [];
            
            // 更新板块过滤器
            updatePlateFilter(AppState.stocks);
            
            // 渲染股票表格
            renderStocksTable(AppState.stocks);
            
            // 【修复】从当前股票列表统计信号数量
            updateSignalCountsFromStocks(AppState.stocks);
            
            // 更新市场状态
            updateMarketStatus(data.data);
            
            console.log('[股票池] 加载完成，共', AppState.stocks.length, '只股票');
        }
    } catch (error) {
        console.error('加载股票池失败:', error);
        showToast('加载股票池失败', 'error');
    }
}

/**
 * 【新增】从股票列表统计信号数量
 * 根据 trading_conditions 中的信号状态统计
 */
function updateSignalCountsFromStocks(stocks) {
    let buyCount = 0;
    let sellCount = 0;
    
    stocks.forEach(stock => {
        const conditions = stock.trading_conditions;
        if (conditions) {
            // 检查买入信号
            if (conditions.buy_signal || conditions.is_buy_point) {
                buyCount++;
            }
            // 检查卖出信号
            if (conditions.sell_signal || conditions.is_sell_point) {
                sellCount++;
            }
        }
    });
    
    // 更新UI显示
    const buyCountEl = document.getElementById('buy-signal-count');
    const sellCountEl = document.getElementById('sell-signal-count');
    
    if (buyCountEl) buyCountEl.textContent = buyCount;
    if (sellCountEl) sellCountEl.textContent = sellCount;
    
    console.log('[信号统计] 买入信号:', buyCount, '卖出信号:', sellCount);
}

function updateMarketStatus(data) {
    // 注：market-status 和 stock-count 元素已从 index.html 中移除
    // 此函数保留以防后续需要
}

function updatePlateFilter(stocks) {
    const plateFilter = document.getElementById('plate-filter');
    if (!plateFilter) return;
    
    // 收集所有板块
    AppState.plates.clear();
    stocks.forEach(stock => {
        if (stock.plate) {
            AppState.plates.add(stock.plate);
        }
    });
    
    // 保存当前选中值
    const currentValue = plateFilter.value;
    
    // 更新选项
    plateFilter.innerHTML = '<option value="">全部板块</option>';
    Array.from(AppState.plates).sort().forEach(plate => {
        const option = document.createElement('option');
        option.value = plate;
        option.textContent = plate;
        plateFilter.appendChild(option);
    });
    
    // 恢复选中值
    if (currentValue && AppState.plates.has(currentValue)) {
        plateFilter.value = currentValue;
    }
}

function renderStocksTable(stocks) {
    const tbody = document.getElementById('stocks-table-body');
    if (!tbody) return;
    
    if (!stocks || stocks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10" class="text-center text-muted">暂无股票数据</td></tr>';
        return;
    }
    
    tbody.innerHTML = stocks.map(stock => {
        const conditions = stock.trading_conditions || {};
        const changeClass = (stock.change_pct || 0) >= 0 ? 'text-up' : 'text-down';
        const signalClass = getSignalClass(conditions);
        const signalText = getSignalText(conditions);
        
        return `
            <tr class="${signalClass}" data-code="${stock.stock_code}">
                <td>${stock.stock_code}</td>
                <td>${stock.stock_name || '--'}</td>
                <td>${stock.plate || '--'}</td>
                <td>${stock.cur_price ? stock.cur_price.toFixed(2) : '--'}</td>
                <td class="${changeClass}">${stock.change_pct ? stock.change_pct.toFixed(2) + '%' : '--'}</td>
                <td>${conditions.drop_pct ? conditions.drop_pct.toFixed(2) + '%' : '--'}</td>
                <td>${conditions.rise_pct ? conditions.rise_pct.toFixed(2) + '%' : '--'}</td>
                <td>${conditions.reversal_pct ? conditions.reversal_pct.toFixed(2) + '%' : '--'}</td>
                <td class="signal-cell">${signalText}</td>
                <td>
                    <button class="btn btn-sm btn-outline-primary" onclick="viewStockDetail('${stock.stock_code}')">详情</button>
                </td>
            </tr>
        `;
    }).join('');
}

function getSignalClass(conditions) {
    if (conditions.buy_signal || conditions.is_buy_point) {
        return 'signal-buy';
    }
    if (conditions.sell_signal || conditions.is_sell_point) {
        return 'signal-sell';
    }
    return '';
}

function getSignalText(conditions) {
    const signals = [];
    if (conditions.buy_signal || conditions.is_buy_point) {
        signals.push('<span class="badge badge-success">买入</span>');
    }
    if (conditions.sell_signal || conditions.is_sell_point) {
        signals.push('<span class="badge badge-danger">卖出</span>');
    }
    return signals.length > 0 ? signals.join(' ') : '-';
}

function filterStocks() {
    const searchTerm = (document.getElementById('stock-search')?.value || '').toLowerCase();
    const plateFilter = document.getElementById('plate-filter')?.value || '';
    const signalFilter = document.getElementById('signal-filter')?.value || '';
    
    const filtered = AppState.stocks.filter(stock => {
        // 搜索过滤
        const matchSearch = !searchTerm || 
            stock.stock_code.toLowerCase().includes(searchTerm) ||
            (stock.stock_name || '').toLowerCase().includes(searchTerm);
        
        // 板块过滤
        const matchPlate = !plateFilter || stock.plate === plateFilter;
        
        // 信号过滤
        let matchSignal = true;
        if (signalFilter) {
            const conditions = stock.trading_conditions || {};
            if (signalFilter === 'buy') {
                matchSignal = conditions.buy_signal || conditions.is_buy_point;
            } else if (signalFilter === 'sell') {
                matchSignal = conditions.sell_signal || conditions.is_sell_point;
            }
        }
        
        return matchSearch && matchPlate && matchSignal;
    });
    
    renderStocksTable(filtered);
}

function viewStockDetail(stockCode) {
    // 跳转到 K 线图页面
    window.open(`/kline?stock=${encodeURIComponent(stockCode)}`, '_blank');
}

/**
 * 打开 K 线图页面
 */
function openKlinePage(stockCode) {
    window.open(`/kline?stock=${encodeURIComponent(stockCode)}`, '_blank');
}

/**
 * 跳转到交易页面
 */
function goToTrading(stockCode) {
    window.open(`/trading?code=${encodeURIComponent(stockCode)}`, '_blank');
}

// ==================== 信号处理（统一入口） ====================

/**
 * 【重构】统一的信号处理函数
 * 处理来自 strategy_signals 和 quotes_update 的信号
 * 
 * 简化后逻辑：
 * - 收到新信号后，从数据库重新加载今日信号
 * - 这样可以确保数据一致性（后端已经存入数据库并去重）
 */
function handleSignals(signals) {
    if (!signals || signals.length === 0) return;
    
    console.log('[信号处理] 收到新信号:', signals.length, '个，从数据库刷新今日信号');
    
    // 播放提示音
    playSignalSound();
    
    // 从数据库重新加载今日信号（后端已经存入数据库并去重）
    loadSignalHistory('today');
    
    // 刷新股票池
    loadStockPool();
}

/**
 * 信号去重（同一批次内去重）
 * 按 stock_code + signal_type 去重，保留最新的
 */
function deduplicateSignals(signals) {
    const signalMap = new Map();
    
    signals.forEach(signal => {
        const key = `${signal.stock_code}_${signal.signal_type}`;
        const existing = signalMap.get(key);
        
        if (!existing) {
            signalMap.set(key, signal);
        } else {
            // 保留时间戳更新的
            const existingTime = new Date(existing.timestamp || 0).getTime();
            const newTime = new Date(signal.timestamp || 0).getTime();
            if (newTime > existingTime) {
                signalMap.set(key, signal);
            }
        }
    });
    
    return Array.from(signalMap.values());
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
    
    if (updated) {
        renderStocksTable(getFilteredStocks());
    }
}

function updateStocksWithConditions(conditions) {
    if (!conditions || conditions.length === 0) return;
    
    const conditionMap = new Map();
    conditions.forEach(c => conditionMap.set(c.stock_code, c));
    
    let updated = false;
    AppState.stocks.forEach(stock => {
        const condition = conditionMap.get(stock.stock_code);
        if (condition) {
            stock.trading_conditions = {
                ...stock.trading_conditions,
                ...condition
            };
            updated = true;
        }
    });
    
    if (updated) {
        renderStocksTable(getFilteredStocks());
        // 更新信号计数
        updateSignalCountsFromStocks(AppState.stocks);
    }
}

function getFilteredStocks() {
    const searchTerm = (document.getElementById('stock-search')?.value || '').toLowerCase();
    const plateFilter = document.getElementById('plate-filter')?.value || '';
    const signalFilter = document.getElementById('signal-filter')?.value || '';
    
    if (!searchTerm && !plateFilter && !signalFilter) {
        return AppState.stocks;
    }
    
    return AppState.stocks.filter(stock => {
        const matchSearch = !searchTerm || 
            stock.stock_code.toLowerCase().includes(searchTerm) ||
            (stock.stock_name || '').toLowerCase().includes(searchTerm);
        const matchPlate = !plateFilter || stock.plate === plateFilter;
        
        let matchSignal = true;
        if (signalFilter) {
            const conditions = stock.trading_conditions || {};
            if (signalFilter === 'buy') {
                matchSignal = conditions.buy_signal || conditions.is_buy_point;
            } else if (signalFilter === 'sell') {
                matchSignal = conditions.sell_signal || conditions.is_sell_point;
            }
        }
        
        return matchSearch && matchPlate && matchSignal;
    });
}

// ==================== 信号历史管理 ====================

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
            
            // 更新实时信号计数
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
        // 获取选中的天数
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

// 兼容旧函数
async function loadSignalHistory(type = 'today') {
    if (type === 'today') {
        await loadTodaySignals();
    } else {
        await loadHistorySignals();
    }
}

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
    
    // 更新UI显示
    const buyCountEl = document.getElementById('buy-signal-count');
    const sellCountEl = document.getElementById('sell-signal-count');
    
    if (buyCountEl) buyCountEl.textContent = buyCount;
    if (sellCountEl) sellCountEl.textContent = sellCount;
    
    console.log('[信号统计] 买入信号:', buyCount, '卖出信号:', sellCount);
}

/**
 * 【修复】添加信号到历史（带去重）
 * 同一股票同一天同一类型信号只保留最新
 */
function addToHistory(signal) {
    if (!signal || !signal.stock_code) return;
    
    // 获取信号日期
    const signalDate = signal.timestamp ? 
        new Date(signal.timestamp).toDateString() : 
        new Date().toDateString();
    
    // 检查是否已存在相同信号（同股票、同天、同类型）
    const existingIndex = AppState.signalHistory.findIndex(h => {
        const hDate = h.timestamp ? 
            new Date(h.timestamp).toDateString() : 
            new Date().toDateString();
        return h.stock_code === signal.stock_code && 
               h.signal_type === signal.signal_type &&
               hDate === signalDate;
    });
    
    if (existingIndex !== -1) {
        // 更新已存在的信号
        AppState.signalHistory[existingIndex] = signal;
        console.log('[信号历史] 更新已存在信号:', signal.stock_code, signal.signal_type);
    } else {
        // 添加新信号到头部
        AppState.signalHistory.unshift(signal);
        console.log('[信号历史] 添加新信号:', signal.stock_code, signal.signal_type);
    }
    
    // 限制历史记录数量
    if (AppState.signalHistory.length > 100) {
        AppState.signalHistory = AppState.signalHistory.slice(0, 100);
    }
    
    renderHistoryList();
}

function renderHistoryList() {
    // 渲染实时信号卡片（signals-container）
    renderSignalsContainer();
    
    // 渲染信号历史列表（history-list）
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
 * 【新增】渲染实时信号卡片到 signals-container（使用今日信号数据）
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
    
    // 渲染信号卡片（显示最近的信号）
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
 * 【新增】渲染历史信号表格
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

// ==================== 板块概览 ====================

async function loadPlateOverview() {
    try {
        const response = await fetch('/api/plates/overview');
        const data = await response.json();
        
        if (data.success) {
            renderPlateOverview(data.data.plates || []);
        }
    } catch (error) {
        console.error('加载板块概览失败:', error);
    }
}

function renderPlateOverview(plates) {
    const container = document.getElementById('plates-container');
    if (!container) return;

    if (!plates || plates.length === 0) {
        container.innerHTML = '<div class="empty-state">暂无板块数据</div>';
        // 更新板块摘要
        const summaryEl = document.getElementById('plate-summary');
        if (summaryEl) summaryEl.textContent = '暂无目标板块';
        return;
    }

    // 更新板块摘要
    const summaryEl = document.getElementById('plate-summary');
    if (summaryEl) {
        const totalStocks = plates.reduce((sum, p) => sum + (p.total_stocks || 0), 0);
        const hotStocks = plates.reduce((sum, p) => sum + (p.hot_stocks || 0), 0);
        summaryEl.textContent = `共 ${plates.length} 个板块，${totalStocks} 只股票，${hotStocks} 只热门股`;
    }

    // 渲染板块卡片
    container.innerHTML = plates.map(plate => {
        const plateName = plate.plate_name || plate.name || '--';
        const plateCode = plate.plate_code || plate.code || '';
        const stockCount = plate.total_stocks || plate.stock_count || 0;
        const hotCount = plate.hot_stocks || 0;
        const market = plate.market || '';
        const marketBadge = market ? `<span class="market-badge market-${market.toLowerCase()}">${market}</span>` : '';

        // 市场热度值
        const heatValue = plate.heat_value || 0;
        const avgChange = plate.avg_change || 0;
        const heatClass = heatValue >= 50 ? 'heat-high' : 'heat-low';
        const changeClass = avgChange >= 0 ? 'price-up' : 'price-down';
        const changeSign = avgChange >= 0 ? '+' : '';

        // 热度显示：始终显示热度百分比 + 平均涨跌幅
        const heatDisplay = `<span class="plate-heat ${heatClass}" title="上涨股票占比">热度 ${heatValue}%</span>
               <span class="plate-avg-change ${changeClass}" title="平均涨跌幅">${changeSign}${avgChange.toFixed(2)}%</span>`;

        return `
            <div class="plate-card" onclick="goToPlateStocks('${plateCode}')">
                <div class="plate-header">
                    <span class="plate-name">${plateName}</span>
                    ${marketBadge}
                </div>
                <div class="plate-stats">
                    <span class="plate-count">${stockCount} 只股票</span>
                    <span class="plate-hot">${hotCount} 只热门</span>
                    ${heatDisplay}
                </div>
            </div>
        `;
    }).join('');
}

function goToPlateStocks(plateCode) {
    if (!plateCode) {
        console.error('板块代码为空');
        return;
    }
    window.location.href = `/plate/${encodeURIComponent(plateCode)}`;
}

function filterByPlate(plateName) {
    const plateFilter = document.getElementById('plate-filter');
    if (plateFilter) {
        plateFilter.value = plateName;
        filterStocks();
    }
}

// ==================== 工具函数 ====================

function playSignalSound() {
    // 提示音功能已禁用（音频文件不存在）
    return;
}

function showToast(message, type = 'info') {
    // 移除已存在的toast
    const existing = document.querySelector('.toast-notification');
    if (existing) existing.remove();
    
    const toast = document.createElement('div');
    toast.className = `toast-notification toast-${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${getToastIcon(type)}</span>
        <span class="toast-message">${message}</span>
    `;
    
    document.body.appendChild(toast);
    
    // 添加样式
    addToastStyles();
    
    // 显示动画
    setTimeout(() => toast.classList.add('show'), 10);
    
    // 自动消失
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

function getToastIcon(type) {
    switch (type) {
        case 'success': return '✅';
        case 'error': return '❌';
        case 'warning': return '⚠️';
        default: return 'ℹ️';
    }
}

function addToastStyles() {
    if (document.getElementById('toast-styles')) return;
    
    const style = document.createElement('style');
    style.id = 'toast-styles';
    style.textContent = `
        .toast-notification {
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 20px;
            border-radius: 8px;
            background: #333;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 10px;
            z-index: 10000;
            transform: translateX(120%);
            transition: transform 0.3s ease;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }
        .toast-notification.show {
            transform: translateX(0);
        }
        .toast-success { background: #28a745; }
        .toast-error { background: #dc3545; }
        .toast-warning { background: #ffc107; color: #333; }
        .toast-info { background: #17a2b8; }
        .toast-icon { font-size: 16px; }
        .toast-message { font-size: 14px; }
    `;
    document.head.appendChild(style);
}

// ==================== 热门股更新 ====================

/**
 * 更新热门股数据
 * 调用后端 API 分析并标记热门股票
 */
async function updateHotStocks() {
    const btn = document.getElementById('update-heat-btn');
    if (!btn) return;
    
    // 禁用按钮，显示加载状态
    btn.disabled = true;
    btn.classList.add('loading');
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span>⏳ 分析中...</span>';
    
    try {
        console.log('[热门股] 开始更新热门股数据...');
        
        const response = await fetch('/api/stocks/update-heat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force_update: true })
        });
        
        const data = await response.json();
        
        if (data.success) {
            const hotCount = data.data?.hot_count || 0;
            const analyzedStocks = data.data?.analyzed_stocks || 0;
            const totalStocks = data.data?.total_stocks || 0;
            
            showToast(`热门股更新完成！分析${analyzedStocks}只股票，标记${hotCount}只热门股`, 'success');
            console.log('[热门股] 更新完成:', data);
            
            // 刷新板块概览
            await loadPlateOverview();
            
            // 更新热度状态显示
            updateHeatStatusDisplay(hotCount);
        } else {
            showToast(data.message || '热门股更新失败', 'error');
            console.error('[热门股] 更新失败:', data.message);
        }
    } catch (error) {
        console.error('[热门股] 更新异常:', error);
        showToast('热门股更新失败', 'error');
    } finally {
        // 恢复按钮状态
        btn.disabled = false;
        btn.classList.remove('loading');
        btn.innerHTML = originalText;
    }
}

/**
 * 更新热度状态显示
 */
function updateHeatStatusDisplay(hotCount) {
    const hotCountEl = document.getElementById('hot-stock-count');
    const updateTimeEl = document.getElementById('heat-update-time');
    
    if (hotCountEl) {
        hotCountEl.textContent = `热门股: ${hotCount}`;
    }
    
    if (updateTimeEl) {
        const now = new Date().toLocaleString('zh-CN', {
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
        updateTimeEl.textContent = `更新于: ${now}`;
    }
}

// ==================== 导出全局函数 ====================
window.viewStockDetail = viewStockDetail;
window.filterByPlate = filterByPlate;
window.goToPlateStocks = goToPlateStocks;
window.updateHotStocks = updateHotStocks;
