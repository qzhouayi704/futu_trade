/**
 * 交易面板 - 信号列表模块
 * 负责交易信号的加载和渲染
 */

// ============================================================
// 全局状态
// ============================================================
const TradingState = {
    selectedStock: null,
    signalStocks: [],
    positions: [],
    pendingTrade: null,
    socket: null,
    priceUpdateTimer: null,
    loadStartTime: null
};

// ============================================================
// 交易信号相关
// ============================================================

/**
 * 加载交易信号
 */
async function loadTradingSignals() {
    try {
        const response = await fetch('/api/trading/signals');
        const result = await response.json();
        
        if (result.success) {
            TradingState.signalStocks = result.data;
            renderSignalStocks();
        } else {
            showNoSignalsMessage();
        }
    } catch (error) {
        console.error('加载交易信号失败:', error);
        showNoSignalsMessage();
    }
}

/**
 * 渲染信号股票列表
 */
function renderSignalStocks() {
    const container = document.getElementById('signal-stocks-list');
    const countBadge = document.getElementById('signal-count');
    
    if (!TradingState.signalStocks.length) {
        showNoSignalsMessage();
        return;
    }
    
    countBadge.textContent = TradingState.signalStocks.length;
    
    const html = TradingState.signalStocks.map(stock => `
        <div class="signal-stock-item" data-stock-code="${stock.code}" onclick="selectStock('${stock.code}')">
            <div class="signal-stock-header">
                <span class="signal-stock-code">${stock.code}</span>
                <span class="signal-stock-price ${stock.change_percent >= 0 ? 'price-up' : 'price-down'}">
                    ${getCurrencySymbol(stock.code)}${stock.last_price?.toFixed(2) || '--'}
                    <span class="signal-stock-change">${stock.change_percent >= 0 ? '+' : ''}${stock.change_percent?.toFixed(2) || '--'}%</span>
                </span>
            </div>
            <div class="signal-stock-footer">
                <span class="signal-stock-name">${stock.name}</span>
                <span class="signal-stock-tag ${stock.signal_type === 'BUY' ? 'buy' : 'sell'}">
                    ${stock.signal_type === 'BUY' ? '🟢买入' : '🔴卖出'}
                </span>
                <span class="signal-stock-time">${formatTime(stock.created_at)}</span>
            </div>
        </div>
    `).join('');
    
    container.innerHTML = html;
}

/**
 * 显示无信号消息
 */
function showNoSignalsMessage() {
    const container = document.getElementById('signal-stocks-list');
    const countBadge = document.getElementById('signal-count');
    
    countBadge.textContent = '0';
    container.innerHTML = `
        <div class="p-3 text-center text-muted">
            <i class="fas fa-info-circle fa-2x mb-2"></i>
            <div>暂无交易信号</div>
            <small>系统将自动检测符合条件的股票并生成交易信号</small>
        </div>
    `;
}

/**
 * 选择股票
 */
function selectStock(stockCode) {
    const stock = TradingState.signalStocks.find(s => s.code === stockCode);
    if (!stock) {
        console.error('未找到股票信息:', stockCode);
        return;
    }
    
    TradingState.selectedStock = stock;
    
    // 更新选中状态
    document.querySelectorAll('.stock-item').forEach(item => {
        item.classList.remove('active');
    });
    const selectedItem = document.querySelector(`[data-stock-code="${stockCode}"]`);
    if (selectedItem) {
        selectedItem.classList.add('active');
    }
    
    updateTradePanel();
    startPriceUpdate();
}

/**
 * 通过代码选择股票
 */
function selectStockByCode(stockCode) {
    const waitForStocks = () => {
        const stockInSignals = TradingState.signalStocks.find(s => s.code === stockCode);
        if (stockInSignals) {
            selectStock(stockCode);
            return;
        }
        
        if (TradingState.signalStocks.length > 0 || Date.now() - TradingState.loadStartTime > 3000) {
            loadStockByCode(stockCode);
        } else {
            setTimeout(waitForStocks, 100);
        }
    };
    
    TradingState.loadStartTime = Date.now();
    waitForStocks();
}

/**
 * 通过代码加载股票
 */
async function loadStockByCode(stockCode) {
    try {
        const response = await fetch(`/api/quotes?codes=${stockCode}`);
        const result = await response.json();
        
        if (result.success && result.data && result.data.length > 0) {
            const quote = result.data[0];
            
            const tempStock = {
                code: quote.code,
                name: quote.name,
                last_price: quote.current_price,
                change_percent: quote.change_percent,
                signal_type: 'BUY',
                created_at: new Date().toISOString()
            };
            
            TradingState.signalStocks.unshift(tempStock);
            renderSignalStocks();
            selectStock(stockCode);
            
            showToast(`已加载股票 ${stockCode}`, 'info');
        } else {
            showToast(`未找到股票 ${stockCode} 的信息`, 'warning');
        }
    } catch (error) {
        console.error('加载股票信息失败:', error);
        showToast(`加载股票 ${stockCode} 信息失败`, 'danger');
    }
}

// ============================================================
// 工具函数
// ============================================================

/**
 * 显示 Toast 消息
 */
function showToast(message, type = 'info') {
    if (typeof window.showToast === 'function') {
        window.showToast('交易面板', message, type);
    } else {
        console.log(`[${type}] ${message}`);
    }
}

/**
 * 格式化时间
 */
function formatTime(isoString) {
    if (typeof TradeUtils !== 'undefined' && TradeUtils.formatRelativeTime) {
        return TradeUtils.formatRelativeTime(isoString);
    }
    if (!isoString) return '--';
    try {
        return new Date(isoString).toLocaleDateString();
    } catch (e) {
        return '--';
    }
}

/**
 * 获取货币符号
 */
function getCurrencySymbol(stockCode) {
    if (!stockCode) return '';
    if (stockCode.startsWith('HK.')) return 'HK$';
    if (stockCode.startsWith('US.')) return '$';
    return '';
}

/**
 * 格式化金额
 */
function formatMoney(value, stockCode = null) {
    if (value === null || value === undefined || isNaN(value)) {
        return '--';
    }
    
    const symbol = stockCode ? getCurrencySymbol(stockCode) : '';
    const absValue = Math.abs(value);
    if (absValue >= 10000) {
        return `${symbol}${(value / 10000).toFixed(2)}万`;
    }
    return `${symbol}${value.toFixed(2)}`;
}

// 导出全局函数和状态
window.TradingState = TradingState;
window.loadTradingSignals = loadTradingSignals;
window.renderSignalStocks = renderSignalStocks;
window.selectStock = selectStock;
window.selectStockByCode = selectStockByCode;
window.getCurrencySymbol = getCurrencySymbol;
window.formatMoney = formatMoney;

console.log('交易面板 - 信号列表模块加载完成');
