/**
 * 交易面板 - 交易表单和控制模块
 * 负责交易面板更新、下单确认、WebSocket 和价格更新
 */

// ============================================================
// 初始化
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    initTradingPanel();
});

/**
 * 初始化交易面板
 */
function initTradingPanel() {
    initEventListeners();
    initWebSocket();
    loadTradingSignals();
    loadPositions();
    checkFutuStatus();
    
    // 检查URL参数
    const urlParams = new URLSearchParams(window.location.search);
    const stockCode = urlParams.get('stock');
    if (stockCode) {
        selectStockByCode(stockCode);
    }
}

/**
 * 初始化事件监听
 */
function initEventListeners() {
    // 买卖按钮事件
    document.getElementById('btn-buy').addEventListener('click', () => {
        showTradeConfirmation('BUY');
    });
    
    document.getElementById('btn-sell').addEventListener('click', () => {
        showTradeConfirmation('SELL');
    });
    
    // 交易确认按钮
    document.getElementById('confirm-trade-btn').addEventListener('click', () => {
        executeTrade();
    });
    
    // 取消交易按钮
    document.getElementById('cancel-trade-btn')?.addEventListener('click', () => {
        hideModal('trade-confirm-modal');
    });
    
    // 模态框关闭按钮
    document.getElementById('modal-close-btn')?.addEventListener('click', () => {
        hideModal('trade-confirm-modal');
    });
    
    // 刷新持仓按钮
    document.getElementById('btn-refresh-positions')?.addEventListener('click', () => {
        loadPositions();
    });
    
    // 交易数量输入验证
    document.getElementById('trade-quantity').addEventListener('input', (e) => {
        validateTradeQuantity(e.target.value);
    });
    
    // 交易价格输入
    document.getElementById('trade-price').addEventListener('input', (e) => {
        updateTradeAmount();
    });
}

// ============================================================
// 模态框控制
// ============================================================

function showModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.style.display = 'flex';
}

function hideModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.style.display = 'none';
}

// ============================================================
// WebSocket
// ============================================================

function initWebSocket() {
    try {
        TradingState.socket = io();
        
        TradingState.socket.on('connect', () => {
            console.log('WebSocket连接成功');
        });
        
        TradingState.socket.on('disconnect', () => {
            console.log('WebSocket连接断开');
            showToast('WebSocket连接断开', 'warning');
        });
        
        TradingState.socket.on('price_update', (data) => {
            updateStockPrice(data);
        });
        
        TradingState.socket.on('trade_result', (data) => {
            handleTradeResult(data);
        });
        
    } catch (error) {
        console.error('WebSocket初始化失败:', error);
    }
}

// ============================================================
// 交易面板更新
// ============================================================

function updateTradePanel() {
    if (!TradingState.selectedStock) return;
    
    const stock = TradingState.selectedStock;
    
    document.getElementById('stock-code').value = stock.code;
    document.getElementById('current-price').value = stock.last_price?.toFixed(2) || '--';
    document.getElementById('price-change').value = 
        `${stock.change_percent >= 0 ? '+' : ''}${stock.change_percent?.toFixed(2) || '--'}%`;
    document.getElementById('trade-price').value = stock.last_price?.toFixed(2) || '';
    
    // 根据信号类型设置默认交易数量
    if (!stock.from_position) {
        document.getElementById('trade-quantity').value = 100;
    }
    
    // 更新价格颜色
    const changeInput = document.getElementById('price-change');
    changeInput.className = `form-input ${stock.change_percent >= 0 ? 'price-up' : 'price-down'}`;
    
    updateTradeAmount();
}

function updateTradeAmount() {
    const price = parseFloat(document.getElementById('trade-price').value) || 0;
    const quantity = parseInt(document.getElementById('trade-quantity').value) || 0;
    const amount = price * quantity;
    console.log('预计交易金额:', amount);
}

function validateTradeQuantity(value) {
    const quantity = parseInt(value);
    if (quantity < 100 || quantity % 100 !== 0) {
        document.getElementById('trade-quantity').setCustomValidity('交易数量必须是100的倍数且不少于100股');
    } else {
        document.getElementById('trade-quantity').setCustomValidity('');
    }
    updateTradeAmount();
}

// ============================================================
// 交易确认和执行
// ============================================================

function showTradeConfirmation(tradeType) {
    if (!TradingState.selectedStock) {
        showToast('请先选择股票', 'warning');
        return;
    }
    
    const stockCode = TradingState.selectedStock.code;
    const price = parseFloat(document.getElementById('trade-price').value) || TradingState.selectedStock.last_price;
    const quantity = parseInt(document.getElementById('trade-quantity').value);
    const amount = price * quantity;
    
    // 验证输入
    if (!quantity || quantity < 100 || quantity % 100 !== 0) {
        showToast('请输入有效的交易数量（100的倍数）', 'warning');
        return;
    }
    
    if (!price || price <= 0) {
        showToast('请输入有效的交易价格', 'warning');
        return;
    }
    
    // 填充确认对话框
    const currencySymbol = getCurrencySymbol(stockCode);
    document.getElementById('confirm-stock-code').textContent = `${stockCode} (${TradingState.selectedStock.name})`;
    document.getElementById('confirm-trade-type').textContent = tradeType === 'BUY' ? '买入' : '卖出';
    document.getElementById('confirm-trade-price').textContent = `${currencySymbol}${price.toFixed(2)}`;
    document.getElementById('confirm-trade-quantity').textContent = `${quantity}股`;
    document.getElementById('confirm-trade-amount').textContent = `${currencySymbol}${amount.toFixed(2)}`;
    
    // 存储交易数据
    TradingState.pendingTrade = {
        stock_code: stockCode,
        trade_type: tradeType,
        price: price,
        quantity: quantity,
        amount: amount
    };
    
    showModal('trade-confirm-modal');
}

async function executeTrade() {
    if (!TradingState.pendingTrade) return;
    
    showModal('loading-modal');
    
    try {
        const response = await fetch('/api/trading/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(TradingState.pendingTrade)
        });
        
        const result = await response.json();
        
        hideModal('loading-modal');
        hideModal('trade-confirm-modal');
        
        if (result.success) {
            showToast('交易提交成功！', 'success');
            handleTradeResult(result.data);
            setTimeout(() => loadPositions(), 2000);
        } else {
            showToast(`交易失败：${result.message}`, 'danger');
        }
        
    } catch (error) {
        hideModal('loading-modal');
        hideModal('trade-confirm-modal');
        console.error('交易执行失败:', error);
        showToast('交易执行失败，请检查网络连接', 'danger');
    }
    
    TradingState.pendingTrade = null;
}

function handleTradeResult(data) {
    console.log('交易结果:', data);
}

// ============================================================
// 价格更新
// ============================================================

function startPriceUpdate() {
    if (TradingState.priceUpdateTimer) {
        clearInterval(TradingState.priceUpdateTimer);
    }

    TradingState.priceUpdateTimer = setInterval(() => {
        updateCurrentPrice();
    }, 10000);
}

async function updateCurrentPrice() {
    if (!TradingState.selectedStock) return;
    
    try {
        const response = await fetch(`/api/quotes?codes=${TradingState.selectedStock.code}`);
        const result = await response.json();
        
        if (result.success && result.data.length > 0) {
            updateStockPrice(result.data[0]);
        }
    } catch (error) {
        console.error('更新股价失败:', error);
    }
}

function updateStockPrice(quote) {
    if (!TradingState.selectedStock || TradingState.selectedStock.code !== quote.code) return;
    
    TradingState.selectedStock.last_price = quote.last_price;
    TradingState.selectedStock.change_percent = quote.change_percent;
    
    document.getElementById('current-price').value = quote.last_price?.toFixed(2) || '--';
    document.getElementById('price-change').value = 
        `${quote.change_percent >= 0 ? '+' : ''}${quote.change_percent?.toFixed(2) || '--'}%`;
    
    const changeInput = document.getElementById('price-change');
    changeInput.className = `form-input ${quote.change_percent >= 0 ? 'price-up' : 'price-down'}`;
    
    // 如果交易价格为空，自动填入当前价格
    const tradePriceInput = document.getElementById('trade-price');
    if (!tradePriceInput.value) {
        tradePriceInput.value = quote.last_price?.toFixed(2) || '';
        updateTradeAmount();
    }
    