/**
 * 策略监控 - 板块概览模块
 * 功能：板块概览、热门股展示、股票池管理
 * 
 * 依赖：AppState (全局状态对象)
 */

// ==================== 板块概览 ====================

/**
 * 加载板块概览
 */
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

/**
 * 渲染板块概览
 */
function renderPlateOverview(plates) {
    const container = document.getElementById('plates-container');
    if (!container) return;

    if (!plates || plates.length === 0) {
        container.innerHTML = '<div class="empty-state">暂无板块数据</div>';
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

        const heatValue = plate.heat_value || 0;
        const avgChange = plate.avg_change || 0;
        const heatClass = heatValue >= 50 ? 'heat-high' : 'heat-low';
        const changeClass = avgChange >= 0 ? 'price-up' : 'price-down';
        const changeSign = avgChange >= 0 ? '+' : '';

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

/**
 * 跳转到板块股票页面
 */
function goToPlateStocks(plateCode) {
    if (!plateCode) {
        console.error('板块代码为空');
        return;
    }
    window.location.href = `/plate/${encodeURIComponent(plateCode)}`;
}

/**
 * 按板块筛选
 */
function filterByPlate(plateName) {
    const plateFilter = document.getElementById('plate-filter');
    if (plateFilter) {
        plateFilter.value = plateName;
        filterStocks();
    }
}

// ==================== 热门股更新 ====================

/**
 * 更新热门股数据
 */
async function updateHotStocks() {
    const btn = document.getElementById('update-heat-btn');
    if (!btn) return;
    
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
            
            showToast(`热门股更新完成！分析${analyzedStocks}只股票，标记${hotCount}只热门股`, 'success');
            console.log('[热门股] 更新完成:', data);
            
            await loadPlateOverview();
            updateHeatStatusDisplay(hotCount);
        } else {
            showToast(data.message || '热门股更新失败', 'error');
            console.error('[热门股] 更新失败:', data.message);
        }
    } catch (error) {
        console.error('[热门股] 更新异常:', error);
        showToast('热门股更新失败', 'error');
    } finally {
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

// ==================== 股票池管理 ====================

/**
 * 加载股票池
 */
async function loadStockPool() {
    try {
        const response = await fetch('/api/stocks/pool');
        const data = await response.json();
        
        if (data.success) {
            AppState.stocks = data.data.stocks || [];
            updatePlateFilter(AppState.stocks);
            renderStocksTable(AppState.stocks);
            updateSignalCountsFromStocks(AppState.stocks);
            updateMarketStatus(data.data);
            console.log('[股票池] 加载完成，共', AppState.stocks.length, '只股票');
        }
    } catch (error) {
        console.error('加载股票池失败:', error);
        showToast('加载股票池失败', 'error');
    }
}

/**
 * 更新板块过滤器
 */
function updatePlateFilter(stocks) {
    const plateFilter = document.getElementById('plate-filter');
    if (!plateFilter) return;
    
    AppState.plates.clear();
    stocks.forEach(stock => {
        if (stock.plate) {
            AppState.plates.add(stock.plate);
        }
    });
    
    const currentValue = plateFilter.value;
    
    plateFilter.innerHTML = '<option value="">全部板块</option>';
    Array.from(AppState.plates).sort().forEach(plate => {
        const option = document.createElement('option');
        option.value = plate;
        option.textContent = plate;
        plateFilter.appendChild(option);
    });
    
    if (currentValue && AppState.plates.has(currentValue)) {
        plateFilter.value = currentValue;
    }
}

/**
 * 更新市场状态（保留接口）
 */
function updateMarketStatus(data) {
    // 此函数保留以防后续需要
}

/**
 * 渲染股票表格
 */
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

/**
 * 获取信号样式类
 */
function getSignalClass(conditions) {
    if (conditions.buy_signal || conditions.is_buy_point) {
        return 'signal-buy';
    }
    if (conditions.sell_signal || conditions.is_sell_point) {
        return 'signal-sell';
    }
    return '';
}

/**
 * 获取信号文本
 */
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

/**
 * 筛选股票
 */
function filterStocks() {
    const searchTerm = (document.getElementById('stock-search')?.value || '').toLowerCase();
    const plateFilter = document.getElementById('plate-filter')?.value || '';
    const signalFilter = document.getElementById('signal-filter')?.value || '';
    
    const filtered = AppState.stocks.filter(stock => {
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
    
    renderStocksTable(filtered);
}

/**
 * 获取筛选后的股票
 */
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

// ==================== 导出到全局 ====================
window.loadPlateOverview = loadPlateOverview;
window.renderPlateOverview = renderPlateOverview;
window.goToPlateStocks = goToPlateStocks;
window.filterByPlate = filterByPlate;
window.updateHotStocks = updateHotStocks;
window.updateHeatStatusDisplay = updateHeatStatusDisplay;
window.loadStockPool = loadStockPool;
window.updatePlateFilter = updatePlateFilter;
window.updateMarketStatus = updateMarketStatus;
window.renderStocksTable = renderStocksTable;
window.getSignalClass = getSignalClass;
window.getSignalText = getSignalText;
window.filterStocks = filterStocks;
window.getFilteredStocks = getFilteredStocks;
