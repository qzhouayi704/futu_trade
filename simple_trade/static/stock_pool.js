/**
 * 股票池管理页面前端脚本 - 简化版本
 * 专注于板块和股票的增删功能
 */

// 全局变量
let loadingModal = null;
let deleteModal = null;
let browsePlatesModal = null;
let initProgressModal = null;
let currentDeleteAction = null;
let platesData = [];
let filteredPlates = [];  // 新增：板块筛选结果
let stocksData = [];
let filteredStocks = [];
let stocksTotalCount = 0;  // 新增：保存后端返回的股票真实总数
let availablePlatesData = [];
let filteredAvailablePlates = [];
let selectedPlates = new Set();
let loadingCounter = 0; // 加载计数器，用于管理并发加载状态

// 初始化进度相关变量
let progressPollInterval = null;
let initializationInProgress = false;

// 分页相关变量
let platesPagination = {
    currentPage: 1,
    pageSize: 20,
    totalItems: 0,
    filteredData: []
};

let stocksPagination = {
    currentPage: 1,
    pageSize: 20,
    totalItems: 0,
    filteredData: []
};

// 初始化
document.addEventListener('DOMContentLoaded', function() {
    initializeStockPoolPage();
});

/**
 * 初始化股票池管理页面
 */
function initializeStockPoolPage() {
    console.log('初始化股票池管理页面...');

    // 初始化模态框 - 添加防御性检查
    try {
        const loadingModalEl = document.getElementById('loadingModal');
        const deleteModalEl = document.getElementById('deleteModal');
        const browsePlatesModalEl = document.getElementById('browsePlatesModal');
        const initProgressModalEl = document.getElementById('initProgressModal');

        if (!loadingModalEl) {
            console.error('找不到 loadingModal 元素');
            return;
        }

        // 确保 Bootstrap 已加载
        if (typeof bootstrap === 'undefined') {
            console.error('Bootstrap 尚未加载');
            return;
        }

        loadingModal = new bootstrap.Modal(loadingModalEl);
        deleteModal = new bootstrap.Modal(deleteModalEl);
        browsePlatesModal = new bootstrap.Modal(browsePlatesModalEl);
        initProgressModal = new bootstrap.Modal(initProgressModalEl);

        console.log('模态框初始化成功');
    } catch (e) {
        console.error('模态框初始化失败:', e);
        return;
    }

    // 绑定事件
    bindEvents();

    // 直接加载数据，不等待初始化
    loadPageData();

    console.log('股票池管理页面初始化完成');
}

/**
 * 绑定事件
 */
function bindEvents() {
    // 板块管理事件
    document.getElementById('add-plate-btn').addEventListener('click', addPlate);
    document.getElementById('refresh-plates').addEventListener('click', loadPlates);
    document.getElementById('browse-plates-btn').addEventListener('click', browsePlates);
    document.getElementById('plate-code-input').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            addPlate();
        }
    });
    
    // 股票管理事件
    document.getElementById('add-stocks-btn').addEventListener('click', addStocks);
    document.getElementById('refresh-stocks').addEventListener('click', loadStocks);
    document.getElementById('stock-codes-input').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            addStocks();
        }
    });
    
    // 搜索和筛选事件
    document.getElementById('search-stocks').addEventListener('input', filterStocks);
    document.getElementById('plate-filter').addEventListener('change', filterStocks);
    document.getElementById('stock-market-filter').addEventListener('change', filterStocks);
    
    // 板块筛选事件
    document.getElementById('plate-market-filter').addEventListener('change', filterPlates);
    document.getElementById('plate-type-filter').addEventListener('change', filterPlates);
    
    // 优先级筛选事件（如果存在）
    const priorityFilter = document.getElementById('plate-priority-filter');
    if (priorityFilter) {
        priorityFilter.addEventListener('change', filterPlates);
    }
    
    // 删除确认事件
    document.getElementById('confirm-delete').addEventListener('click', executeDelete);
    
    // 浏览板块模态框事件
    document.getElementById('search-available-plates').addEventListener('input', searchAvailablePlates);
    document.getElementById('market-filter').addEventListener('change', filterAvailablePlates);
    document.getElementById('status-filter-modal').addEventListener('change', filterAvailablePlates);
    document.getElementById('select-all-plates').addEventListener('click', selectAllPlates);
    document.getElementById('deselect-all-plates').addEventListener('click', deselectAllPlates);
    document.getElementById('select-tech-plates').addEventListener('click', selectTechPlates);
    document.getElementById('select-medical-plates').addEventListener('click', selectMedicalPlates);
    document.getElementById('confirm-batch-add').addEventListener('click', batchAddPlates);
    document.getElementById('select-all-checkbox').addEventListener('change', toggleAllPlates);
    
    // 刷新数据按钮（如果存在）
    const refreshBtn = document.getElementById('refresh-data-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', refreshAllData);
    }
    
    // 初始化股票池按钮
    const manualInitBtn = document.getElementById('manual-init-btn');
    if (manualInitBtn) {
        manualInitBtn.addEventListener('click', manualInitStockPool);
    }
    
    // 进度条模态框事件
    const initCancelBtn = document.getElementById('init-cancel-btn');
    if (initCancelBtn) {
        initCancelBtn.addEventListener('click', cancelInitialization);
    }
    
    const initRetryBtn = document.getElementById('init-retry-btn');
    if (initRetryBtn) {
        initRetryBtn.addEventListener('click', retryInitialization);
    }
    
    const initCompleteBtn = document.getElementById('init-complete-btn');
    if (initCompleteBtn) {
        initCompleteBtn.addEventListener('click', () => {
            initProgressModal.hide();
        });
    }
    
    // 分页相关事件
    bindPaginationEvents();
}

/**
 * 加载页面数据
 */
async function loadPageData() {
    console.log('[loadPageData] 开始加载页面数据');
    try {
        showLoading('加载数据中...');
        console.log('[loadPageData] 已调用 showLoading, loadingCounter:', loadingCounter);

        // 使用内部版本，不显示loading
        await Promise.all([loadPlatesInternal(), loadStocksInternal()]);
        console.log('[loadPageData] 数据加载完成');

        updateStatistics();
        console.log('[loadPageData] 统计信息更新完成');
    } catch (error) {
        console.error('[loadPageData] 加载页面数据失败:', error);
        showToast('错误', '加载页面数据失败', 'danger');
    } finally {
        console.log('[loadPageData] finally块执行，准备调用 hideLoading, loadingCounter:', loadingCounter);
        hideLoading();
        console.log('[loadPageData] hideLoading 调用完成, loadingCounter:', loadingCounter);
    }
}

// ==================== 板块管理功能 ====================

/**
 * 加载板块列表（带loading）
 */
async function loadPlates() {
    try {
        showLoading('加载板块数据...');
        await loadPlatesInternal();
    } finally {
        hideLoading();
    }
}

/**
 * 加载板块列表（内部版本，不显示loading）
 */
async function loadPlatesInternal() {
    try {
        const response = await fetch('/api/data?type=plates&limit=1000');
        const result = await response.json();
        
        if (result.success) {
            platesData = result.data;
            filteredPlates = platesData;  // 初始化筛选结果为全部数据
            updatePlatesPagination(); // 使用分页渲染
            updatePlateFilter();
            console.log(`已加载 ${platesData.length} 个板块`);
        } else {
            showToast('错误', `加载板块失败: ${result.message || '未知错误'}`, 'danger');
            platesData = [];
            filteredPlates = [];
            updatePlatesPagination(); // 显示空表格
        }
    } catch (error) {
        console.error('加载板块失败:', error);
        showToast('错误', '加载板块请求失败', 'danger');
        platesData = [];
        filteredPlates = [];
        updatePlatesPagination(); // 显示空表格
    }
}

/**
 * 渲染板块表格
 */
function renderPlatesTable(plates = platesData) {
    const tbody = document.getElementById('plates-table-body');

    if (plates.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="text-center text-muted py-3">
                    <i class="fas fa-info-circle"></i> 暂无板块数据
                </td>
            </tr>
        `;
        return;
    }

    try {
        const rows = plates.map(plate => {
            const isTarget = plate.is_target;
            const isEnabled = plate.is_enabled !== undefined ? plate.is_enabled : true;
            const priority = plate.priority || 0;
            const safePlateName = (plate.plate_name || '').replace(/'/g, "\\'");

            // 根据优先级确定行样式和优先级标识
            let rowClass = '';
            let priorityBadge = '';

            if (priority >= 80) {
                rowClass = 'table-danger';
                priorityBadge = '<span class="badge bg-danger me-2" title="核心板块 - 最高优先级"><i class="fas fa-crown"></i> 核心</span>';
            } else if (priority >= 50) {
                rowClass = 'table-warning';
                priorityBadge = '<span class="badge bg-warning text-dark me-2" title="重要板块 - 中等优先级"><i class="fas fa-star"></i> 重要</span>';
            } else if (priority > 0) {
                priorityBadge = '<span class="badge bg-info me-2" title="一般板块 - 低优先级"><i class="fas fa-circle"></i> 一般</span>';
            } else {
                priorityBadge = '<span class="badge bg-secondary me-2" title="普通板块 - 无优先级"><i class="fas fa-minus"></i> 普通</span>';
            }

            const targetBadge = isTarget
                ? '<span class="badge bg-success me-1" title="目标板块"><i class="fas fa-check"></i> 目标</span>'
                : '';

            return `
                <tr class="${rowClass}" data-plate-id="${plate.id}" data-priority="${priority}">
                    <td class="fw-bold text-nowrap">${plate.plate_code || '-'}</td>
                    <td>
                        <div class="d-flex flex-wrap align-items-center">
                            ${priorityBadge}
                            ${targetBadge}
                            <span class="plate-name">${plate.plate_name || '-'}</span>
                        </div>
                    </td>
                    <td>
                        <span class="badge bg-primary">${plate.market || '-'}</span>
                    </td>
                    <td class="text-center">
                        <span class="badge bg-info fs-6">${plate.stock_count || 0}</span>
                    </td>
                    <td class="text-center priority-cell">
                        <div class="d-flex align-items-center justify-content-center">
                            <span class="priority-value fw-bold fs-5 me-2"
                                  style="color: ${priority >= 80 ? '#dc3545' : priority >= 50 ? '#ffc107' : priority > 0 ? '#0dcaf0' : '#6c757d'};">
                                ${priority}
                            </span>
                            <button class="btn btn-sm btn-outline-primary edit-priority-btn"
                                    onclick="showPriorityEditModal(${plate.id}, ${priority}, '${safePlateName}')"
                                    title="编辑优先级">
                                <i class="fas fa-edit"></i>
                            </button>
                        </div>
                    </td>
                    <td class="text-center">
                        <div class="d-flex align-items-center justify-content-center gap-2">
                            <div class="form-check form-switch mb-0" title="${isEnabled ? '已启用 - 点击禁用' : '已禁用 - 点击启用'}">
                                <input type="checkbox" class="form-check-input" role="switch"
                                       id="plate-switch-${plate.id}"
                                       ${isEnabled ? 'checked' : ''}
                                       onchange="togglePlateStatus(${plate.id}, ${isEnabled}, '${safePlateName}')">
                                <label class="form-check-label small ${isEnabled ? 'text-primary' : 'text-muted'}"
                                       for="plate-switch-${plate.id}">
                                    ${isEnabled ? '启用' : '禁用'}
                                </label>
                            </div>
                            <button class="btn btn-sm btn-outline-danger"
                                    onclick="deletePlate(${plate.id}, '${safePlateName}')"
                                    title="删除板块">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        }).join('');

        tbody.innerHTML = rows;
    } catch (error) {
        console.error('渲染板块表格失败:', error);
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="text-center text-danger py-3">
                    <i class="fas fa-exclamation-triangle"></i> 渲染数据失败，请刷新页面
                </td>
            </tr>
        `;
    }
}

/**
 * 切换板块启用/禁用状态
 */
async function togglePlateStatus(plateId, currentStatus, plateName) {
    const action = currentStatus ? '禁用' : '启用';
    const newStatus = !currentStatus;
    
    if (!confirm(`确定要${action}板块 "${plateName}" 吗？\n${action}后会影响股票列表显示。`)) {
        // 用户取消，恢复开关状态
        const switchEl = document.getElementById(`plate-switch-${plateId}`);
        if (switchEl) {
            switchEl.checked = currentStatus;
        }
        return;
    }
    
    try {
        showLoading(`${action}板块中...`);
        
        const response = await fetch(`/api/plates/${plateId}/toggle`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const result = await response.json();
        
        if (result.success) {
            // 更新本地板块数据
            const plateIndex = platesData.findIndex(p => p.id === plateId);
            if (plateIndex !== -1) {
                platesData[plateIndex].is_enabled = newStatus;
            }
            
            // 重新渲染板块表格
            updatePlatesPagination();
            
            // 重新加载股票数据（因为禁用/启用板块会影响股票列表）
            await loadStocks();
            
            // 更新统计数据
            updateStatistics();
            
            showToast('成功', result.message, 'success');
        } else {
            // 失败时恢复开关状态
            const switchEl = document.getElementById(`plate-switch-${plateId}`);
            if (switchEl) {
                switchEl.checked = currentStatus;
            }
            showToast('错误', `${action}板块失败: ${result.message}`, 'danger');
        }
    } catch (error) {
        console.error(`${action}板块失败:`, error);
        // 失败时恢复开关状态
        const switchEl = document.getElementById(`plate-switch-${plateId}`);
        if (switchEl) {
            switchEl.checked = currentStatus;
        }
        showToast('错误', `${action}板块请求失败`, 'danger');
    } finally {
        hideLoading();
    }
}

/**
 * 添加板块
 */
async function addPlate() {
    const plateCodeInput = document.getElementById('plate-code-input');
    const plateCode = plateCodeInput.value.trim();
    
    if (!plateCode) {
        showToast('警告', '请输入板块代码', 'warning');
        return;
    }
    
    // 基本格式验证
    if (!plateCode.match(/^[A-Z]{2}\d+$/)) {
        showToast('警告', '板块代码格式不正确，应为类似 BK1027 的格式', 'warning');
        return;
    }
    
    try {
        showLoading('添加板块中...');
        const response = await fetch('/api/plates/add', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ plate_code: plateCode })
        });
        
        const result = await response.json();
        
        if (result.success) {
            plateCodeInput.value = '';
            await loadPageData(); // 重新加载所有数据
            showToast('成功', `板块 ${plateCode} 添加成功`, 'success');
        } else {
            showToast('错误', `添加板块失败: ${result.message || '未知错误'}`, 'danger');
        }
    } catch (error) {
        console.error('添加板块失败:', error);
        showToast('错误', '添加板块请求失败', 'danger');
    } finally {
        hideLoading();
    }
}

/**
 * 删除板块
 */
function deletePlate(plateId, plateName) {
    currentDeleteAction = {
        type: 'plate',
        id: plateId,
        name: plateName
    };
    
    document.getElementById('delete-message').textContent = 
        `确定要删除板块 "${plateName}" 吗？这将同时删除该板块下的所有股票！`;
    deleteModal.show();
}

// ==================== 股票管理功能 ====================

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
 * 加载股票列表（内部版本，不显示loading）
 * 修复：将limit从1000增加到5000，确保能加载所有股票数据
 */
async function loadStocksInternal() {
    try {
        const response = await fetch('/api/data?type=stocks&limit=5000');
        const result = await response.json();
        
        if (result.success) {
            stocksData = result.data;
            // 使用后端返回的真实总数（从meta.total获取），如果没有则使用数据长度
            stocksTotalCount = result.meta?.total || result.data.length;
            filteredStocks = stocksData;
            updateStocksPagination(); // 使用分页渲染
            console.log(`已加载 ${stocksData.length} 只股票（总数: ${stocksTotalCount}）`);
        } else {
            showToast('错误', `加载股票失败: ${result.message || '未知错误'}`, 'danger');
            stocksData = [];
            stocksTotalCount = 0;
            filteredStocks = [];
            updateStocksPagination(); // 显示空表格
        }
    } catch (error) {
        console.error('加载股票失败:', error);
        showToast('错误', '加载股票请求失败', 'danger');
        stocksData = [];
        stocksTotalCount = 0;
        filteredStocks = [];
        updateStocksPagination(); // 显示空表格
    }
}

/**
 * 渲染股票表格 - 支持自选股显示
 */
function renderStocksTable(stocks = filteredStocks) {
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

            // 根据自选股状态设置行样式和标识
            let rowClass = '';
            let priorityBadge = '';

            if (isManual) {
                rowClass = 'table-warning';
                if (stockPriority >= 90) {
                    priorityBadge = '<span class="badge bg-danger me-2" title="自选股 - 最高优先级"><i class="fas fa-star"></i> 核心自选</span>';
                } else if (stockPriority >= 50) {
                    priorityBadge = '<span class="badge bg-warning text-dark me-2" title="自选股 - 重要"><i class="fas fa-star"></i> 重要自选</span>';
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
    
    // 解析股票代码（支持逗号分隔）
    const stockCodes = stockCodesText.split(',').map(code => code.trim()).filter(code => code);
    
    if (stockCodes.length === 0) {
        showToast('警告', '请输入有效的股票代码', 'warning');
        return;
    }
    
    try {
        showLoading(`添加 ${stockCodes.length} 只股票中...`);
        const response = await fetch('/api/stocks/add', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ stock_codes: stockCodes })
        });
        
        const result = await response.json();
        
        if (result.success) {
            stockCodesInput.value = '';
            await loadPageData(); // 重新加载所有数据
            
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
    currentDeleteAction = {
        type: 'stock',
        id: stockId,
        code: stockCode
    };
    
    document.getElementById('delete-message').textContent = 
        `确定要删除股票 "${stockCode}" 吗？`;
    deleteModal.show();
}

// ==================== 搜索和筛选功能 ====================

/**
 * 筛选板块 - 修复版本
 * 使用全局变量 filteredPlates 存储筛选结果
 */
function filterPlates() {
    const marketFilter = document.getElementById('plate-market-filter').value;
    const typeFilter = document.getElementById('plate-type-filter').value;
    const priorityFilter = document.getElementById('plate-priority-filter')?.value || '';
    
    console.log('板块筛选条件 - 市场:', marketFilter, '类型:', typeFilter, '优先级:', priorityFilter);
    
    // 使用全局变量存储筛选结果
    filteredPlates = platesData.filter(plate => {
        // 市场过滤
        const marketMatch = !marketFilter || plate.market === marketFilter;
        
        // 类型过滤
        let typeMatch = true;
        if (typeFilter === 'target') {
            typeMatch = plate.is_target;
        } else if (typeFilter === 'normal') {
            typeMatch = !plate.is_target;
        }
        
        // 优先级过滤
        let priorityMatch = true;
        const priority = plate.priority || 0;
        if (priorityFilter === 'high') {
            priorityMatch = priority >= 80;
        } else if (priorityFilter === 'medium') {
            priorityMatch = priority >= 50 && priority < 80;
        } else if (priorityFilter === 'low') {
            priorityMatch = priority > 0 && priority < 50;
        } else if (priorityFilter === 'normal') {
            priorityMatch = priority === 0;
        }
        
        return marketMatch && typeMatch && priorityMatch;
    });
    
    console.log('板块筛选结果:', filteredPlates.length, '个板块');
    
    // 重置到第一页
    platesPagination.currentPage = 1;
    updatePlatesPagination();
}

/**
 * 筛选股票
 */
function filterStocks() {
    const searchText = document.getElementById('search-stocks').value.toLowerCase();
    const plateFilter = document.getElementById('plate-filter').value;
    const marketFilter = document.getElementById('stock-market-filter').value;
    
    filteredStocks = stocksData.filter(stock => {
        // 搜索过滤
        const searchMatch = !searchText || 
                           stock.code.toLowerCase().includes(searchText) ||
                           (stock.name && stock.name.toLowerCase().includes(searchText));
        
        // 板块过滤
        const plateMatch = !plateFilter || stock.plate_id == plateFilter;
        
        // 市场过滤
        const marketMatch = !marketFilter || stock.market === marketFilter;
        
        return searchMatch && plateMatch && marketMatch;
    });
    
    // 重置到第一页
    stocksPagination.currentPage = 1;
    updateStocksPagination();
}

/**
 * 更新板块筛选器
 */
function updatePlateFilter() {
    const plateFilter = document.getElementById('plate-filter');
    const currentValue = plateFilter.value;
    
    // 清空现有选项（保留"所有板块"）
    plateFilter.innerHTML = '<option value="">所有板块</option>';
    
    // 添加板块选项
    platesData.forEach(plate => {
        const option = document.createElement('option');
        option.value = plate.id;
        option.textContent = `${plate.plate_code} - ${plate.plate_name}`;
        plateFilter.appendChild(option);
    });
    
    // 恢复之前的选择
    plateFilter.value = currentValue;
}

// ==================== 统计数据更新 ====================

/**
 * 更新筛选后的统计信息
 * 在筛选操作后调用，更新显示当前筛选结果的数量
 */
function updateFilteredStatistics() {
    // 更新股票分页信息，显示当前筛选后的数量
    const totalStocksElement = document.getElementById('total-stocks');
    if (totalStocksElement && filteredStocks.length !== stocksData.length) {
        // 如果有筛选，显示筛选后的数量和总数
        totalStocksElement.innerHTML = `<span class="text-primary">${filteredStocks.length}</span><small class="text-muted">/${stocksTotalCount}</small>`;
    } else {
        // 没有筛选，只显示总数
        totalStocksElement.textContent = stocksTotalCount || stocksData.length;
    }
}

/**
 * 更新统计数据 - 统计目标板块、相关股票和自选股
 * 修复：使用后端返回的真实总数，而不是前端加载的数据条数
 */
function updateStatistics() {
    // 计算目标板块数量（只统计启用的板块）
    const targetPlates = platesData.filter(plate => plate.is_target);
    const enabledTargetPlates = platesData.filter(plate => plate.is_target && plate.is_enabled !== false);
    const totalPlates = enabledTargetPlates.length;
    
    // 使用后端返回的真实股票总数（stocksTotalCount），而不是前端加载的数据条数
    // 这样可以正确反映禁用板块后股票数量的变化
    const totalStocks = stocksTotalCount || stocksData.length;
    
    // 计算自选股数量 - 包括所有标记为手动添加的股票
    const manualStocks = stocksData.filter(stock => stock.is_manual === true || stock.is_manual === 1);
    const manualStocksCount = manualStocks.length;
    
    // 计算板块股票数量（总数减去自选股数量）
    const plateStocksCount = Math.max(0, totalStocks - manualStocksCount);
    
    // 更新显示
    document.getElementById('total-plates').textContent = totalPlates;
    document.getElementById('total-stocks').textContent = totalStocks;
    document.getElementById('manual-stocks').textContent = manualStocksCount;
    document.getElementById('plate-stocks').textContent = plateStocksCount;
    
    console.log(`统计更新: 启用板块${totalPlates}个, 总股票${totalStocks}只, 自选股${manualStocksCount}只, 板块股票${plateStocksCount}只`);
}

// ==================== 删除确认处理 ====================

/**
 * 执行删除操作
 */
async function executeDelete() {
    if (!currentDeleteAction) {
        return;
    }
    
    const { type, id, name, code } = currentDeleteAction;
    
    try {
        showLoading(`删除${type === 'plate' ? '板块' : '股票'}中...`);
        
        const endpoint = type === 'plate' ? `/api/plates/${id}` : `/api/stocks/${id}`;
        const response = await fetch(endpoint, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        if (result.success) {
            deleteModal.hide();
            
            // 重新加载数据
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
        currentDeleteAction = null;
    }
}

// ==================== 数据刷新功能 ====================

/**
 * 刷新所有数据
 */
async function refreshAllData() {
    try {
        showLoading('刷新数据中...');
        
        // 调用后端刷新接口
        const response = await fetch('/api/stocks/refresh', {
            method: 'POST'
        });
        
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

/**
 * 手动初始化股票池 - 带进度条显示
 */
async function manualInitStockPool() {
    if (initializationInProgress) {
        showToast('警告', '初始化正在进行中，请稍候...', 'warning');
        return;
    }

    try {
        initializationInProgress = true;
        
        // 重置进度条状态
        resetInitProgressModal();
        
        // 显示进度条模态框
        initProgressModal.show();
        
        // 启动初始化
        const response = await fetch('/api/init', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ force_refresh: true })
        });
        
        const result = await response.json();
        
        if (result.success) {
            // 开始轮询进度
            startProgressPolling();
        } else {
            // 初始化启动失败
            showInitError(result.message || '初始化启动失败');
        }
    } catch (error) {
        console.error('启动初始化失败:', error);
        showInitError('启动初始化请求失败');
    }
}

/**
 * 重置进度模态框状态
 */
function resetInitProgressModal() {
    // 重置进度条
    updateProgressBar(0);
    
    // 重置文本
    document.getElementById('init-current-action').textContent = '准备初始化...';
    document.getElementById('init-current-step').textContent = '0';
    document.getElementById('init-total-steps').textContent = '0';
    
    // 隐藏成功/错误信息
    document.getElementById('init-success-alert').style.display = 'none';
    document.getElementById('init-error-alert').style.display = 'none';
    
    // 显示取消按钮，隐藏完成/重试按钮
    document.getElementById('init-cancel-btn').style.display = 'block';
    document.getElementById('init-complete-btn').style.display = 'none';
    document.getElementById('init-retry-btn').style.display = 'none';
}

/**
 * 开始进度轮询
 */
function startProgressPolling() {
    // 清除现有的轮询定时器
    if (progressPollInterval) {
        clearInterval(progressPollInterval);
    }
    
    // 开始轮询进度
    progressPollInterval = setInterval(async () => {
        try {
            const response = await fetch('/api/init/progress');
            const result = await response.json();
            
            if (result.success) {
                const progress = result.data;
                updateProgressDisplay(progress);
                
                // 检查是否完成
                if (progress.completed) {
                    stopProgressPolling();
                    handleInitializationComplete(progress);
                }
            }
        } catch (error) {
            console.error('获取进度失败:', error);
            // 继续轮询，不中断
        }
    }, 1000); // 每秒轮询一次
}

/**
 * 停止进度轮询
 */
function stopProgressPolling() {
    if (progressPollInterval) {
        clearInterval(progressPollInterval);
        progressPollInterval = null;
    }
}

/**
 * 更新进度显示
 */
function updateProgressDisplay(progress) {
    // 更新进度条
    updateProgressBar(progress.progress_percentage);
    
    // 更新当前操作文本
    document.getElementById('init-current-action').textContent = progress.current_action || '处理中...';
    
    // 更新步骤信息
    document.getElementById('init-current-step').textContent = progress.current_step || 0;
    document.getElementById('init-total-steps').textContent = progress.total_steps || 0;
}

/**
 * 更新进度条
 */
function updateProgressBar(percentage) {
    const progressBar = document.getElementById('init-progress-bar');
    const progressText = document.getElementById('init-progress-percentage');
    
    const safePercentage = Math.max(0, Math.min(100, percentage || 0));
    
    progressBar.style.width = `${safePercentage}%`;
    progressBar.setAttribute('aria-valuenow', safePercentage);
    progressText.textContent = safePercentage;
}

/**
 * 处理初始化完成
 */
async function handleInitializationComplete(progress) {
    initializationInProgress = false;
    
    if (progress.error) {
        // 初始化失败
        showInitError(progress.error);
    } else {
        // 初始化成功
        await showInitSuccess();
    }
}

/**
 * 显示初始化成功
 */
async function showInitSuccess() {
    try {
        // 重新加载页面数据
        await loadPageData();
        
        // 获取最新的统计数据
        const platesCount = platesData.length;
        const stocksCount = stocksData.length;
        
        // 更新成功信息
        document.getElementById('init-plates-count').textContent = platesCount;
        document.getElementById('init-stocks-count').textContent = stocksCount;
        
        // 显示成功alert
        document.getElementById('init-success-alert').style.display = 'block';
        
        // 隐藏取消按钮，显示完成按钮
        document.getElementById('init-cancel-btn').style.display = 'none';
        document.getElementById('init-complete-btn').style.display = 'block';
        
        // 自动显示toast
        showToast('成功', 
            `股票池初始化完成！获取了 ${platesCount} 个板块和 ${stocksCount} 只股票`, 
            'success'
        );
    } catch (error) {
        console.error('加载初始化后数据失败:', error);
        showInitError('初始化完成但数据加载失败');
    }
}

/**
 * 显示初始化错误
 */
function showInitError(errorMessage) {
    initializationInProgress = false;
    
    // 停止轮询
    stopProgressPolling();
    
    // 更新错误信息
    document.getElementById('init-error-message').textContent = errorMessage;
    
    // 显示错误alert
    document.getElementById('init-error-alert').style.display = 'block';
    
    // 隐藏取消按钮，显示重试按钮
    document.getElementById('init-cancel-btn').style.display = 'none';
    document.getElementById('init-retry-btn').style.display = 'block';
    
    // 显示toast错误
    showToast('错误', `股票池初始化失败: ${errorMessage}`, 'danger');
}

/**
 * 取消初始化
 */
function cancelInitialization() {
    // 停止进度轮询
    stopProgressPolling();
    
    // 重置状态
    initializationInProgress = false;
    
    // 隐藏进度模态框
    initProgressModal.hide();
    
    // 显示取消消息
    showToast('信息', '股票池初始化已取消', 'info');
}

/**
 * 重试初始化
 */
function retryInitialization() {
    // 重新启动初始化
    manualInitStockPool();
}

// ==================== 工具函数 ====================

/**
 * 显示加载中 - 支持并发加载管理
 */
function showLoading(message = '处理中，请稍候...') {
    loadingCounter++;
    document.getElementById('loading-message').textContent = message;
    
    // 只有第一次调用时才显示模态框
    if (loadingCounter === 1) {
        loadingModal.show();
    } else {
        // 更新现有加载框的消息
        document.getElementById('loading-message').textContent = message;
    }
    
    console.log(`showLoading: ${message}, counter: ${loadingCounter}`);
}

/**
 * 隐藏加载中 - 支持并发加载管理
 * 增强版：使用事件监听确保Bootstrap动画完成后再清理
 */
function hideLoading() {
    loadingCounter = Math.max(0, loadingCounter - 1);
    console.log(`hideLoading: counter: ${loadingCounter}`);

    // 只有当所有加载操作完成时才隐藏模态框
    if (loadingCounter === 0) {
        console.log('[hideLoading] 开始隐藏模态框');

        const modalElement = document.getElementById('loadingModal');
        if (!modalElement) {
            console.log('[hideLoading] 模态框元素不存在');
            return;
        }

        // 设置超时强制隐藏（防止动画卡住）
        const forceHideTimeout = setTimeout(() => {
            console.log('[hideLoading] 超时，执行强制隐藏');
            forceHideModal(modalElement);
        }, 500);

        // 监听 hidden 事件，动画完成后清除超时
        const hiddenHandler = () => {
            console.log('[hideLoading] Bootstrap hidden 事件触发');
            clearTimeout(forceHideTimeout);
            modalElement.removeEventListener('hidden.bs.modal', hiddenHandler);
            // 确保清理干净
            cleanupModalState();
        };

        modalElement.addEventListener('hidden.bs.modal', hiddenHandler);

        // 调用 Bootstrap hide
        try {
            if (loadingModal) {
                loadingModal.hide();
                console.log('[hideLoading] loadingModal.hide() 调用完成');
            }
        } catch (e) {
            console.error('[hideLoading] loadingModal.hide() 失败:', e);
            clearTimeout(forceHideTimeout);
            forceHideModal(modalElement);
        }
    }
}

/**
 * 强制隐藏模态框
 */
function forceHideModal(modalElement) {
    try {
        modalElement.classList.remove('show');
        modalElement.style.display = 'none';
        modalElement.setAttribute('aria-hidden', 'true');
        cleanupModalState();
        console.log('[forceHideModal] 强制隐藏完成');
    } catch (e) {
        console.error('[forceHideModal] 强制隐藏失败:', e);
    }
}

/**
 * 清理模态框相关状态
 */
function cleanupModalState() {
    document.body.classList.remove('modal-open');
    document.body.style.overflow = '';
    document.body.style.paddingRight = '';

    const backdrops = document.querySelectorAll('.modal-backdrop');
    backdrops.forEach(backdrop => {
        backdrop.remove();
    });
    console.log('[cleanupModalState] 清理完成，移除了', backdrops.length, '个backdrop');
}

/**
 * 显示Toast消息
 */
function showToast(title, message, type = 'info') {
    const toastContainer = document.getElementById('toast-container');
    const toastId = 'toast-' + Date.now();
    
    const typeConfig = {
        success: { bg: 'bg-success', icon: 'fa-check-circle' },
        danger: { bg: 'bg-danger', icon: 'fa-exclamation-circle' },
        warning: { bg: 'bg-warning', icon: 'fa-exclamation-triangle' },
        info: { bg: 'bg-info', icon: 'fa-info-circle' }
    };
    
    const config = typeConfig[type] || typeConfig.info;
    
    const toastHtml = `
        <div class="toast" id="${toastId}" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="toast-header ${config.bg} text-white">
                <i class="fas ${config.icon} me-2"></i>
                <strong class="me-auto">${title}</strong>
                <small class="text-white-50">${new Date().toLocaleTimeString()}</small>
                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast"></button>
            </div>
            <div class="toast-body">
                ${message}
            </div>
        </div>
    `;
    
    toastContainer.insertAdjacentHTML('beforeend', toastHtml);
    
    const toastElement = document.getElementById(toastId);
    const toast = new bootstrap.Toast(toastElement, {
        autohide: true,
        delay: type === 'danger' ? 8000 : 5000
    });
    
    toast.show();
    
    // 自动清理
    toastElement.addEventListener('hidden.bs.toast', function() {
        toastElement.remove();
    });
}

// ==================== 浏览板块功能 ====================

/**
 * 浏览所有板块
 */
async function browsePlates() {
    try {
        // 重置状态
        selectedPlates.clear();
        availablePlatesData = [];
        filteredAvailablePlates = [];
        
        // 显示模态框
        browsePlatesModal.show();
        
        // 加载可用板块数据
        await loadAvailablePlates();
        
    } catch (error) {
        console.error('浏览板块失败:', error);
        showToast('错误', '打开浏览板块窗口失败', 'danger');
    }
}

/**
 * 加载可用板块数据
 */
async function loadAvailablePlates() {
    try {
        // 显示加载状态
        const tbody = document.getElementById('available-plates-table-body');
        tbody.innerHTML = `
            <tr>
                <td colspan="5" class="text-center text-muted py-3">
                    <div class="spinner-border spinner-border-sm me-2" role="status"></div>
                    正在获取可用板块...
                </td>
            </tr>
        `;
        
        const response = await fetch('/api/plates/available');
        const result = await response.json();
        
        if (result.success) {
            availablePlatesData = result.data;
            filteredAvailablePlates = availablePlatesData;
            renderAvailablePlatesTable();
            updateSelectedCount();
            console.log(`已加载 ${availablePlatesData.length} 个可用板块`);
        } else {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" class="text-center text-danger py-3">
                        <i class="fas fa-exclamation-circle"></i> ${result.message || '加载失败'}
                    </td>
                </tr>
            `;
            showToast('错误', `加载可用板块失败: ${result.message || '未知错误'}`, 'danger');
        }
    } catch (error) {
        console.error('加载可用板块失败:', error);
        const tbody = document.getElementById('available-plates-table-body');
        tbody.innerHTML = `
            <tr>
                <td colspan="5" class="text-center text-danger py-3">
                    <i class="fas fa-exclamation-circle"></i> 网络请求失败
                </td>
            </tr>
        `;
        showToast('错误', '加载可用板块请求失败', 'danger');
    }
}

/**
 * 渲染可用板块表格
 */
function renderAvailablePlatesTable(plates = filteredAvailablePlates) {
    const tbody = document.getElementById('available-plates-table-body');
    
    if (plates.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="5" class="text-center text-muted py-3">
                    <i class="fas fa-info-circle"></i> 没有找到匹配的板块
                </td>
            </tr>
        `;
        return;
    }
    
    const rows = plates.map(plate => {
        const isSelected = selectedPlates.has(plate.plate_code);
        const statusClass = plate.is_added ? 'text-success' : 'text-muted';
        const statusIcon = plate.is_added ? 'fa-check-circle' : 'fa-circle';
        
        return `
            <tr class="${isSelected ? 'table-primary' : ''}">
                <td>
                    <input type="checkbox" class="form-check-input plate-checkbox" 
                           value="${plate.plate_code}" 
                           ${isSelected ? 'checked' : ''}
                           ${plate.is_added ? 'disabled title="已添加"' : ''}>
                </td>
                <td class="fw-bold">${plate.plate_code}</td>
                <td>${plate.plate_name}</td>
                <td>
                    <span class="badge ${plate.market === 'HK' ? 'bg-primary' : 'bg-info'}">
                        ${plate.market === 'HK' ? '港股' : '美股'}
                    </span>
                </td>
                <td>
                    <span class="${statusClass}">
                        <i class="fas ${statusIcon}"></i> ${plate.status}
                    </span>
                </td>
            </tr>
        `;
    }).join('');
    
    tbody.innerHTML = rows;
    
    // 绑定复选框事件
    tbody.querySelectorAll('.plate-checkbox').forEach(checkbox => {
        checkbox.addEventListener('change', function() {
            const plateCode = this.value;
            if (this.checked) {
                selectedPlates.add(plateCode);
            } else {
                selectedPlates.delete(plateCode);
            }
            updateSelectedCount();
            updateBatchAddButton();
        });
    });
}

/**
 * 搜索可用板块
 */
function searchAvailablePlates() {
    filterAvailablePlates();
}

/**
 * 筛选可用板块
 */
function filterAvailablePlates() {
    const searchText = document.getElementById('search-available-plates').value.toLowerCase();
    const marketFilter = document.getElementById('market-filter').value;
    const statusFilter = document.getElementById('status-filter-modal').value;
    
    filteredAvailablePlates = availablePlatesData.filter(plate => {
        // 搜索过滤
        const searchMatch = !searchText || 
                           plate.plate_code.toLowerCase().includes(searchText) ||
                           plate.plate_name.toLowerCase().includes(searchText);
        
        // 市场过滤
        const marketMatch = !marketFilter || plate.market === marketFilter;
        
        // 状态过滤
        let statusMatch = true;
        if (statusFilter === 'added') {
            statusMatch = plate.is_added;
        } else if (statusFilter === 'not-added') {
            statusMatch = !plate.is_added;
        }
        
        return searchMatch && marketMatch && statusMatch;
    });
    
    renderAvailablePlatesTable();
}

/**
 * 全选板块
 */
function selectAllPlates() {
    filteredAvailablePlates.forEach(plate => {
        if (!plate.is_added) {
            selectedPlates.add(plate.plate_code);
        }
    });
    renderAvailablePlatesTable();
    updateSelectedCount();
    updateBatchAddButton();
    updateSelectAllCheckbox();
}

/**
 * 取消全选板块
 */
function deselectAllPlates() {
    selectedPlates.clear();
    renderAvailablePlatesTable();
    updateSelectedCount();
    updateBatchAddButton();
    updateSelectAllCheckbox();
}

/**
 * 选择科技板块
 */
function selectTechPlates() {
    const techKeywords = ['科技', '技术', '软件', '互联网', '电脑', '芯片', '半导体', '通信', 'IT', '科创'];
    
    filteredAvailablePlates.forEach(plate => {
        if (!plate.is_added && techKeywords.some(keyword => 
            plate.plate_name.includes(keyword) || plate.plate_code.includes(keyword))) {
            selectedPlates.add(plate.plate_code);
        }
    });
    
    renderAvailablePlatesTable();
    updateSelectedCount();
    updateBatchAddButton();
    updateSelectAllCheckbox();
}

/**
 * 选择医药板块
 */
function selectMedicalPlates() {
    const medicalKeywords = ['医药', '医疗', '生物', '制药', '健康', '医院', '诊断', '疫苗', '药品'];
    
    filteredAvailablePlates.forEach(plate => {
        if (!plate.is_added && medicalKeywords.some(keyword => 
            plate.plate_name.includes(keyword) || plate.plate_code.includes(keyword))) {
            selectedPlates.add(plate.plate_code);
        }
    });
    
    renderAvailablePlatesTable();
    updateSelectedCount();
    updateBatchAddButton();
    updateSelectAllCheckbox();
}

/**
 * 切换全选状态
 */
function toggleAllPlates() {
    const checkbox = document.getElementById('select-all-checkbox');
    if (checkbox.checked) {
        selectAllPlates();
    } else {
        deselectAllPlates();
    }
}

/**
 * 批量添加板块
 */
async function batchAddPlates() {
    if (selectedPlates.size === 0) {
        showToast('警告', '请先选择要添加的板块', 'warning');
        return;
    }
    
    const plateCodesArray = Array.from(selectedPlates);
    
    try {
        showLoading(`批量添加 ${plateCodesArray.length} 个板块中...`);
        
        const response = await fetch('/api/plates/batch-add', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ plate_codes: plateCodesArray })
        });
        
        const result = await response.json();
        
        if (result.success) {
            const { success_count, failed_count, failed_plates } = result.data;
            
            // 清空选择
            selectedPlates.clear();
            
            // 关闭模态框
            browsePlatesModal.hide();
            
            // 重新加载页面数据
            await loadPageData();
            
            // 显示结果
            if (success_count > 0) {
                showToast('成功', `成功添加 ${success_count} 个板块`, 'success');
            }
            
            if (failed_count > 0) {
                const failedMessages = failed_plates.map(fp => `${fp.plate_code}: ${fp.error}`).join('\n');
                showToast('警告', `${failed_count} 个板块添加失败:\n${failedMessages}`, 'warning');
            }
        } else {
            showToast('错误', `批量添加失败: ${result.message || '未知错误'}`, 'danger');
        }
    } catch (error) {
        console.error('批量添加板块失败:', error);
        showToast('错误', '批量添加板块请求失败', 'danger');
    } finally {
        hideLoading();
    }
}

/**
 * 更新选中数量显示
 */
function updateSelectedCount() {
    const countElement = document.getElementById('selected-count');
    if (countElement) {
        countElement.textContent = selectedPlates.size;
    }
}

/**
 * 更新批量添加按钮状态
 */
function updateBatchAddButton() {
    const button = document.getElementById('confirm-batch-add');
    if (button) {
        button.disabled = selectedPlates.size === 0;
    }
}

/**
 * 更新全选复选框状态
 */
function updateSelectAllCheckbox() {
    const checkbox = document.getElementById('select-all-checkbox');
    if (checkbox) {
        const availableNotAdded = filteredAvailablePlates.filter(plate => !plate.is_added);
        const selectedFromVisible = availableNotAdded.filter(plate => selectedPlates.has(plate.plate_code));
        
        if (availableNotAdded.length === 0) {
            checkbox.indeterminate = false;
            checkbox.checked = false;
        } else if (selectedFromVisible.length === availableNotAdded.length) {
            checkbox.indeterminate = false;
            checkbox.checked = true;
        } else if (selectedFromVisible.length > 0) {
            checkbox.indeterminate = true;
            checkbox.checked = false;
        } else {
            checkbox.indeterminate = false;
            checkbox.checked = false;
        }
    }
}

// ==================== 分页功能实现 ====================

/**
 * 绑定分页相关事件
 */
function bindPaginationEvents() {
    // 板块分页事件
    const platesPageSize = document.getElementById('plates-page-size');
    if (platesPageSize) {
        platesPageSize.addEventListener('change', function() {
            platesPagination.pageSize = parseInt(this.value);
            platesPagination.currentPage = 1;
            updatePlatesPagination();
        });
    }
    
    // 股票分页事件
    const stocksPageSize = document.getElementById('stocks-page-size');
    if (stocksPageSize) {
        stocksPageSize.addEventListener('change', function() {
            stocksPagination.pageSize = parseInt(this.value);
            stocksPagination.currentPage = 1;
            updateStocksPagination();
        });
    }
}

/**
 * 更新板块分页 - 修复版本
 * 使用全局变量 filteredPlates 作为数据源，支持筛选功能
 */
function updatePlatesPagination() {
    // 使用 filteredPlates 而不是 platesData，这样筛选结果不会被覆盖
    platesPagination.filteredData = filteredPlates;
    platesPagination.totalItems = platesPagination.filteredData.length;
    
    // 计算总页数
    const totalPages = Math.ceil(platesPagination.totalItems / platesPagination.pageSize);
    
    // 确保当前页在有效范围内
    platesPagination.currentPage = Math.min(platesPagination.currentPage, Math.max(1, totalPages));
    
    // 计算分页数据
    const startIndex = (platesPagination.currentPage - 1) * platesPagination.pageSize;
    const endIndex = startIndex + platesPagination.pageSize;
    const pageData = platesPagination.filteredData.slice(startIndex, endIndex);
    
    // 渲染表格
    renderPlatesTable(pageData);
    
    // 更新分页控件
    renderPlatesPagination(totalPages);
    updatePlatesPaginationInfo();
    
    // 显示/隐藏分页控件
    const container = document.getElementById('plates-pagination-container');
    if (container) {
        if (platesPagination.totalItems > platesPagination.pageSize) {
            container.style.display = 'flex';
        } else {
            container.style.display = 'none';
        }
    }
}

/**
 * 更新股票分页
 */
function updateStocksPagination() {
    stocksPagination.filteredData = filteredStocks;
    stocksPagination.totalItems = stocksPagination.filteredData.length;
    
    // 计算总页数
    const totalPages = Math.ceil(stocksPagination.totalItems / stocksPagination.pageSize);
    
    // 确保当前页在有效范围内
    stocksPagination.currentPage = Math.min(stocksPagination.currentPage, Math.max(1, totalPages));
    
    // 计算分页数据
    const startIndex = (stocksPagination.currentPage - 1) * stocksPagination.pageSize;
    const endIndex = startIndex + stocksPagination.pageSize;
    const pageData = stocksPagination.filteredData.slice(startIndex, endIndex);
    
    // 渲染表格
    renderStocksTable(pageData);
    
    // 更新分页控件
    renderStocksPagination(totalPages);
    updateStocksPaginationInfo();
    
    // 显示/隐藏分页控件
    const container = document.getElementById('stocks-pagination-container');
    if (container) {
        if (stocksPagination.totalItems > stocksPagination.pageSize) {
            container.style.display = 'flex';
        } else {
            container.style.display = 'none';
        }
    }
}

/**
 * 渲染板块分页导航
 */
function renderPlatesPagination(totalPages) {
    const pagination = document.getElementById('plates-pagination');
    if (!pagination) return;
    
    const currentPage = platesPagination.currentPage;
    let html = '';
    
    // 上一页
    html += `
        <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="goToPlatesPage(${currentPage - 1})" aria-label="上一页">
                <span aria-hidden="true">&laquo;</span>
            </a>
        </li>
    `;
    
    // 页码按钮
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
    
    // 下一页
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
 * 渲染股票分页导航
 */
function renderStocksPagination(totalPages) {
    const pagination = document.getElementById('stocks-pagination');
    if (!pagination) return;
    
    const currentPage = stocksPagination.currentPage;
    let html = '';
    
    // 上一页
    html += `
        <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="goToStocksPage(${currentPage - 1})" aria-label="上一页">
                <span aria-hidden="true">&laquo;</span>
            </a>
        </li>
    `;
    
    // 页码按钮
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
    
    // 下一页
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
 * 更新板块分页信息
 */
function updatePlatesPaginationInfo() {
    const info = document.getElementById('plates-info');
    if (!info) return;
    
    const { currentPage, pageSize, totalItems } = platesPagination;
    const startIndex = (currentPage - 1) * pageSize + 1;
    const endIndex = Math.min(currentPage * pageSize, totalItems);
    
    info.textContent = `显示第${startIndex}-${endIndex}条，共${totalItems}条记录`;
}

/**
 * 更新股票分页信息
 */
function updateStocksPaginationInfo() {
    const info = document.getElementById('stocks-info');
    if (!info) return;
    
    const { currentPage, pageSize, totalItems } = stocksPagination;
    const startIndex = (currentPage - 1) * pageSize + 1;
    const endIndex = Math.min(currentPage * pageSize, totalItems);
    
    info.textContent = `显示第${startIndex}-${endIndex}条，共${totalItems}条记录`;
}

/**
 * 跳转到板块指定页
 */
function goToPlatesPage(page) {
    const totalPages = Math.ceil(platesPagination.totalItems / platesPagination.pageSize);
    platesPagination.currentPage = Math.max(1, Math.min(page, totalPages));
    updatePlatesPagination();
}

/**
 * 跳转到股票指定页
 */
function goToStocksPage(page) {
    const totalPages = Math.ceil(stocksPagination.totalItems / stocksPagination.pageSize);
    stocksPagination.currentPage = Math.max(1, Math.min(page, totalPages));
    updateStocksPagination();
}

// ==================== 优先级编辑功能 ====================

/**
 * 显示优先级编辑模态框
 */
function showPriorityEditModal(plateId, currentPriority, plateName) {
    // 如果模态框还不存在，先创建
    let priorityModal = document.getElementById('priorityEditModal');
    if (!priorityModal) {
        const modalHtml = `
            <div class="modal fade" id="priorityEditModal" tabindex="-1">
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">
                                <i class="fas fa-edit me-2"></i>编辑板块优先级
                            </h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <div class="mb-3">
                                <label class="form-label fw-bold">板块信息</label>
                                <p class="text-muted mb-1" id="priority-plate-name"></p>
                            </div>
                            
                            <!-- 优先级图例 -->
                            <div class="mb-3">
                                <label class="form-label">优先级说明</label>
                                <div class="row g-2">
                                    <div class="col-6 col-md-3">
                                        <div class="card border-danger">
                                            <div class="card-body p-2 text-center">
                                                <i class="fas fa-crown text-danger"></i>
                                                <div class="small fw-bold">核心 (80-100)</div>
                                                <div class="small text-muted">最高优先级</div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="col-6 col-md-3">
                                        <div class="card border-warning">
                                            <div class="card-body p-2 text-center">
                                                <i class="fas fa-star text-warning"></i>
                                                <div class="small fw-bold">重要 (50-79)</div>
                                                <div class="small text-muted">中等优先级</div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="col-6 col-md-3">
                                        <div class="card border-info">
                                            <div class="card-body p-2 text-center">
                                                <i class="fas fa-circle text-info"></i>
                                                <div class="small fw-bold">一般 (1-49)</div>
                                                <div class="small text-muted">低优先级</div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="col-6 col-md-3">
                                        <div class="card border-secondary">
                                            <div class="card-body p-2 text-center">
                                                <i class="fas fa-minus text-secondary"></i>
                                                <div class="small fw-bold">普通 (0)</div>
                                                <div class="small text-muted">无优先级</div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="mb-3">
                                <label for="priority-input" class="form-label">设置优先级 (0-100)</label>
                                <div class="row g-2">
                                    <div class="col-8">
                                        <input type="range" class="form-range" id="priority-slider" 
                                               min="0" max="100" value="0">
                                    </div>
                                    <div class="col-4">
                                        <input type="number" class="form-control" id="priority-input" 
                                               min="0" max="100" value="0">
                                    </div>
                                </div>
                                <div class="form-text">
                                    <span id="priority-level-text">普通板块</span>
                                </div>
                            </div>
                            
                            <!-- 快速设置按钮 -->
                            <div class="mb-3">
                                <label class="form-label">快速设置</label>
                                <div class="btn-group w-100" role="group">
                                    <button type="button" class="btn btn-outline-secondary btn-sm quick-priority-btn" 
                                            data-priority="0">普通</button>
                                    <button type="button" class="btn btn-outline-info btn-sm quick-priority-btn" 
                                            data-priority="30">一般</button>
                                    <button type="button" class="btn btn-outline-warning btn-sm quick-priority-btn" 
                                            data-priority="60">重要</button>
                                    <button type="button" class="btn btn-outline-danger btn-sm quick-priority-btn" 
                                            data-priority="90">核心</button>
                                </div>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                                <i class="fas fa-times me-1"></i>取消
                            </button>
                            <button type="button" class="btn btn-primary" id="save-priority-btn">
                                <i class="fas fa-save me-1"></i>保存优先级
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        
        // 绑定事件
        bindPriorityModalEvents();
        
        priorityModal = document.getElementById('priorityEditModal');
    }
    
    // 设置板块信息
    document.getElementById('priority-plate-name').textContent = plateName;
    
    // 设置当前优先级
    const prioritySlider = document.getElementById('priority-slider');
    const priorityInput = document.getElementById('priority-input');
    
    prioritySlider.value = currentPriority;
    priorityInput.value = currentPriority;
    updatePriorityLevelText(currentPriority);
    
    // 保存当前编辑的板块ID
    priorityModal.dataset.plateId = plateId;
    
    // 显示模态框
    const modal = new bootstrap.Modal(priorityModal);
    modal.show();
}

/**
 * 绑定优先级模态框事件
 */
function bindPriorityModalEvents() {
    const prioritySlider = document.getElementById('priority-slider');
    const priorityInput = document.getElementById('priority-input');
    const savePriorityBtn = document.getElementById('save-priority-btn');
    
    // 滑块和输入框同步
    prioritySlider.addEventListener('input', function() {
        priorityInput.value = this.value;
        updatePriorityLevelText(parseInt(this.value));
    });
    
    priorityInput.addEventListener('input', function() {
        let value = parseInt(this.value);
        if (isNaN(value)) value = 0;
        if (value < 0) value = 0;
        if (value > 100) value = 100;
        
        this.value = value;
        prioritySlider.value = value;
        updatePriorityLevelText(value);
    });
    
    // 快速设置按钮
    document.querySelectorAll('.quick-priority-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const priority = parseInt(this.dataset.priority);
            prioritySlider.value = priority;
            priorityInput.value = priority;
            updatePriorityLevelText(priority);
        });
    });
    
    // 保存按钮
    savePriorityBtn.addEventListener('click', savePlatePriority);
}

/**
 * 更新优先级级别文本
 */
function updatePriorityLevelText(priority) {
    const priorityText = document.getElementById('priority-level-text');
    
    if (priority >= 80) {
        priorityText.innerHTML = '<span class="text-danger fw-bold"><i class="fas fa-crown"></i> 核心板块 - 最高优先级</span>';
    } else if (priority >= 50) {
        priorityText.innerHTML = '<span class="text-warning fw-bold"><i class="fas fa-star"></i> 重要板块 - 中等优先级</span>';
    } else if (priority > 0) {
        priorityText.innerHTML = '<span class="text-info fw-bold"><i class="fas fa-circle"></i> 一般板块 - 低优先级</span>';
    } else {
        priorityText.innerHTML = '<span class="text-secondary"><i class="fas fa-minus"></i> 普通板块 - 无优先级</span>';
    }
}

/**
 * 保存板块优先级
 */
async function savePlatePriority() {
    const priorityModal = document.getElementById('priorityEditModal');
    const plateId = priorityModal.dataset.plateId;
    const priority = parseInt(document.getElementById('priority-input').value);
    
    if (!plateId) {
        showToast('错误', '板块ID丢失，请重新打开编辑窗口', 'danger');
        return;
    }
    
    try {
        showLoading('保存优先级中...');
        
        const response = await fetch(`/api/plates/${plateId}/priority`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ priority: priority })
        });
        
        const result = await response.json();
        
        if (result.success) {
            // 关闭模态框
            const modal = bootstrap.Modal.getInstance(priorityModal);
            modal.hide();
            
            // 刷新板块数据
            await loadPageData();
            
            showToast('成功', result.message, 'success');
        } else {
            showToast('错误', `保存优先级失败: ${result.message}`, 'danger');
        }
    } catch (error) {
        console.error('保存优先级失败:', error);
        showToast('错误', '保存优先级请求失败', 'danger');
    } finally {
        hideLoading();
    }
}

console.log('股票池管理页面脚本加载完成 - 简化版本');
