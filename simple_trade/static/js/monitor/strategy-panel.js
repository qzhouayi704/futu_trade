/**
 * 策略监控 - 策略面板模块
 * 功能：策略选择器、参数方案管理、监控启动对话框
 * 
 * 依赖：AppState (全局状态对象)
 */

// ==================== 监控启动对话框状态 ====================
const MonitorStartState = {
    isStarting: false,
    phase: 'init',
    batchNum: 0,
    totalBatches: 0,
    activeCount: 0,
    waitingSeconds: 0,
    waitIntervalId: null,
    progressIntervalId: null
};

// ==================== 监控启动对话框 ====================

/**
 * 显示监控启动对话框
 */
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
    
    // 重置状态
    MonitorStartState.isStarting = true;
    MonitorStartState.phase = 'init';
    MonitorStartState.batchNum = 0;
    MonitorStartState.totalBatches = 0;
    MonitorStartState.activeCount = 0;
    MonitorStartState.waitingSeconds = 0;
    MonitorStartState.waitIntervalId = null;
    MonitorStartState.progressIntervalId = null;
    
    startMonitorProgressSimulation();
}

/**
 * 添加监控启动对话框样式
 */
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

/**
 * 启动监控进度模拟
 */
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
        
        if (elapsed % 5 === 0 && MonitorStartState.phase === 'filtering') {
            const batchNum = Math.min(Math.ceil(elapsed / 30), 3);
            const activeCount = Math.min(elapsed * 5, 150);
            updateMonitorStartStatus({ batchNum, totalBatches: 3, activeCount });
        }
        
        if (!MonitorStartState.isStarting || MonitorStartState.phase === 'completed') {
            clearInterval(progressInterval);
        }
        
        if (elapsed > 300) {
            clearInterval(progressInterval);
        }
    }, 1000);
    
    MonitorStartState.progressIntervalId = progressInterval;
}

/**
 * 启动等待倒计时
 */
function startWaitCountdown(totalSeconds) {
    const waitEl = document.getElementById('monitor-wait');
    const waitText = document.getElementById('monitor-wait-text');
    const waitBar = document.getElementById('monitor-wait-bar');
    
    if (!waitEl) return;
    
    waitEl.style.display = 'block';
    MonitorStartState.waitingSeconds = totalSeconds;
    
    if (MonitorStartState.waitIntervalId) {
        clearInterval(MonitorStartState.waitIntervalId);
    }
    
    const updateWait = () => {
        const remaining = MonitorStartState.waitingSeconds;
        const progress = ((totalSeconds - remaining) / totalSeconds) * 100;
        
        if (waitText) waitText.textContent = `等待反订阅限制解除 (${remaining}秒)`;
        if (waitBar) waitBar.style.width = `${progress}%`;
        
        MonitorStartState.waitingSeconds--;
        
        if (remaining <= 0) {
            clearInterval(MonitorStartState.waitIntervalId);
            MonitorStartState.waitIntervalId = null;
            waitEl.style.display = 'none';
            updateMonitorStartStatus({ phase: 'filtering', tip: '继续处理下一批...' });
        }
    };
    
    updateWait();
    MonitorStartState.waitIntervalId = setInterval(updateWait, 1000);
}

/**
 * 更新监控启动状态
 */
function updateMonitorStartStatus(info) {
    if (!info) return;
    
    const titleEl = document.getElementById('monitor-start-title');
    const phaseEl = document.getElementById('monitor-start-phase');
    const tipEl = document.getElementById('monitor-start-tip');
    const batchNumEl = document.getElementById('monitor-batch-num');
    const activeCountEl = document.getElementById('monitor-active-count');
    
    if (info.phase) {
        MonitorStartState.phase = info.phase;
        
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
        MonitorStartState.batchNum = info.batchNum;
        if (batchNumEl) batchNumEl.textContent = `${info.batchNum}/${info.totalBatches || '?'}`;
    }
    
    if (info.activeCount !== undefined) {
        MonitorStartState.activeCount = info.activeCount;
        if (activeCountEl) activeCountEl.textContent = info.activeCount;
    }
}

/**
 * 隐藏监控启动对话框
 */
function hideMonitorStartDialog() {
    const dialog = document.getElementById('monitor-start-dialog');
    if (dialog) {
        dialog.style.display = 'none';
    }
    
    MonitorStartState.isStarting = false;
    
    if (MonitorStartState.waitIntervalId) {
        clearInterval(MonitorStartState.waitIntervalId);
        MonitorStartState.waitIntervalId = null;
    }
    if (MonitorStartState.progressIntervalId) {
        clearInterval(MonitorStartState.progressIntervalId);
        MonitorStartState.progressIntervalId = null;
    }
}

// ==================== 导出到全局 ====================
window.MonitorStartState = MonitorStartState;
window.showMonitorStartDialog = showMonitorStartDialog;
window.hideMonitorStartDialog = hideMonitorStartDialog;
window.updateMonitorStartStatus = updateMonitorStartStatus;
