/**
 * 交易面板 - 持仓管理模块
 * 负责持仓信息的加载、渲染和汇总
 */

// ============================================================
// 持仓信息相关
// ============================================================

/**
 * 加载持仓信息
 */
async function loadPositions() {
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
            TradingState.positions = result.data || [];
            renderPositions();
            updatePositionsSummary();
        } else {
            showNoPositionsMessage(result.message || '加载失败');
        }
    } catch (error) {
        console.error('加载持仓信息失败:', error);
        showNoPositionsMessage('网络错误，请检查连接');
    }
}

/**
 * 渲染持仓列表
 */
function renderPositions() {
    const container = document.getElementById('positions-list');
    const countBadge = document.getElementById('positions-count');
    
    if (!TradingState.positions.length) {
        showNoPositionsMessage('暂无持仓');
        return;
    }
    
    countBadge.textContent = TradingState.positions.length;
    
    const html = TradingState.positions.map(position => {
        const plClass = position.pl_val >= 0 ? 'price-up' : 'price-down';
        const plSign = position.pl_val >= 0 ? '+' : '';
        
        return `
            <div class="position-item" data-position-code="${position.stock_code}" onclick="selectPosition('${position.stock_code}')">
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
                            <span class="price-value">${formatMoney(position.market_val, position.stock_code)}</span>
                        </div>
                    </div>
                    <div class="position-pl ${plClass}">
                        <div class="pl-value">${plSign}${formatMoney(position.pl_val, position.stock_code)}</div>
                        <div class="pl-ratio">${plSign}${position.pl_ratio?.toFixed(2) || '0.00'}%</div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
    
    container.innerHTML = html;
}

/**
 * 显示无持仓消息
 */
function showNoPositionsMessage(message = '暂无持仓') {
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

/**
 * 更新持仓汇总
 */
function updatePositionsSummary() {
    if (!TradingState.positions.length) {
        document.getElementById('summary-count').textContent = '0';
        document.getElementById('summary-market-val').textContent = '--';
        document.getElementById('summary-pl-val').textContent = '--';
        document.getElementById('summary-pl-ratio').textContent = '--';
        return;
    }
    
    // 计算汇总数据
    const totalMarketVal = TradingState.positions.reduce((sum, p) => sum + (p.market_val || 0), 0);
    const totalPlVal = TradingState.positions.reduce((sum, p) => sum + (p.pl_val || 0), 0);
    const totalCost = TradingState.positions.reduce((sum, p) => sum + ((p.cost_price || 0) * (p.qty || 0)), 0);
    const avgPlRatio = totalCost > 0 ? (totalPlVal / totalCost * 100) : 0;
    
    document.getElementById('summary-count').textContent = TradingState.positions.length;
    document.getElementById('summary-market-val').textContent = formatMoney(totalMarketVal);
    
    const plValElement = document.getElementById('summary-pl-val');
    const plRatioElement = document.getElementById('summary-pl-ratio');
    
    const plSign = totalPlVal >= 0 ? '+' : '';
    const plClass = totalPlVal >= 0 ? 'price-up' : 'price-down';
    
    plValElement.textContent = `${plSign}${formatMoney(totalPlVal)}`;
    plValElement.className = `summary-value ${plClass}`;
    
    plRatioElement.textContent = `${plSign}${avgPlRatio.toFixed(2)}%`;
    plRatioElement.className = `summary-value ${plClass}`;
}

/**
 * 选择持仓股票
 */
function selectPosition(stockCode) {
    const position = TradingState.positions.find(p => p.stock_code === stockCode);
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
    TradingState.selectedStock = {
        code: position.stock_code,
        name: position.stock_name || position.stock_code,
        last_price: position.nominal_price,
        change_percent: position.pl_ratio,
        signal_type: 'SELL',
        from_position: true
    };
    
    updateTradePanel();
    
    // 设置交易数量为可卖数量
    document.getElementById('trade-quantity').value = position.can_sell_qty || position.qty;
    
    startPriceUpdate();
}

// 导出全局函数
window.loadPositions = loadPositions;
window.renderPositions = renderPositions;
window.selectPosition = selectPosition;
window.updatePositionsSummary = updatePositionsSummary;

console.log('交易面板 - 持仓管理模块加载完成');
