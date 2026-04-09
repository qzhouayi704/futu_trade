/**
 * 股票池管理 - 分页模块
 * 功能：板块和股票的分页逻辑
 * 
 * 依赖：StockPoolState (全局状态对象)
 */

// ==================== 分页事件绑定 ====================

/**
 * 绑定分页相关事件
 */
function bindPaginationEvents() {
    const platesPageSize = document.getElementById('plates-page-size');
    if (platesPageSize) {
        platesPageSize.addEventListener('change', function() {
            StockPoolState.platesPagination.pageSize = parseInt(this.value);
            StockPoolState.platesPagination.currentPage = 1;
            updatePlatesPagination();
        });
    }
    
    const stocksPageSize = document.getElementById('stocks-page-size');
    if (stocksPageSize) {
        stocksPageSize.addEventListener('change', function() {
            StockPoolState.stocksPagination.pageSize = parseInt(this.value);
            StockPoolState.stocksPagination.currentPage = 1;
            updateStocksPagination();
        });
    }
}

// ==================== 板块分页 ====================

/**
 * 更新板块分页
 */
function updatePlatesPagination() {
    const pagination = StockPoolState.platesPagination;
    pagination.filteredData = StockPoolState.filteredPlates;
    pagination.totalItems = pagination.filteredData.length;
    
    const totalPages = Math.ceil(pagination.totalItems / pagination.pageSize);
    pagination.currentPage = Math.min(pagination.currentPage, Math.max(1, totalPages));
    
    const startIndex = (pagination.currentPage - 1) * pagination.pageSize;
    const endIndex = startIndex + pagination.pageSize;
    const pageData = pagination.filteredData.slice(startIndex, endIndex);
    
    renderPlatesTable(pageData);
    renderPlatesPagination(totalPages);
    updatePlatesPaginationInfo();
    
    const container = document.getElementById('plates-pagination-container');
    if (container) {
        container.style.display = pagination.totalItems > pagination.pageSize ? 'flex' : 'none';
    }
}

/**
 * 渲染板块分页导航
 */
function renderPlatesPagination(totalPages) {
    const pagination = document.getElementById('plates-pagination');
    if (!pagination) return;
    
    const currentPage = StockPoolState.platesPagination.currentPage;
    let html = '';
    
    html += `
        <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="goToPlatesPage(${currentPage - 1})" aria-label="上一页">
                <span aria-hidden="true">&laquo;</span>
            </a>
        </li>
    `;
    
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);
    
    if (startPage > 1) {
        html += `<li class="page-item"><a class="page-link" href="#" onclick="goToPlatesPage(1)">1</a></li>`;
        if (startPage > 2) {
            html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        }
    }
    
    for (let i = startPage; i <= endPage; i++) {
        html += `
            <li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#" onclick="goToPlatesPage(${i})">${i}</a>
            </li>
        `;
    }
    
    if (endPage < totalPages) {
        if (endPage < totalPages - 1) {
            html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        }
        html += `<li class="page-item"><a class="page-link" href="#" onclick="goToPlatesPage(${totalPages})">${totalPages}</a></li>`;
    }
    
    html += `
        <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="goToPlatesPage(${currentPage + 1})" aria-label="下一页">
                <span aria-hidden="true">&raquo;</span>
            </a>
        </li>
    `;
    
    pagination.innerHTML = html;
}

/**
 * 更新板块分页信息
 */
function updatePlatesPaginationInfo() {
    const info = document.getElementById('plates-info');
    if (!info) return;
    
    const { currentPage, pageSize, totalItems } = StockPoolState.platesPagination;
    const startIndex = (currentPage - 1) * pageSize + 1;
    const endIndex = Math.min(currentPage * pageSize, totalItems);
    
    info.textContent = `显示第${startIndex}-${endIndex}条，共${totalItems}条记录`;
}

/**
 * 跳转到板块指定页
 */
function goToPlatesPage(page) {
    const totalPages = Math.ceil(StockPoolState.platesPagination.totalItems / StockPoolState.platesPagination.pageSize);
    StockPoolState.platesPagination.currentPage = Math.max(1, Math.min(page, totalPages));
    updatePlatesPagination();
}

// ==================== 股票分页 ====================

/**
 * 更新股票分页
 */
function updateStocksPagination() {
    const pagination = StockPoolState.stocksPagination;
    pagination.filteredData = StockPoolState.filteredStocks;
    pagination.totalItems = pagination.filteredData.length;
    
    const totalPages = Math.ceil(pagination.totalItems / pagination.pageSize);
    pagination.currentPage = Math.min(pagination.currentPage, Math.max(1, totalPages));
    
    const startIndex = (pagination.currentPage - 1) * pagination.pageSize;
    const endIndex = startIndex + pagination.pageSize;
    const pageData = pagination.filteredData.slice(startIndex, endIndex);
    
    renderStocksTable(pageData);
    renderStocksPagination(totalPages);
    updateStocksPaginationInfo();
    
    const container = document.getElementById('stocks-pagination-container');
    if (container) {
        container.style.display = pagination.totalItems > pagination.pageSize ? 'flex' : 'none';
    }
}

/**
 * 渲染股票分页导航
 */
function renderStocksPagination(totalPages) {
    const pagination = document.getElementById('stocks-pagination');
    if (!pagination) return;
    
    const currentPage = StockPoolState.stocksPagination.currentPage;
    let html = '';
    
    html += `
        <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="goToStocksPage(${currentPage - 1})" aria-label="上一页">
                <span aria-hidden="true">&laquo;</span>
            </a>
        </li>
    `;
    
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);
    
    if (startPage > 1) {
        html += `<li class="page-item"><a class="page-link" href="#" onclick="goToStocksPage(1)">1</a></li>`;
        if (startPage > 2) {
            html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        }
    }
    
    for (let i = startPage; i <= endPage; i++) {
        html += `
            <li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#" onclick="goToStocksPage(${i})">${i}</a>
            </li>
        `;
    }
    
    if (endPage < totalPages) {
        if (endPage < totalPages - 1) {
            html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        }
        html += `<li class="page-item"><a class="page-link" href="#" onclick="goToStocksPage(${totalPages})">${totalPages}</a></li>`;
    }
    
    html += `
        <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="goToStocksPage(${currentPage + 1})" aria-label="下一页">
                <span aria-hidden="true">&raquo;</span>
            </a>
        </li>
    `;
    
    pagination.innerHTML = html;
}

/**
 * 更新股票分页信息
 */
function updateStocksPaginationInfo() {
    const info = document.getElementById('stocks-info');
    if (!info) return;
    
    const { currentPage, pageSize, totalItems } = StockPoolState.stocksPagination;
    const startIndex = (currentPage - 1) * pageSize + 1;
    const endIndex = Math.min(currentPage * pageSize, totalItems);
    
    info.textContent = `显示第${startIndex}-${endIndex}条，共${totalItems}条记录`;
}

/**
 * 跳转到股票指定页
 */
function goToStocksPage(page) {
    const totalPages = Math.ceil(StockPoolState.stocksPagination.totalItems / StockPoolState.stocksPagination.pageSize);
    StockPoolState.stocksPagination.currentPage = Math.max(1, Math.min(page, totalPages));
    updateStocksPagination();
}

// ==================== 导出到全局 ====================
window.bindPaginationEvents = bindPaginationEvents;
window.updatePlatesPagination = updatePlatesPagination;
window.renderPlatesPagination = renderPlatesPagination;
window.updatePlatesPaginationInfo = updatePlatesPaginationInfo;
window.goToPlatesPage = goToPlatesPage;
window.updateStocksPagination = updateStocksPagination;
window.renderStocksPagination = renderStocksPagination;
window.updateStocksPaginationInfo = updateStocksPaginationInfo;
window.goToStocksPage = goToStocksPage;
