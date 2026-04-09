/**
 * 交易面板JavaScript逻辑
 */

class TradingPanel {
    constructor() {
        this.selectedStock = null;
        this.socket = null;
        this.priceUpdateTimer = null;
        this.signalStocks = [];
        this.positions = [];
        
        this.init();
    }
    
    init() {
        this.initEventListeners();
        this.initWebSocket();
        this.loadTradingSignals();
        this.loadPositions();
        this.checkFutuStatus();
        
        // 检查URL参数，看是否指定了股票
        const urlParams = new URLSearchParams(window.location.search);
        const stockCode = urlParams.get('stock');
        if (stockCode) {
            this.selectStockByCode(stockCode);
        }
    }
    
    initEventListeners() {
        // 买卖按钮事件
        document.getElementById('btn-buy').addEventListener('click', () => {
            this.showTradeConfirmation('BUY');
        });
        
        document.getElementById('btn-sell').addEventListener('click', () => {
            this.showTradeConfirmation('SELL');
        });
        
        // 交易确认按钮
        document.getElementById('confirm-trade-btn').addEventListener('click', () => {
            this.executeTrade();
        });
        
        // 取消交易按钮
        document.getElementById('cancel-trade-btn')?.addEventListener('click', () => {
            this.hideModal('trade-confirm-modal');
        });
        
        // 模态框关闭按钮
        document.getElementById('modal-close-btn')?.addEventListener('click', () => {
            this.hideModal('trade-confirm-modal');
        });
        
        // 刷新持仓按钮
        document.getElementById('btn-refresh-positions')?.addEventListener('click', () => {
            this.loadPositions();
        });
        
        // 交易数量输入验证
        document.getElementById('trade-quantity').addEventListener('input', (e) => {
            this.validateTradeQuantity(e.target.value);
        });
        
        // 交易价格输入
        document.getElementById('trade-price').addEventListener('input', (e) => {
            this.updateTradeAmount();
        });
    }
    
    // 显示模态框
    showModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.style.display = 'flex';
        }
    }
    
    // 隐藏模态框
    hideModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.style.display = 'none';
        }
    }
    
    initWebSocket() {
        try {
            this.socket = io();
            
            this.socket.on('connect', () => {
                console.log('WebSocket连接成功');
            });
            
            this.socket.on('disconnect', () => {
                console.log('WebSocket连接断开');
                this.showToast('WebSocket连接断开', 'warning');
            });
            
            this.socket.on('price_update', (data) => {
                this.updateStockPrice(data);
            });
            
            this.socket.on('trade_result', (data) => {
                this.handleTradeResult(data);
            });
            
        } catch (error) {
            console.error('WebSocket初始化失败:', error);
        }
    }
    
    // ==================== 交易信号相关 ====================
    
    async loadTradingSignals() {
        try {
            const response = await fetch('/api/trading/signals');
            const result = await response.json();
            
            if (result.success) {
                this.signalStocks = result.data;
                this.renderSignalStocks();
            } else {
                this.showNoSignalsMessage();
            }
        } catch (error) {
            console.error('加载交易信号失败:', error);
            this.showNoSignalsMessage();
        }
    }
    
    renderSignalStocks() {
        const container = document.getElementById('signal-stocks-list');
        const countBadge = document.getElementById('signal-count');
        
        if (!this.signalStocks.length) {
            this.showNoSignalsMessage();
            return;
        }
        
        countBadge.textContent = this.signalStocks.length;
        
        const html = this.signalStocks.map(stock => `
            <div class="signal-stock-item" data-stock-code="${stock.code}" onclick="tradingPanel.selectStock('${stock.code}')">
                <div class="signal-stock-header">
                    <span class="signal-stock-code">${stock.code}</span>
                    <span class="signal-stock-price ${stock.change_percent >= 0 ? 'price-up' : 'price-down'}">
                        ${this.getCurrencySymbol(stock.code)}${stock.last_price?.toFixed(2) || '--'}
                        <span class="signal-stock-change">${stock.change_percent >= 0 ? '+' : ''}${stock.change_percent?.toFixed(2) || '--'}%</span>
                    </span>
                </div>
                <div class="signal-stock-footer">
                    <span class="signal-stock-name">${stock.name}</span>
                    <span class="signal-stock-tag ${stock.signal_type === 'BUY' ? 'buy' : 'sell'}">
                        ${stock.signal_type === 'BUY' ? '🟢买入' : '🔴卖出'}
                    </span>
                    <span class="signal-stock-time">${this.formatTime(stock.created_at)}</span>
                </div>
            </div>
        `).join('');
        
        container.innerHTML = html;
    }
    
    showNoSignalsMessage() {
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
    
    selectStock(stockCode) {
        // 查找股票信息
        const stock = this.signalStocks.find(s => s.code === stockCode);
        if (!stock) {
            console.error('未找到股票信息:', stockCode);
            return;
        }
        
        this.selectedStock = stock;
        
        // 更新选中状态
        document.querySelectorAll('.stock-item').forEach(item => {
            item.classList.remove('active');
        });
        const selectedItem = document.querySelector(`[data-stock-code="${stockCode}"]`);
        if (selectedItem) {
            selectedItem.classList.add('active');
        }
        
        // 更新交易面板
        this.updateTradePanel();
        
        // 开始价格实时更新
        this.startPriceUpdate();
    }
    
    selectStockByCode(stockCode) {
        // 等待股票列表加载完成后再选择
        const waitForStocks = () => {
            // 首先检查股票是否在信号列表中
            const stockInSignals = this.signalStocks.find(s => s.code === stockCode);
            if (stockInSignals) {
                this.selectStock(stockCode);
                return;
            }
            
            // 如果不在信号列表中，尝试从API获取股票信息
            if (this.signalStocks.length > 0 || Date.now() - this.loadStartTime > 3000) {
                // 信号列表已加载完成或超时，尝试获取股票信息
                this.loadStockByCode(stockCode);
            } else {
                // 继续等待信号列表加载
                setTimeout(waitForStocks, 100);
            }
        };
        
        this.loadStartTime = Date.now();
        waitForStocks();
    }
    
    async loadStockByCode(stockCode) {
        try {
            // 从API获取股票基本信息
            const response = await fetch(`/api/quotes?codes=${stockCode}`);
            const result = await response.json();
            
            if (result.success && result.data && result.data.length > 0) {
                const quote = result.data[0];
                
                // 创建一个临时股票对象
                const tempStock = {
                    code: quote.code,
                    name: quote.name,
                    last_price: quote.current_price,
                    change_percent: quote.change_percent,
                    signal_type: 'BUY', // 默认买入信号
                    created_at: new Date().toISOString()
                };
                
                // 添加到信号列表的开头（方便查看）
                this.signalStocks.unshift(tempStock);
                this.renderSignalStocks();
                
                // 选中该股票
                this.selectStock(stockCode);
                
                this.showToast(`已加载股票 ${stockCode}`, 'info');
            } else {
                this.showToast(`未找到股票 ${stockCode} 的信息`, 'warning');
            }
        } catch (error) {
            console.error('加载股票信息失败:', error);
            this.showToast(`加载股票 ${stockCode} 信息失败`, 'danger');
        }
    }
    
    // ==================== 持仓信息相关 ====================
    
    async loadPositions() {
        try {
            const container = document.getElementById('positions-list');
            container.innerHTML = `
                <div class="empty-state">
                    <span class="empty-icon">⏳</span>
                    <p>正在加载持仓信息...</p>
                </div>
            `;
            
            const response = await fetch('/api/trading/positions');
            const result = await response.json();
            
            if (result.success) {
                this.positions = result.data || [];
                this.renderPositions();
                this.updatePositionsSummary();
            } else {
                this.showNoPositionsMessage(result.message || '加载失败');
            }
        } catch (error) {
            console.error('加载持仓信息失败:', error);
            this.showNoPositionsMessage('网络错误，请检查连接');
        }
    }
    
    renderPositions() {
        const container = document.getElementById('positions-list');
        const countBadge = document.getElementById('positions-count');
        
        if (!this.positions.length) {
            this.showNoPositionsMessage('暂无持仓');
            return;
        }
        
        countBadge.textContent = this.positions.length;
        
        const html = this.positions.map(position => {
            const plClass = position.pl_val >= 0 ? 'price-up' : 'price-down';
            const plSign = position.pl_val >= 0 ? '+' : '';
            
            return `
                <div class="position-item" data-position-code="${position.stock_code}" onclick="tradingPanel.selectPosition('${position.stock_code}')">
                    <div class="position-header">
                        <div class="position-stock">
                            <span class="position-code">${position.stock_code}</span>
                            <span class="position-name">${position.stock_name || '--'}</span>
                        </div>
                        <div class="position-qty">
                            <span class="qty-value">${position.qty}</span>
                            <span class="qty-label">股</span>
                            <span class="can-sell">(可卖: ${position.can_sell_qty})</span>
                        </div>
                    </div>
                    <div class="position-details">
                        <div class="position-prices">
                            <div class="price-item">
                                <span class="price-label">现价</span>
                                <span class="price-value">${position.nominal_price?.toFixed(2) || '--'}</span>
                            </div>
                            <div class="price-item">
                                <span class="price-label">成本</span>
                                <span class="price-value">${position.cost_price?.toFixed(2) || '--'}</span>
                            </div>
                            <div class="price-item">
                                <span class="price-label">市值</span>
                                <span class="price-value">${this.formatMoney(position.market_val, position.stock_code)}</span>
                            </div>
                        </div>
                        <div class="position-pl ${plClass}">
                            <div class="pl-value">${plSign}${this.formatMoney(position.pl_val, position.stock_code)}</div>
                            <div class="pl-ratio">${plSign}${position.pl_ratio?.toFixed(2) || '0.00'}%</div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
        
        container.innerHTML = html;
    }
    
    showNoPositionsMessage(message = '暂无持仓') {
        const container = document.getElementById('positions-list');
        const countBadge = document.getElementById('positions-count');
        
        countBadge.textContent = '0';
        container.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">📦</span>
                <p>${message}</p>
                <small>点击刷新按钮重新加载</small>
            </div>
        `;
    }
    
    updatePositionsSummary() {
        if (!this.positions.length) {
            document.getElementById('summary-count').textContent = '0';
            document.getElementById('summary-market-val').textContent = '--';
            document.getElementById('summary-pl-val').textContent = '--';
            document.getElementById('summary-pl-ratio').textContent = '--';
            return;
        }
        
        // 计算汇总数据
        const totalMarketVal = this.positions.reduce((sum, p) => sum + (p.market_val || 0), 0);
        const totalPlVal = this.positions.reduce((sum, p) => sum + (p.pl_val || 0), 0);
        const totalCost = this.positions.reduce((sum, p) => sum + ((p.cost_price || 0) * (p.qty || 0)), 0);
        const avgPlRatio = totalCost > 0 ? (totalPlVal / totalCost * 100) : 0;
        
        document.getElementById('summary-count').textContent = this.positions.length;
        document.getElementById('summary-market-val').textContent = this.formatMoney(totalMarketVal);
        
        const plValElement = document.getElementById('summary-pl-val');
        const plRatioElement = document.getElementById('summary-pl-ratio');
        
        const plSign = totalPlVal >= 0 ? '+' : '';
        const plClass = totalPlVal >= 0 ? 'price-up' : 'price-down';
        
        plValElement.textContent = `${plSign}${this.formatMoney(totalPlVal)}`;
        plValElement.className = `summary-value ${plClass}`;
        
        plRatioElement.textContent = `${plSign}${avgPlRatio.toFixed(2)}%`;
        plRatioElement.className = `summary-value ${plClass}`;
    }
    
    /**
     * 点击持仓股票，自动填充到交易面板
     */
    selectPosition(stockCode) {
        // 查找持仓信息
        const position = this.positions.find(p => p.stock_code === stockCode);
        if (!position) {
            console.error('未找到持仓信息:', stockCode);
            return;
        }
        
        // 更新持仓选中状态
        document.querySelectorAll('.position-item').forEach(item => {
            item.classList.remove('active');
        });
        const selectedItem = document.querySelector(`[data-position-code="${stockCode}"]`);
        if (selectedItem) {
            selectedItem.classList.add('active');
        }
        
        // 取消信号股票的选中状态
        document.querySelectorAll('.stock-item').forEach(item => {
            item.classList.remove('active');
        });
        
        // 创建临时股票对象用于交易面板
        this.selectedStock = {
            code: position.stock_code,
            name: position.stock_name || position.stock_code,
            last_price: position.nominal_price,
            change_percent: position.pl_ratio,
            signal_type: 'SELL', // 持仓默认为卖出
            from_position: true
        };
        
        // 更新交易面板
        this.updateTradePanel();
        
        // 设置交易数量为可卖数量
        document.getElementById('trade-quantity').value = position.can_sell_qty || position.qty;
        
        // 开始价格实时更新
        this.startPriceUpdate();
    }
    
    // ==================== 交易面板相关 ====================
    
    updateTradePanel() {
        if (!this.selectedStock) return;
        
        const stock = this.selectedStock;
        
        document.getElementById('stock-code').value = stock.code;
        document.getElementById('current-price').value = stock.last_price?.toFixed(2) || '--';
        document.getElementById('price-change').value = 
            `${stock.change_percent >= 0 ? '+' : ''}${stock.change_percent?.toFixed(2) || '--'}%`;
        document.getElementById('trade-price').value = stock.last_price?.toFixed(2) || '';
        
        // 根据信号类型设置默认交易数量（如果不是从持仓来的）
        if (!stock.from_position) {
            const defaultQuantity = 100;
            document.getElementById('trade-quantity').value = defaultQuantity;
        }
        
        // 更新价格颜色
        const changeInput = document.getElementById('price-change');
        changeInput.className = `form-input ${stock.change_percent >= 0 ? 'price-up' : 'price-down'}`;
        
        // 更新交易金额
        this.updateTradeAmount();
    }
    
    updateTradeAmount() {
        const price = parseFloat(document.getElementById('trade-price').value) || 0;
        const quantity = parseInt(document.getElementById('trade-quantity').value) || 0;
        const amount = price * quantity;
        
        // 可以在界面上显示预计金额（如果需要的话）
        console.log('预计交易金额:', amount);
    }
    
    validateTradeQuantity(value) {
        const quantity = parseInt(value);
        if (quantity < 100 || quantity % 100 !== 0) {
            document.getElementById('trade-quantity').setCustomValidity('交易数量必须是100的倍数且不少于100股');
        } else {
            document.getElementById('trade-quantity').setCustomValidity('');
        }
        this.updateTradeAmount();
    }
    
    showTradeConfirmation(tradeType) {
        if (!this.selectedStock) {
            this.showToast('请先选择股票', 'warning');
            return;
        }
        
        const stockCode = this.selectedStock.code;
        const price = parseFloat(document.getElementById('trade-price').value) || this.selectedStock.last_price;
        const quantity = parseInt(document.getElementById('trade-quantity').value);
        const amount = price * quantity;
        
        // 验证输入
        if (!quantity || quantity < 100 || quantity % 100 !== 0) {
            this.showToast('请输入有效的交易数量（100的倍数）', 'warning');
            return;
        }
        
        if (!price || price <= 0) {
            this.showToast('请输入有效的交易价格', 'warning');
            return;
        }
        
        // 填充确认对话框
        const currencySymbol = this.getCurrencySymbol(stockCode);
        document.getElementById('confirm-stock-code').textContent = `${stockCode} (${this.selectedStock.name})`;
        document.getElementById('confirm-trade-type').textContent = tradeType === 'BUY' ? '买入' : '卖出';
        document.getElementById('confirm-trade-price').textContent = `${currencySymbol}${price.toFixed(2)}`;
        document.getElementById('confirm-trade-quantity').textContent = `${quantity}股`;
        document.getElementById('confirm-trade-amount').textContent = `${currencySymbol}${amount.toFixed(2)}`;
        
        // 存储交易数据
        this.pendingTrade = {
            stock_code: stockCode,
            trade_type: tradeType,
            price: price,
            quantity: quantity,
            amount: amount
        };
        
        // 显示确认对话框（使用自定义模态框）
        this.showModal('trade-confirm-modal');
    }
    
    async executeTrade() {
        if (!this.pendingTrade) return;
        
        // 显示加载提示（使用自定义模态框）
        this.showModal('loading-modal');
        
        try {
            const response = await fetch('/api/trading/execute', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(this.pendingTrade)
            });
            
            const result = await response.json();
            
            // 隐藏加载提示
            this.hideModal('loading-modal');
            
            // 隐藏确认对话框
            this.hideModal('trade-confirm-modal');
            
            if (result.success) {
                this.showToast('交易提交成功！', 'success');
                this.handleTradeResult(result.data);
                
                // 刷新持仓信息
                setTimeout(() => this.loadPositions(), 2000);
            } else {
                this.showToast(`交易失败：${result.message}`, 'danger');
            }
            
        } catch (error) {
            this.hideModal('loading-modal');
            this.hideModal('trade-confirm-modal');
            console.error('交易执行失败:', error);
            this.showToast('交易执行失败，请检查网络连接', 'danger');
        }
        
        this.pendingTrade = null;
    }
    
    handleTradeResult(data) {
        console.log('交易结果:', data);
        // 可以在这里更新交易历史、持仓等信息
    }
    
    // ==================== 价格更新相关 ====================
    
    startPriceUpdate() {
        if (this.priceUpdateTimer) {
            clearInterval(this.priceUpdateTimer);
        }

        this.priceUpdateTimer = setInterval(() => {
            this.updateCurrentPrice();
        }, 10000); // 每10秒更新一次
    }
    
    async updateCurrentPrice() {
        if (!this.selectedStock) return;
        
        try {
            const response = await fetch(`/api/quotes?codes=${this.selectedStock.code}`);
            const result = await response.json();
            
            if (result.success && result.data.length > 0) {
                const quote = result.data[0];
                this.updateStockPrice(quote);
            }
        } catch (error) {
            console.error('更新股价失败:', error);
        }
    }
    
    updateStockPrice(quote) {
        if (!this.selectedStock || this.selectedStock.code !== quote.code) return;
        
        // 更新选中股票的价格信息
        this.selectedStock.last_price = quote.last_price;
        this.selectedStock.change_percent = quote.change_percent;
        
        // 更新交易面板价格显示
        document.getElementById('current-price').value = quote.last_price?.toFixed(2) || '--';
        document.getElementById('price-change').value = 
            `${quote.change_percent >= 0 ? '+' : ''}${quote.change_percent?.toFixed(2) || '--'}%`;
        
        const changeInput = document.getElementById('price-change');
        changeInput.className = `form-input ${quote.change_percent >= 0 ? 'price-up' : 'price-down'}`;
        
        // 如果交易价格为空，自动填入当前价格
        const tradePriceInput = document.getElementById('trade-price');
        if (!tradePriceInput.value) {
            tradePriceInput.value = quote.last_price?.toFixed(2) || '';
            this.updateTradeAmount();
        }
        
        // 更新股票列表中的价格显示
        const stockItem = document.querySelector(`[data-stock-code="${quote.code}"]`);
        if (stockItem) {
            const priceElement = stockItem.querySelector('.fw-bold:last-child');
            const changeElement = stockItem.querySelector('.small:last-child');
            
            if (priceElement) {
                priceElement.textContent = `${this.getCurrencySymbol(quote.code)}${quote.last_price?.toFixed(2) || '--'}`;
                priceElement.className = `fw-bold ${quote.change_percent >= 0 ? 'price-up' : 'price-down'}`;
            }
            
            if (changeElement) {
                changeElement.textContent = `${quote.change_percent >= 0 ? '+' : ''}${quote.change_percent?.toFixed(2) || '--'}%`;
                changeElement.className = `small ${quote.change_percent >= 0 ? 'price-up' : 'price-down'}`;
            }
        }
    }
    
    // ==================== 系统状态相关 ====================
    
    async checkFutuStatus() {
        try {
            const response = await fetch('/api/system?types=status');
            const result = await response.json();
            
            if (result.success && result.data.status) {
                const status = result.data.status;
                const statusElement = document.getElementById('futu-status-text');
                
                if (status.futu_connected) {
                    statusElement.textContent = '已连接';
                    statusElement.className = 'text-success';
                } else {
                    statusElement.textContent = '未连接';
                    statusElement.className = 'text-danger';
                }
            }
        } catch (error) {
            console.error('检查富途状态失败:', error);
            document.getElementById('futu-status-text').textContent = '检查失败';
        }
    }
    
    // ==================== 工具方法 ====================
    
    // 使用全局工具函数 showToast（来自 common.js）
    showToast(message, type = 'info') {
        if (typeof window.showToast === 'function') {
            window.showToast('交易面板', message, type);
        } else {
            console.log(`[${type}] ${message}`);
        }
    }
    
    // 使用全局工具函数格式化相对时间
    formatTime(isoString) {
        if (typeof TradeUtils !== 'undefined' && TradeUtils.formatRelativeTime) {
            return TradeUtils.formatRelativeTime(isoString);
        }
        // 降级处理
        if (!isoString) return '--';
        try {
            return new Date(isoString).toLocaleDateString();
        } catch (e) {
            return '--';
        }
    }
    
    // 获取货币符号
    getCurrencySymbol(stockCode) {
        if (!stockCode) return '';
        if (stockCode.startsWith('HK.')) return 'HK$';
        if (stockCode.startsWith('US.')) return '$';
        return '';
    }
    
    // 格式化金额（根据股票代码自动选择货币符号）
    formatMoney(value, stockCode = null) {
        if (value === null || value === undefined || isNaN(value)) {
            return '--';
        }
        
        const symbol = stockCode ? this.getCurrencySymbol(stockCode) : '';
        const absValue = Math.abs(value);
        if (absValue >= 10000) {
            return `${symbol}${(value / 10000).toFixed(2)}万`;
        }
        return `${symbol}${value.toFixed(2)}`;
    }
    
    destroy() {
        if (this.priceUpdateTimer) {
            clearInterval(this.priceUpdateTimer);
        }
        
        if (this.socket) {
            this.socket.disconnect();
        }
    }
}

// 全局实例
let tradingPanel;

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    tradingPanel = new TradingPanel();
});

// 页面卸载时清理
window.addEventListener('beforeunload', () => {
    if (tradingPanel) {
        tradingPanel.destroy();
    }
});
