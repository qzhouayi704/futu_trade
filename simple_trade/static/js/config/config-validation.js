/**
 * 系统配置管理 - 验证和 UI 辅助模块
 * 功能：表单验证、确认对话框、加载状态、Toast 消息、工具函数
 */

// ==================== 表单验证 ====================

function bindFormValidation() {
    const numberInputs = document.querySelectorAll('input[type="number"]');
    numberInputs.forEach(input => {
        input.addEventListener('change', validateNumberInput);
        input.addEventListener('blur', validateNumberInput);
    });
    
    const portInput = document.getElementById('futu_port');
    if (portInput) {
        portInput.addEventListener('change', function() {
            const value = parseInt(this.value);
            if (value && (value < 1 || value > 65535)) {
                showToast('验证错误', '端口号必须在1-65535之间', 'warning');
                this.value = 11111;
            }
        });
    }
}

function validateNumberInput(event) {
    const input = event.target;
    const value = parseFloat(input.value);
    const min = parseFloat(input.getAttribute('min'));
    const max = parseFloat(input.getAttribute('max'));
    
    if (!isNaN(value)) {
        if (!isNaN(min) && value < min) {
            showToast('验证错误', `${input.labels[0].textContent.split('(')[0].trim()}不能小于${min}`, 'warning');
            input.value = min;
        } else if (!isNaN(max) && value > max) {
            showToast('验证错误', `${input.labels[0].textContent.split('(')[0].trim()}不能大于${max}`, 'warning');
            input.value = max;
        }
    }
}

function validateConfig(config) {
    const requiredFields = {
        'futu_host': '富途API主机地址',
        'futu_port': '富途API端口',
        'update_interval': '更新间隔'
    };
    
    for (const [field, label] of Object.entries(requiredFields)) {
        if (!config[field] || (typeof config[field] === 'string' && config[field].trim() === '')) {
            return { valid: false, message: `${label}不能为空` };
        }
    }
    
    const numberRanges = {
        'futu_port': { min: 1, max: 65535, label: '富途API端口' },
        'update_interval': { min: 5, max: 3600, label: '更新间隔' },
        'price_change_threshold': { min: 0, max: 50, label: '价格变化阈值' },
        'volume_surge_threshold': { min: 1, max: 20, label: '成交量激增阈值' }
    };
    
    for (const [field, range] of Object.entries(numberRanges)) {
        const value = config[field];
        if (value !== null && value !== undefined) {
            if (value < range.min || value > range.max) {
                return { valid: false, message: `${range.label}必须在${range.min}-${range.max}之间` };
            }
        }
    }
    
    return { valid: true };
}

// ==================== 确认对话框 ====================

function showConfirmDialog(title, message, callback) {
    document.getElementById('confirmModalTitle').textContent = title;
    document.getElementById('confirmModalBody').textContent = message;
    
    const confirmBtn = document.getElementById('confirmModalConfirm');
    confirmBtn.onclick = function() {
        confirmModal.hide();
        callback();
    };
    confirmModal.show();
}

function handleConfirmAction() {
    // 由 showConfirmDialog 中设置的 onclick 处理
}

// ==================== 加载状态 ====================

function showLoading(message = '处理中，请稍候...') {
    if (typeof TradeUtils !== 'undefined' && TradeUtils.showLoading) {
        TradeUtils.showLoading(message);
        return;
    }
    document.getElementById('loading-message').textContent = message;
    loadingModal.show();
}

function hideLoading() {
    if (typeof TradeUtils !== 'undefined' && TradeUtils.hideLoading) {
        TradeUtils.hideLoading();
        return;
    }
    loadingModal.hide();
}

// ==================== Toast 消息 ====================

function showToast(title, message, type = 'info') {
    if (typeof TradeUtils !== 'undefined' && TradeUtils.showToast) {
        TradeUtils.showToast(title, message, type);
        return;
    }
    
    const toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
        console.log(`[${type}] ${title}: ${message}`);
        return;
    }
    
    const toastId = 'toast-' + Date.now();
    const typeConfig = {
        success: { bg: 'bg-success', icon: 'fa-check-circle' },
        danger: { bg: 'bg-danger', icon: 'fa-exclamation-circle' },
        warning: { bg: 'bg-warning', icon: 'fa-exclamation-triangle' },
        info: { bg: 'bg-info', icon: 'fa-info-circle' }
    };
    
    const config = typeConfig[type] || typeConfig.info;
    const toastHtml = `
        <div class="toast" id="${toastId}" role="alert">
            <div class="toast-header ${config.bg} text-white">
                <i class="fas ${config.icon} me-2"></i>
                <strong class="me-auto">${title}</strong>
                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast"></button>
            </div>
            <div class="toast-body">${message}</div>
        </div>
    `;
    
    toastContainer.insertAdjacentHTML('beforeend', toastHtml);
    const toastElement = document.getElementById(toastId);
    const toast = new bootstrap.Toast(toastElement, { autohide: true, delay: 5000 });
    toast.show();
    toastElement.addEventListener('hidden.bs.toast', () => toastElement.remove());
}

// ==================== 工具函数 ====================

function formatDateTime(timestamp) {
    try {
        const date = new Date(timestamp);
        return date.toLocaleString('zh-CN', {
            year: 'numeric', month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit', second: '2-digit'
        });
    } catch (error) {
        return timestamp;
    }
}

function formatTime(timestamp) {
    try {
        const date = new Date(timestamp);
        return date.toLocaleTimeString('zh-CN', {
            hour: '2-digit', minute: '2-digit', second: '2-digit'
        });
    } catch (error) {
        return timestamp;
    }
}

console.log('系统配置管理 - 验证模块加载完成');
