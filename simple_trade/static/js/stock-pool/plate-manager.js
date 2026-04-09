/**
 * 股票池管理 - 板块管理模块
 * 功能：板块增删、浏览、筛选、优先级管理
 * 
 * 依赖：StockPoolState (全局状态对象)
 */

// ==================== 板块加载 ====================

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
 * 加载板块列表（内部版本）
 */
async function loadPlatesInternal() {
    try {
        const response = await fetch('/api/data?type=plates&limit=1000');
        const result = await response.json();
        
        if (result.success) {
            StockPoolState.platesData = result.data;
            StockPoolState.filteredPlates = StockPoolState.platesData;
            updatePlatesPagination();
            updatePlateFilter();
            console.log(`已加载 ${StockPoolState.platesData.length} 个板块`);
        } else {
            showToast('错误', `加载板块失败: ${result.message || '未知错误'}`, 'danger');
            StockPoolState.platesData = [];
            StockPoolState.filteredPlates = [];
            updatePlatesPagination();
        }
    } catch (error) {
        console.error('加载板块失败:', error);
        showToast('错误', '加载板块请求失败', 'danger');
        StockPoolState.platesData = [];
        StockPoolState.filteredPlates = [];
        updatePlatesPagination();
    }
}

// ==================== 板块渲染 ====================

/**
 * 渲染板块表格
 */
function renderPlatesTable(plates = StockPoolState.platesData) {
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
            const isEnabled = plate.is_enabled !== undefined ? plate.is_enabled : true;
            const priority = plate.priority || 0;
            const safePlateName = (plate.plate_name || '').replace(/'/g, "\\'");

            let rowClass = '';
            let priorityBadge = '';

            if (priority >= 80) {
                rowClass = 'table-danger';
                priorityBadge = '<span class="badge bg-danger me-2" title="核心板块"><i class="fas fa-crown"></i> 核心</span>';
            } else if (priority >= 50) {
                rowClass = 'table-warning';
                priorityBadge = '<span class="badge bg-warning text-dark me-2" title="重要板块"><i class="fas fa-star"></i> 重要</span>';
            } else if (priority > 0) {
                priorityBadge = '<span class="badge bg-info me-2" title="一般板块"><i class="fas fa-circle"></i> 一般</span>';
            } else {
                priorityBadge = '<span class="badge bg-secondary me-2" title="普通板块"><i class="fas fa-minus"></i> 普通</span>';
            }

            const targetBadge = plate.is_target
                ? '<span class="badge bg-success me-1" title="目标板块"><i class="fas fa-check"></i> 目标</span>'
                : '';

            return `
                <tr class="${rowClass}" data-plate-id="${plate.id}" data-priority="${priority}">
                    <td class="fw-bold text-nowrap">${plate.plate_code || '-'}</td>
                    <td>
                        <div class="d-flex flex-wrap align-items-center">
                            ${priorityBadge}${targetBadge}
                            <span class="plate-name">${plate.plate_name || '-'}</span>
                        </div>
                    </td>
                    <td><span class="badge bg-primary">${plate.market || '-'}</span></td>
                    <td class="text-center"><span class="badge bg-info fs-6">${plate.stock_count || 0}</span></td>
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
                            <div class="form-check form-switch mb-0">
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

// ==================== 板块操作 ====================

/**
 * 切换板块启用/禁用状态
 */
async function togglePlateStatus(plateId, currentStatus, plateName) {
    const action = currentStatus ? '禁用' : '启用';
    const newStatus = !currentStatus;
    
    if (!confirm(`确定要${action}板块 "${plateName}" 吗？`)) {
        const switchEl = document.getElementById(`plate-switch-${plateId}`);
        if (switchEl) switchEl.checked = currentStatus;
        return;
    }
    
    try {
        showLoading(`${action}板块中...`);
        
        const response = await fetch(`/api/plates/${plateId}/toggle`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const result = await response.json();
        
        if (result.success) {
            const plateIndex = StockPoolState.platesData.findIndex(p => p.id === plateId);
            if (plateIndex !== -1) {
                StockPoolState.platesData[plateIndex].is_enabled = newStatus;
            }
            updatePlatesPagination();
            await loadStocks();
            updateStatistics();
            showToast('成功', result.message, 'success');
        } else {
            const switchEl = document.getElementById(`plate-switch-${plateId}`);
            if (switchEl) switchEl.checked = currentStatus;
            showToast('错误', `${action}板块失败: ${result.message}`, 'danger');
        }
    } catch (error) {
        console.error(`${action}板块失败:`, error);
        const switchEl = document.getElementById(`plate-switch-${plateId}`);
        if (switchEl) switchEl.checked = currentStatus;
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
    
    if (!plateCode.match(/^[A-Z]{2}\d+$/)) {
        showToast('警告', '板块代码格式不正确，应为类似 BK1027 的格式', 'warning');
        return;
    }
    
    try {
        showLoading('添加板块中...');
        const response = await fetch('/api/plates/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plate_code: plateCode })
        });
        
        const result = await response.json();
        
        if (result.success) {
            plateCodeInput.value = '';
            await loadPageData();
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
    StockPoolState.currentDeleteAction = {
        type: 'plate',
        id: plateId,
        name: plateName
    };
    
    document.getElementById('delete-message').textContent = 
        `确定要删除板块 "${plateName}" 吗？这将同时删除该板块下的所有股票！`;
    StockPoolState.deleteModal.show();
}

// ==================== 板块筛选 ====================

/**
 * 筛选板块
 */
function filterPlates() {
    const marketFilter = document.getElementById('plate-market-filter').value;
    const typeFilter = document.getElementById('plate-type-filter').value;
    const priorityFilter = document.getElementById('plate-priority-filter')?.value || '';
    
    StockPoolState.filteredPlates = StockPoolState.platesData.filter(plate => {
        const marketMatch = !marketFilter || plate.market === marketFilter;
        
        let typeMatch = true;
        if (typeFilter === 'target') typeMatch = plate.is_target;
        else if (typeFilter === 'normal') typeMatch = !plate.is_target;
        
        let priorityMatch = true;
        const priority = plate.priority || 0;
        if (priorityFilter === 'high') priorityMatch = priority >= 80;
        else if (priorityFilter === 'medium') priorityMatch = priority >= 50 && priority < 80;
        else if (priorityFilter === 'low') priorityMatch = priority > 0 && priority < 50;
        else if (priorityFilter === 'normal') priorityMatch = priority === 0;
        
        return marketMatch && typeMatch && priorityMatch;
    });
    
    StockPoolState.platesPagination.currentPage = 1;
    updatePlatesPagination();
}

/**
 * 更新板块筛选器
 */
function updatePlateFilter() {
    const plateFilter = document.getElementById('plate-filter');
    const currentValue = plateFilter.value;
    
    plateFilter.innerHTML = '<option value="">所有板块</option>';
    
    StockPoolState.platesData.forEach(plate => {
        const option = document.createElement('option');
        option.value = plate.id;
        option.textContent = `${plate.plate_code} - ${plate.plate_name}`;
        plateFilter.appendChild(option);
    });
    
    plateFilter.value = currentValue;
}

// ==================== 导出到全局 ====================
window.loadPlates = loadPlates;
window.loadPlatesInternal = loadPlatesInternal;
window.renderPlatesTable = renderPlatesTable;
window.togglePlateStatus = togglePlateStatus;
window.addPlate = addPlate;
window.deletePlate = deletePlate;
window.filterPlates = filterPlates;
window.updatePlateFilter = updatePlateFilter;
