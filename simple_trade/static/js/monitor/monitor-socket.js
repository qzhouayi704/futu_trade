/**
 * 策略监控 - WebSocket 连接和 Toast 通知模块
 * 功能：Socket.IO 连接管理、连接状态显示、Toast 消息
 * 
 * 依赖：AppState (全局状态对象)
 */

// ==================== WebSocket ====================
function initSocket() {
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
    
    AppState.socket.on('connect', function() {
        updateConnectionStatus(true);
        console.log('[WebSocket] 连接成功，ID:', AppState.socket.id);
        setTimeout(() => {
            console.log('[WebSocket] 请求最新数据更新');
            AppState.socket.emit('request_update');
            loadStockPool();
            loadSignalHistory();
        }, 500);
    });
    
    AppState.socket.on('disconnect', function(reason) {
        updateConnectionStatus(false);
        console.log('[WebSocket] 连接断开，原因:', reason);
        if (reason === 'io server disconnect') {
            console.log('[WebSocket] 服务器断开连接，尝试重连...');
            AppState.socket.connect();
        }
    });
    
    AppState.socket.on('connect_error', function(error) {
        console.error('[WebSocket] 连接错误:', error.message);
        updateConnectionStatus(false, '连接错误');
    });
    
    AppState.socket.on('reconnect_attempt', function(attemptNumber) {
        console.log('[WebSocket] 第', attemptNumber, '次重连尝试...');
        updateConnectionStatus(false, '重连中(' + attemptNumber + ')');
    });
    
    AppState.socket.on('reconnect', function(attemptNumber) {
        console.log('[WebSocket] 重连成功，共尝试', attemptNumber, '次');
        updateConnectionStatus(true);
        setTimeout(() => {
            console.log('[WebSocket] 重连后刷新数据');
            AppState.socket.emit('request_update');
            loadStockPool();
            loadSignalHistory();
        }, 500);
    });
    
    AppState.socket.on('reconnect_failed', function() {
        console.error('[WebSocket] 重连失败，已达最大重试次数');
        updateConnectionStatus(false, '重连失败');
    });
    
    AppState.socket.on('strategy_signals', function(data) {
        console.log('[WebSocket] 收到策略信号:', data);
        handleSignals(data.signals || []);
    });
    
    AppState.socket.on('quotes_update', function(data) {
        console.log('[WebSocket] 收到报价更新:', (data.quotes || []).length, '条');
        updateStocksWithQuotes(data.quotes || []);
        
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

        if (data.signals_by_strategy) {
            if (window.StrategyPanel) window.StrategyPanel.updateSignalCounts(data.signals_by_strategy);
            if (window.SignalTabs) window.SignalTabs.updateSignals(data.signals_by_strategy);
        }
    });
    
    AppState.socket.on('conditions_update', function(data) {
        console.log('[WebSocket] 收到交易条件更新:', (data.conditions || []).length, '条');
        updateStocksWithConditions(data.conditions || []);
    });
    
    AppState.socket.on('status', function(data) {
        console.log('[WebSocket] 收到状态更新:', data);
    });
}

// ==================== 连接状态 ====================
function updateConnectionStatus(connected, customText = null) {
    const statusEl = document.getElementById('connection-status');
    if (statusEl) {
        let statusClass = 'status-indicator ';
        if (connected) statusClass += 'connected';
        else if (customText) statusClass += 'error';
        else statusClass += 'disconnected';
        statusEl.className = statusClass;
        
        const textEl = statusEl.querySelector('.status-text');
        if (textEl) textEl.textContent = customText || (connected ? '已连接' : '未连接');
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

// ==================== Toast 通知 ====================
function showToast(message, type = 'info') {
    const existing = document.querySelector('.toast-notification');
    if (existing) existing.remove();
    
    const toast = document.createElement('div');
    toast.className = `toast-notification toast-${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${getToastIcon(type)}</span>
        <span class="toast-message">${message}</span>
    `;
    
    document.body.appendChild(toast);
    addToastStyles();
    setTimeout(() => toast.classList.add('show'), 10);
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
            position: fixed; top: 20px; right: 20px; padding: 12px 20px;
            border-radius: 8px; background: #333; color: #fff;
            display: flex; align-items: center; gap: 10px; z-index: 10000;
            transform: translateX(120%); transition: transform 0.3s ease;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }
        .toast-notification.show { transform: translateX(0); }
        .toast-success { background: #28a745; }
        .toast-error { background: #dc3545; }
        .toast-warning { background: #ffc107; color: #333; }
        .toast-info { background: #17a2b8; }
        .toast-icon { font-size: 16px; }
        .toast-message { font-size: 14px; }
    `;
    document.head.appendChild(style);
}

// ==================== 导出全局函数 ====================
window.initSocket = initSocket;
window.updateConnectionStatus = updateConnectionStatus;
window.showToast = showToast;
window.playSignalSound = function() { return; };

console.log('策略监控 - WebSocket 和通知模块加载完成');
