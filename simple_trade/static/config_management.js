/**
 * 系统配置管理前端脚本
 */

// 全局变量
let loadingModal = null;
let confirmModal = null;
let currentConfig = {};
let originalConfig = {};

// 配置字段映射
const CONFIG_FIELDS = [
    // 基础配置
    'futu_host', 'futu_port', 'database_path', 'update_interval', 'auto_trade',
    // 交易参数
    'price_change_threshold', 'volume_surge_threshold',
    // 数据限制
    'max_stocks_monitor', 'max_subscription_stocks', 'max_active_stocks',
    'max_plate_stocks', 'max_target_plates', 'max_quality_plates',
    // K线和历史数据
    'kline_days', 'max_kline_records', 'max_recent_signals',
    'stocks_per_plate', 'max_stocks_for_kline_update', 'max_stocks_for_trading'
];

// 初始化
document.addEventListener('DOMContentLoaded', function() {
    initializeConfigPage();
});

/**
 * 初始化配置页面
 */
function initializeConfigPage() {
    console.log('初始化系统配置管理页面...');
    
    // 初始化模态框
    loadingModal = new bootstrap.Modal(document.getElementById('loadingModal'));
    confirmModal = new bootstrap.Modal(document.getElementById('confirmModal'));
    
    // 绑定事件
    bindEvents();
    
    // 加载当前配置
    loadCurrentConfig();
    
    console.log('配置管理页面初始化完成');
}

/**
 * 绑定事件
 */
function bindEvents() {
    // 保存配置按钮
    document.getElementById('btn-save-config').addEventListener('click', handleSaveConfig);
    
    // 恢复默认按钮
    document.getElementById('btn-reset-config').addEventListener('click', handleResetConfig);
    
    // 确认模态框
    document.getElementById('confirmModalConfirm').addEventListener('click', handleConfirmAction);
    
    // 表单验证事件
    bindFormValidation();
}

/**
 * 绑定表单验证事件
 */
function bindFormValidation() {
    // 数字输入验证
    const numberInputs = document.querySelectorAll('input[type="number"]');
    numberInputs.forEach(input => {
        input.addEventListener('change', validateNumberInput);
        input.addEventListener('blur', validateNumberInput);
    });
    
    // 端口号特殊验证
    const portInput = document.getElementById('futu_port');
    if (portInput) {
        portInput.addEventListener('change', function() {
            const value = parseInt(this.value);
            if (value && (value < 1 || value > 65535)) {
                showToast('验证错误', '端口号必须在1-65535之间', 'warning');
                this.value = 11111; // 恢复默认值
            }
        });
    }
}

/**
 * 验证数字输入
 */
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

/**
 * 加载当前配置
 */
async function loadCurrentConfig() {
    console.log('开始加载配置...');
    showLoading('正在加载配置...');
    
    try {
        const response = await fetch('/api/config');
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const result = await response.json();
        console.log('API响应:', result);
        
        if (result.success) {
            currentConfig = result.data;
            originalConfig = JSON.parse(JSON.stringify(result.data)); // 深拷贝
            
            console.log('配置数据:', currentConfig);
            
            // 填充表单
            populateConfigForm(currentConfig);
            
            // 更新状态信息
            updateConfigStatus(result.meta || {});
            
            showToast('成功', '配置加载成功', 'success');
            console.log('配置加载完成');
        } else {
            console.error('API返回错误:', result);
            showToast('错误', `加载配置失败: ${result.message}`, 'danger');
            
            // 设置错误状态
            const status = document.getElementById('config-status');
            if (status) {
                status.innerHTML = '<span class="text-danger"><i class="fas fa-exclamation-circle me-1"></i>加载失败</span>';
            }
        }
    } catch (error) {
        console.error('加载配置异常:', error);
        showToast('错误', `加载配置时发生网络错误: ${error.message}`, 'danger');
        
        // 设置错误状态
        const status = document.getElementById('config-status');
        if (status) {
            status.innerHTML = '<span class="text-danger"><i class="fas fa-exclamation-circle me-1"></i>网络错误</span>';
        }
    } finally {
        console.log('准备隐藏加载模态框...');
        hideLoading();
        console.log('配置加载流程完成');
    }
}

/**
 * 填充配置表单
 */
function populateConfigForm(config) {
    CONFIG_FIELDS.forEach(field => {
        const element = document.getElementById(field);
        if (element) {
            const value = config[field];
            
            if (element.type === 'checkbox') {
                element.checked = Boolean(value);
            } else if (element.type === 'number') {
                element.value = value || '';
            } else {
                element.value = value || '';
            }
        }
    });
    
    console.log('配置表单已填充:', config);
}

/**
 * 从表单获取配置
 */
function getConfigFromForm() {
    const config = {};
    
    CONFIG_FIELDS.forEach(field => {
        const element = document.getElementById(field);
        if (element) {
            if (element.type === 'checkbox') {
                config[field] = element.checked;
            } else if (element.type === 'number') {
                const value = parseFloat(element.value);
                config[field] = isNaN(value) ? null : value;
            } else {
                config[field] = element.value.trim() || null;
            }
        }
    });
    
    return config;
}

/**
 * 更新配置状态
 */
function updateConfigStatus(meta) {
    try {
        console.log('更新配置状态:', meta);
        
        // 配置文件路径
        const configPath = document.getElementById('config-file-path');
        if (configPath) {
            configPath.textContent = meta.config_path || 'simple_trade/config.json';
        }
        
        // 最后修改时间
        const lastModified = document.getElementById('config-last-modified');
        if (lastModified) {
            lastModified.textContent = meta.last_modified ? 
                formatDateTime(meta.last_modified) : '未知';
        }
        
        // 配置状态 - 确保正确更新
        const status = document.getElementById('config-status');
        if (status) {
            status.innerHTML = '<span class="text-success"><i class="fas fa-check-circle me-1"></i>已加载</span>';
            console.log('配置状态已更新为已加载');
        } else {
            console.error('未找到配置状态元素: config-status');
        }
    } catch (error) {
        console.error('更新配置状态失败:', error);
    }
}

/**
 * 处理保存配置
 */
function handleSaveConfig() {
    // 获取表单数据
    const newConfig = getConfigFromForm();
    
    // 验证配置
    const validation = validateConfig(newConfig);
    if (!validation.valid) {
        showToast('验证失败', validation.message, 'danger');
        return;
    }
    
    // 检查是否有变化
    if (JSON.stringify(newConfig) === JSON.stringify(originalConfig)) {
        showToast('提示', '配置没有变化', 'info');
        return;
    }
    
    // 显示确认对话框
    showConfirmDialog(
        '保存配置',
        '确定要保存配置更改吗？保存后将立即生效。',
        () => saveConfig(newConfig)
    );
}

/**
 * 验证配置
 */
function validateConfig(config) {
    // 必填字段验证
    const requiredFields = {
        'futu_host': '富途API主机地址',
        'futu_port': '富途API端口',
        'update_interval': '更新间隔'
    };
    
    for (const [field, label] of Object.entries(requiredFields)) {
        if (!config[field] || (typeof config[field] === 'string' && config[field].trim() === '')) {
            return {
                valid: false,
                message: `${label}不能为空`
            };
        }
    }
    
    // 数值范围验证
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
                return {
                    valid: false,
                    message: `${range.label}必须在${range.min}-${range.max}之间`
                };
            }
        }
    }
    
    return { valid: true };
}

/**
 * 保存配置
 */
async function saveConfig(config) {
    showLoading('正在保存配置...');
    
    try {
        const response = await fetch('/api/config', {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(config)
        });
        
        const result = await response.json();
        
        if (result.success) {
            // 更新当前配置
            currentConfig = config;
            originalConfig = JSON.parse(JSON.stringify(config));
            
            showToast('成功', '配置保存成功', 'success');
            
            // 更新状态
            if (result.meta) {
                updateConfigStatus(result.meta);
            }
            
            // 显示重启提示
            if (result.requires_restart) {
                showToast('提示', '部分配置更改需要重启系统后生效', 'warning');
            }
        } else {
            showToast('错误', `保存配置失败: ${result.message}`, 'danger');
        }
    } catch (error) {
        console.error('保存配置异常:', error);
        showToast('错误', '保存配置时发生网络错误', 'danger');
    } finally {
        hideLoading();
    }
}

/**
 * 处理重置配置
 */
function handleResetConfig() {
    showConfirmDialog(
        '恢复默认配置',
        '确定要恢复默认配置吗？这将清除所有自定义设置。',
        () => resetConfig()
    );
}

/**
 * 重置配置到默认值
 */
async function resetConfig() {
    showLoading('正在恢复默认配置...');
    
    try {
        const response = await fetch('/api/config/reset', {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (result.success) {
            // 重新加载配置
            await loadCurrentConfig();
            
            showToast('成功', '已恢复默认配置', 'success');
        } else {
            showToast('错误', `恢复默认配置失败: ${result.message}`, 'danger');
        }
    } catch (error) {
        console.error('重置配置异常:', error);
        showToast('错误', '重置配置时发生网络错误', 'danger');
    } finally {
        hideLoading();
    }
}

/**
 * 显示确认对话框
 */
function showConfirmDialog(title, message, callback) {
    document.getElementById('confirmModalTitle').textContent = title;
    document.getElementById('confirmModalBody').textContent = message;
    
    // 清除之前的事件监听器
    const confirmBtn = document.getElementById('confirmModalConfirm');
    confirmBtn.onclick = null;
    
    // 设置新的回调
    confirmBtn.onclick = function() {
        confirmModal.hide();
        callback();
    };
    
    confirmModal.show();
}

/**
 * 处理确认操作
 */
function handleConfirmAction() {
    // 这个函数由showConfirmDialog中设置的onclick处理
}

/**
 * 显示加载中 - 优先使用全局函数
 */
function showLoading(message = '处理中，请稍候...') {
    if (typeof TradeUtils !== 'undefined' && TradeUtils.showLoading) {
        TradeUtils.showLoading(message);
        return;
    }
    // 降级使用本地模态框
    document.getElementById('loading-message').textContent = message;
    loadingModal.show();
}

/**
 * 隐藏加载中 - 优先使用全局函数
 */
function hideLoading() {
    if (typeof TradeUtils !== 'undefined' && TradeUtils.hideLoading) {
        TradeUtils.hideLoading();
        return;
    }
    // 降级使用本地模态框
    loadingModal.hide();
}

/**
 * 显示Toast消息 - 优先使用全局函数
 */
function showToast(title, message, type = 'info') {
    // 优先使用全局 TradeUtils.showToast
    if (typeof TradeUtils !== 'undefined' && TradeUtils.showToast) {
        TradeUtils.showToast(title, message, type);
        return;
    }
    // 降级使用本地实现
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

// ========== 工具函数 ==========

/**
 * 格式化日期时间
 */
function formatDateTime(timestamp) {
    try {
        const date = new Date(timestamp);
        return date.toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    } catch (error) {
        return timestamp;
    }
}

/**
 * 格式化时间（简短）
 */
function formatTime(timestamp) {
    try {
        const date = new Date(timestamp);
        return date.toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    } catch (error) {
        return timestamp;
    }
}

/**
 * 检查配置是否有变化
 */
function hasConfigChanged() {
    const currentFormConfig = getConfigFromForm();
    return JSON.stringify(currentFormConfig) !== JSON.stringify(originalConfig);
}

/**
 * 页面离开前检查未保存的更改
 */
window.addEventListener('beforeunload', function(e) {
    if (hasConfigChanged()) {
        e.preventDefault();
        e.returnValue = '您有未保存的配置更改，确定要离开吗？';
    }
});

// 导出全局函数
window.showToast = showToast;
window.showLoading = showLoading;
window.hideLoading = hideLoading;
window.loadCurrentConfig = loadCurrentConfig;

console.log('系统配置管理前端脚本加载完成');
