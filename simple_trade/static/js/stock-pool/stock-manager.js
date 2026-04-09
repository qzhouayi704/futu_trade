/**
 * 股票池管理 - 股票管理模块
 * 功能：股票增删、搜索、筛选、统计
 * 
 * 依赖：StockPoolState (全局状态对象)
 */

// ==================== 股票加载 ====================

/**
 * 加载股票列表（带loading）
 */
async function loadStocks() {
    try {
        showLoading('加载股票数据...');
        await loadStocksInternal();
    } finally {
        hideLoading();
    }
}

/**
 * 加载股票列表（内部版本）
 */
async function loadStocksInternal() {
    try {
        const response = await fetch('/api/data?type=stocks&limit=5000');
        const result = await response.json();
        
        if (result.success) {
            StockPoolState.stocksData = result.data;
            StockPoolState.stocksTotalCount = result.meta?.total || result.data.length;
            StockPoolState.filteredStocks = StockPoolState.stocksData;
            updateStocksPagination();
            console.log(`已加载 ${StockPoolState.stocksData.length} 只股票（总数: ${StockPoolState.stocksTotalCount}）`);
        } else {
            showToast('错误', `加载股票失败: ${result.message || '未知错误'}`, 'danger');
            StockPoolState.stocksData = [];
            StockPoolState.stocksTotalCount = 0;
            StockPoolState.filteredStocks = [];
            updateStocksPagination();
        }
    } catch (error) {
        console.error('加载股票失败:', error);
        showToast('错误', '加载股票请求失败', 'danger');
        StockPoolState.stocksData = [];
        StockPoolState.stocksTotalCount = 0;
        StockPoolState.filteredStocks = [];
        updateStocksPagination();
    }
}

// ==================== 股票渲染 ====================

/**
 * 渲染股票表格
 */
function renderStocksTable(stocks = StockPoolState.filteredStocks) {
    const tbody = document.getElementById('stocks-table-body');

    if (stocks.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="4" class="text-center text-muted py-3">
                    <i class="fas fa-info-circle"></i> 暂无股票数据
                </td>
            </tr>
        `;
        return;
    }

    try {
        const rows = stocks.map(stock => {
            const isManual = stock.is_manual || false;
            const stockPriority = stock.stock_priority || 0;
            const safeStockCode = (stock.code || '').replace(/'/g, "\\'");

            let rowClass = '';
            let priorityBadge = '';

            if (isManual) {
                rowClass = 'table-warning';
                if (stockPriority >= 90) {
                    priorityBadge = '<span class="badge bg-danger me-2" title="核心自选"><i class="fas fa-star"></i> 核心自选</span>';
                } else if (stockPriority >= 50) {
                    priorityBadge = '<span class="badge bg-warning text-dark me-2" title="重要自选"><i class="fas fa-star"></i> 重要自选</span>';
                } else {
                    priorityBadge = '<span class="badge bg-info me-2" title="自选股"><i class="fas fa-heart"></i> 自选</span>';
                }
            }

            return `
                <tr data-stock-code="${stock.code || ''}" class="${rowClass}" data-is-manual="${isManual}">
                    <td class="fw-bold">${stock.code || '-'}</td>
                    <td>
                        <div class="d-flex align-items-center">
                            ${priorityBadge}
                            <span class="stock-name">${stock.name || '-'}</span>
                        </div>
                    </td>
                    <td><small class="text-muted">${stock.plate_name || '-'}</small></td>
                    <td>
                        <div class="btn-group" role="group">
                            <button class="btn btn-sm btn-outline-danger"
                                    onclick="deleteStock(${stock.id}, '${safeStockCode}')"
                                    title="删除股票">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        }).join('');

        tbody.innerHTML = rows;
    } catch (error) {
        console.error('渲染股票表格失败:', error);
        tbody.innerHTML = `
            <tr>
                <td colspan="4" class="text-center text-danger py-3">
                    <i class="fas fa-exclamation-triangle"></i> 渲染数据失败，请刷新页面
                </td>
            </tr>
        `;
    }
}

// ==================== 股票操作 ====================

/**
 * 添加股票
 */
async function addStocks() {
    const stockCodesInput = document.getElementById('stock-codes-input');
    const stockCodesText = stockCodesInput.value.trim();
    
    if (!stockCodesText) {
        showToast('警告', '请输入股票代码', 'warning');
        return;
    }
    
    const stockCodes = stockCodesText.split(',').map(code => code.trim()).filter(code => code);
    
    if (stockCodes.length === 0) {
        showToast('警告', '请输入有效的股票代码', 'warning');
        return;
    }
    
    try {
        showLoading(`添加 ${stockCodes.length} 只股票中...`);
        const response = await fetch('/api/stocks/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ stock_codes: stockCodes })
        });
        
        const result = await response.json();
        
        if (result.success) {
            stockCodesInput.value = '';
            await loadPageData();
            
            if (result.data.added_count > 0) {
                showToast('成功', `成功添加 ${result.data.added_count} 只股票`, 'success');
            }
            
            if (result.data.failed_codes && result.data.failed_codes.length > 0) {
                showToast('警告', `部分股票添加失败: ${result.data.failed_codes.join(', ')}`, 'warning');
            }
        } else {
            showToast('错误', `添加股票失败: ${result.message || '未知错误'}`, 'danger');
        }
    } catch (error) {
        console.error('添加股票失败:', error);
        showToast('错误', '添加股票请求失败', 'danger');
    } finally {
        hideLoading();
    }
}

/**
 * 删除股票
 */
function deleteStock(stockId, stockCode) {
    StockPoolState.currentDeleteAction = {
        type: 'stock',
        id: stockId,
        code: stockCode
    };
    
    document.getElementById('delete-message').textContent = 
        `确定要删除股票 "${stockCode}" 吗？`;
    StockPoolState.deleteModal.show();
}

// ==================== 股票筛选 ====================

/**
 * 筛选股票
 */
function filterStocks() {
    const searchText = document.getElementById('search-stocks').value.toLowerCase();
    const plateFilter = document.getElementById('plate-filter').value;
    const marketFilter = document.getElementById('stock-market-filter').value;
    
    StockPoolState.filteredStocks = StockPoolState.stocksData.filter(stock => {
        const searchMatch = !searchText || 
                           stock.code.toLowerCase().includes(searchText) ||
                           (stock.name && stock.name.toLowerCase().includes(searchText));
        
        const plateMatch = !plateFilter || stock.plate_id == plateFilter;
        const marketMatch = !marketFilter || stock.market === marketFilter;
        
        return searchMatch && plateMatch && marketMatch;
    });
    
    StockPoolState.stocksPagination.currentPage = 1;
    updateStocksPagination();
}

// ==================== 统计数据 ====================

/**
 * 更新统计数据
 */
function updateStatistics() {
    const enabledTargetPlates = StockPoolState.platesData.filter(plate => plate.is_target && plate.is_enabled !== false);
    const totalPlates = enabledTargetPlates.length;
    const totalStocks = StockPoolState.stocksTotalCount || StockPoolState.stocksData.length;
    
    const manualStocks = StockPoolState.stocksData.filter(stock => stock.is_manual === true || stock.is_manual === 1);
    const manualStocksCount = manualStocks.length;
    const plateStocksCount = Math.max(0, totalStocks - manualStocksCount);
    
    document.getElementById('total-plates').textContent = totalPlates;
    document.getElementById('total-stocks').textContent = totalStocks;
    document.getElementById('manual-stocks').textContent = manualStocksCount;
    document.getElementById('plate-stocks').textContent = plateStocksCount;
    
    console.log(`统计更新: 启用板块${totalPlates}个, 总股票${totalStocks}只, 自选股${manualStocksCount}只`);
}

/**
 * 更新筛选后的统计信息
 */
function updateFilteredStatistics() {
    const totalStocksElement = document.getElementById('total-stocks');
    if (totalStocksElement && StockPoolState.filteredStocks.length !== StockPoolState.stocksData.length) {
        totalStocksElement.innerHTML = `<span class="text-primary">${StockPoolState.filteredStocks.length}</span><small class="text-muted">/${StockPoolState.stocksTotalCount}</small>`;
    } else {
        totalStocksElement.textContent = StockPoolState.stocksTotalCount || StockPoolState.stocksData.length;
    }
}

// ==================== 删除确认 ====================

/**
 * 执行删除操作
 */
async function executeDelete() {
    if (!StockPoolState.currentDeleteAction) return;
    
    const { type, id, name, code } = StockPoolState.currentDeleteAction;
    
    try {
        showLoading(`删除${type === 'plate' ? '板块' : '股票'}中...`);
        
        const endpoint = type === 'plate' ? `/api/plates/${id}` : `/api/stocks/${id}`;
        const response = await fetch(endpoint, { method: 'DELETE' });
        const result = await response.json();
        
        if (result.success) {
            StockPoolState.deleteModal.hide();
            await loadPageData();
            showToast('成功', `${type === 'plate' ? '板块' : '股票'} "${name || code}" 已删除`, 'success');
        } else {
            showToast('错误', `删除失败: ${result.message || '未知错误'}`, 'danger');
        }
    } catch (error) {
        console.error('删除失败:', error);
        showToast('错误', '删除请求失败', 'danger');
    } finally {
        hideLoading();
        StockPoolState.currentDeleteAction = null;
    }
}

/**
 * 刷新所有数据
 */
async function refreshAllData() {
    try {
        showLoading('刷新数据中...');
        
        const response = await fetch('/api/refresh', { method: 'POST' });
        const result = await response.json();
        
        if (result.success) {
            await loadPageData();
            showToast('成功', '数据刷新成功', 'success');
        } else {
            showToast('错误', `数据刷新失败: ${result.message}`, 'danger');
        }
    } catch (error) {
        console.error('刷新数据失败:', error);
        showToast('错误', '刷新数据请求失败', 'danger');
    } finally {
        hideLoading();
    }
}

// ==================== 导出到全局 ====================
window.loadStocks = loadStocks;
window.loadStocksInternal = loadStocksInternal;
window.renderStocksTable = renderStocksTable;
window.addStocks = addStocks;
window.deleteStock = deleteStock;
window.filterStocks = filterStocks;
window.updateStatistics = updateStatistics;
window.updateFilteredStatistics = updateFilteredStatistics;
window.executeDelete = executeDelete;
window.refreshAllData = refreshAllData;
