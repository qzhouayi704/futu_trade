/**
 * 股票池管理 - 优先级编辑模块
 * 功能：板块优先级的编辑、保存
 * 
 * 依赖：StockPoolState (全局状态对象)
 */

// ==================== 优先级编辑功能 ====================

/**
 * 显示优先级编辑模态框
 */
function showPriorityEditModal(plateId, currentPriority, plateName) {
    let priorityModal = document.getElementById('priorityEditModal');
    if (!priorityModal) {
        const modalHtml = `
            <div class="modal fade" id="priorityEditModal" tabindex="-1">
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title"><i class="fas fa-edit me-2"></i>编辑板块优先级</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <div class="mb-3">
                                <label class="form-label fw-bold">板块信息</label>
                                <p class="text-muted mb-1" id="priority-plate-name"></p>
                            </div>
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
                                        <input type="range" class="form-range" id="priority-slider" min="0" max="100" value="0">
                                    </div>
                                    <div class="col-4">
                                        <input type="number" class="form-control" id="priority-input" min="0" max="100" value="0">
                                    </div>
                                </div>
                                <div class="form-text"><span id="priority-level-text">普通板块</span></div>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">快速设置</label>
                                <div class="btn-group w-100" role="group">
                                    <button type="button" class="btn btn-outline-secondary btn-sm quick-priority-btn" data-priority="0">普通</button>
                                    <button type="button" class="btn btn-outline-info btn-sm quick-priority-btn" data-priority="30">一般</button>
                                    <button type="button" class="btn btn-outline-warning btn-sm quick-priority-btn" data-priority="60">重要</button>
                                    <button type="button" class="btn btn-outline-danger btn-sm quick-priority-btn" data-priority="90">核心</button>
                                </div>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                                <i class="fas fa-times me-1"></i>取消</button>
                            <button type="button" class="btn btn-primary" id="save-priority-btn">
                                <i class="fas fa-save me-1"></i>保存优先级</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        bindPriorityModalEvents();
        priorityModal = document.getElementById('priorityEditModal');
    }
    
    document.getElementById('priority-plate-name').textContent = plateName;
    
    const prioritySlider = document.getElementById('priority-slider');
    const priorityInput = document.getElementById('priority-input');
    prioritySlider.value = currentPriority;
    priorityInput.value = currentPriority;
    updatePriorityLevelText(currentPriority);
    
    priorityModal.dataset.plateId = plateId;
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
    
    document.querySelectorAll('.quick-priority-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const priority = parseInt(this.dataset.priority);
            prioritySlider.value = priority;
            priorityInput.value = priority;
            updatePriorityLevelText(priority);
        });
    });
    
    savePriorityBtn.addEventListener('click', savePlatePriority);
}

/**
 * 更新优先级级别文本
 */
function updatePriorityLevelText(priority) {
    const el = document.getElementById('priority-level-text');
    if (priority >= 80) {
        el.innerHTML = '<span class="text-danger fw-bold"><i class="fas fa-crown"></i> 核心板块 - 最高优先级</span>';
    } else if (priority >= 50) {
        el.innerHTML = '<span class="text-warning fw-bold"><i class="fas fa-star"></i> 重要板块 - 中等优先级</span>';
    } else if (priority > 0) {
        el.innerHTML = '<span class="text-info fw-bold"><i class="fas fa-circle"></i> 一般板块 - 低优先级</span>';
    } else {
        el.innerHTML = '<span class="text-secondary"><i class="fas fa-minus"></i> 普通板块 - 无优先级</span>';
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
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ priority: priority })
        });
        const result = await response.json();
        
        if (result.success) {
            const modal = bootstrap.Modal.getInstance(priorityModal);
            modal.hide();
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

// ==================== 导出到全局 ====================
window.showPriorityEditModal = showPriorityEditModal;
window.savePlatePriority = savePlatePriority;
