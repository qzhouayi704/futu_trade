/**
 * 股票池管理 - 浏览板块和优先级编辑模块
 * 功能：浏览可用板块、批量添加、优先级编辑
 * 
 * 依赖：StockPoolState (全局状态对象)
 */

// ==================== 浏览板块功能 ====================

async function browsePlates() {
    try {
        StockPoolState.selectedPlates.clear();
        StockPoolState.availablePlatesData = [];
        StockPoolState.filteredAvailablePlates = [];
        StockPoolState.browsePlatesModal.show();
        await loadAvailablePlates();
    } catch (error) {
        console.error('浏览板块失败:', error);
        showToast('错误', '打开浏览板块窗口失败', 'danger');
    }
}

async function loadAvailablePlates() {
    const tbody = document.getElementById('available-plates-table-body');
    tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-3">
        <div class="spinner-border spinner-border-sm me-2" role="status"></div>正在获取可用板块...</td></tr>`;
    
    try {
        const response = await fetch('/api/plates/available');
        const result = await response.json();
        
        if (result.success) {
            StockPoolState.availablePlatesData = result.data;
            StockPoolState.filteredAvailablePlates = StockPoolState.availablePlatesData;
            renderAvailablePlatesTable();
            updateSelectedCount();
            console.log(`已加载 ${StockPoolState.availablePlatesData.length} 个可用板块`);
        } else {
            tbody.innerHTML = `<tr><td colspan="5" class="text-center text-danger py-3">
                <i class="fas fa-exclamation-circle"></i> ${result.message || '加载失败'}</td></tr>`;
            showToast('错误', `加载可用板块失败: ${result.message || '未知错误'}`, 'danger');
        }
    } catch (error) {
        console.error('加载可用板块失败:', error);
        tbody.innerHTML = `<tr><td colspan="5" class="text-center text-danger py-3">
            <i class="fas fa-exclamation-circle"></i> 网络请求失败</td></tr>`;
        showToast('错误', '加载可用板块请求失败', 'danger');
    }
}

function renderAvailablePlatesTable(plates = StockPoolState.filteredAvailablePlates) {
    const tbody = document.getElementById('available-plates-table-body');
    
    if (plates.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-3">
            <i class="fas fa-info-circle"></i> 没有找到匹配的板块</td></tr>`;
        return;
    }
    
    const rows = plates.map(plate => {
        const isSelected = StockPoolState.selectedPlates.has(plate.plate_code);
        const statusClass = plate.is_added ? 'text-success' : 'text-muted';
        const statusIcon = plate.is_added ? 'fa-check-circle' : 'fa-circle';
        
        return `
            <tr class="${isSelected ? 'table-primary' : ''}">
                <td><input type="checkbox" class="form-check-input plate-checkbox" 
                       value="${plate.plate_code}" ${isSelected ? 'checked' : ''} ${plate.is_added ? 'disabled title="已添加"' : ''}></td>
                <td class="fw-bold">${plate.plate_code}</td>
                <td>${plate.plate_name}</td>
                <td><span class="badge ${plate.market === 'HK' ? 'bg-primary' : 'bg-info'}">${plate.market === 'HK' ? '港股' : '美股'}</span></td>
                <td><span class="${statusClass}"><i class="fas ${statusIcon}"></i> ${plate.status}</span></td>
            </tr>
        `;
    }).join('');
    
    tbody.innerHTML = rows;
    
    // 绑定复选框事件
    tbody.querySelectorAll('.plate-checkbox').forEach(checkbox => {
        checkbox.addEventListener('change', function() {
            if (this.checked) {
                StockPoolState.selectedPlates.add(this.value);
            } else {
                StockPoolState.selectedPlates.delete(this.value);
            }
            updateSelectedCount();
            updateBatchAddButton();
        });
    });
}

// ==================== 搜索和筛选 ====================

function searchAvailablePlates() { filterAvailablePlates(); }

function filterAvailablePlates() {
    const searchText = document.getElementById('search-available-plates').value.toLowerCase();
    const marketFilter = document.getElementById('market-filter').value;
    const statusFilter = document.getElementById('status-filter-modal').value;
    
    StockPoolState.filteredAvailablePlates = StockPoolState.availablePlatesData.filter(plate => {
        const searchMatch = !searchText || 
            plate.plate_code.toLowerCase().includes(searchText) ||
            plate.plate_name.toLowerCase().includes(searchText);
        const marketMatch = !marketFilter || plate.market === marketFilter;
        let statusMatch = true;
        if (statusFilter === 'added') statusMatch = plate.is_added;
        else if (statusFilter === 'not-added') statusMatch = !plate.is_added;
        return searchMatch && marketMatch && statusMatch;
    });
    
    renderAvailablePlatesTable();
}

// ==================== 全选/取消全选 ====================

function selectAllPlates() {
    StockPoolState.filteredAvailablePlates.forEach(plate => {
        if (!plate.is_added) StockPoolState.selectedPlates.add(plate.plate_code);
    });
    renderAvailablePlatesTable();
    updateSelectedCount();
    updateBatchAddButton();
    updateSelectAllCheckbox();
}

function deselectAllPlates() {
    StockPoolState.selectedPlates.clear();
    renderAvailablePlatesTable();
    updateSelectedCount();
    updateBatchAddButton();
    updateSelectAllCheckbox();
}

function selectTechPlates() {
    const keywords = ['科技', '技术', '软件', '互联网', '电脑', '芯片', '半导体', '通信', 'IT', '科创'];
    StockPoolState.filteredAvailablePlates.forEach(plate => {
        if (!plate.is_added && keywords.some(k => plate.plate_name.includes(k) || plate.plate_code.includes(k))) {
            StockPoolState.selectedPlates.add(plate.plate_code);
        }
    });
    renderAvailablePlatesTable();
    updateSelectedCount();
    updateBatchAddButton();
    updateSelectAllCheckbox();
}

function selectMedicalPlates() {
    const keywords = ['医药', '医疗', '生物', '制药', '健康', '医院', '诊断', '疫苗', '药品'];
    StockPoolState.filteredAvailablePlates.forEach(plate => {
        if (!plate.is_added && keywords.some(k => plate.plate_name.includes(k) || plate.plate_code.includes(k))) {
            StockPoolState.selectedPlates.add(plate.plate_code);
        }
    });
    renderAvailablePlatesTable();
    updateSelectedCount();
    updateBatchAddButton();
    updateSelectAllCheckbox();
}

function toggleAllPlates() {
    const checkbox = document.getElementById('select-all-checkbox');
    if (checkbox.checked) selectAllPlates();
    else deselectAllPlates();
}

// ==================== 批量添加 ====================

async function batchAddPlates() {
    if (StockPoolState.selectedPlates.size === 0) {
        showToast('警告', '请先选择要添加的板块', 'warning');
        return;
    }
    
    const plateCodesArray = Array.from(StockPoolState.selectedPlates);
    
    try {
        showLoading(`批量添加 ${plateCodesArray.length} 个板块中...`);
        const response = await fetch('/api/plates/batch-add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plate_codes: plateCodesArray })
        });
        const result = await response.json();
        
        if (result.success) {
            const { success_count, failed_count, failed_plates } = result.data;
            StockPoolState.selectedPlates.clear();
            StockPoolState.browsePlatesModal.hide();
            await loadPageData();
            if (success_count > 0) showToast('成功', `成功添加 ${success_count} 个板块`, 'success');
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

// ==================== UI 更新辅助 ====================

function updateSelectedCount() {
    const el = document.getElementById('selected-count');
    if (el) el.textContent = StockPoolState.selectedPlates.size;
}

function updateBatchAddButton() {
    const btn = document.getElementById('confirm-batch-add');
    if (btn) btn.disabled = StockPoolState.selectedPlates.size === 0;
}

function updateSelectAllCheckbox() {
    const checkbox = document.getElementById('select-all-checkbox');
    if (!checkbox) return;
    const available = StockPoolState.filteredAvailablePlates.filter(p => !p.is_added);
    const selected = available.filter(p => StockPoolState.selectedPlates.has(p.plate_code));
    if (available.length === 0) { checkbox.indeterminate = false; checkbox.checked = false; }
    else if (selected.length === available.length) { checkbox.indeterminate = false; checkbox.checked = true; }
    else if (selected.length > 0) { checkbox.indeterminate = true; checkbox.checked = false; }
    else { checkbox.indeterminate = false; checkbox.checked = false; }
}

// ==================== 导出到全局 ====================
window.browsePlates = browsePlates;
window.loadAvailablePlates = loadAvailablePlates;
window.renderAvailablePlatesTable = renderAvailablePlatesTable;
window.searchAvailablePlates = searchAvailablePlates;
window.filterAvailablePlates = filterAvailablePlates;
window.selectAllPlates = selectAllPlates;
window.deselectAllPlates = deselectAllPlates;
window.selectTechPlates = selectTechPlates;
window.selectMedicalPlates = selectMedicalPlates;
window.toggleAllPlates = toggleAllPlates;
window.batchAddPlates = batchAddPlates;
window.updateSelectedCount = updateSelectedCount;
window.updateBatchAddButton = updateBatchAddButton;
window.updateSelectAllCheckbox = updateSelectAllCheckbox;
