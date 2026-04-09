/**
 * 系统配置管理 - 表单加载与保存模块
 * 功能：配置加载、表单填充、保存、重置
 */

// 全局变量
let loadingModal = null;
let confirmModal = null;
let currentConfig = {};
let originalConfig = {};

// 配置字段映射
const CONFIG_FIELDS = [
    'futu_host', 'futu_port', 'database_path', 'update_interval', 'auto_trade',
    'price_change_threshold', 'volume_surge_threshold',
    'max_stocks_monitor', 'max_subscription_stocks', 'max_active_stocks',
    'max_plate_stocks', 'max_target_plates', 'max_quality_plates',
    'kline_days', 'max_kline_records', 'max_recent_signals',
    'stocks_per_plate', 'max_stocks_for_kline_update', 'max_stocks_for_trading'
];

// 初始化
document.addEventListener('DOMContentLoaded', function() {
    initializeConfigPage();
});

function initializeConfigPage() {
    console.log('初始化系统配置管理页面...');
    loadingModal = new bootstrap.Modal(document.getElementById('loadingModal'));
    confirmModal = new bootstrap.Modal(document.getElementById('confirmModal'));
    bindEvents();
    loadCurrentConfig();
    console.log('配置管理页面初始化完成');
}

function bindEvents() {
    document.getElementById('btn-save-config').addEventListener('click', handleSaveConfig);
    document.getElementById('btn-reset-config').addEventListener('click', handleResetConfig);
    document.getElementById('confirmModalConfirm').addEventListener('click', handleConfirmAction);
    bindFormValidation();
}

// ==================== 配置加载 ====================

async function loadCurrentConfig() {
    console.log('开始加载配置...');
    showLoading('正在加载配置...');
    
    try {
        const response = await fetch('/api/config');
        if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        
        const result = await response.json();
        
        if (result.success) {
            currentConfig = result.data;
            originalConfig = JSON.parse(JSON.stringify(result.data));
            populateConfigForm(currentConfig);
            updateConfigStatus(result.meta || {});
            showToast('成功', '配置加载成功', 'success');
        } else {
            showToast('错误', `加载配置失败: ${result.message}`, 'danger');
            setStatusError('加载失败');
        }
    } catch (error) {
        console.error('加载配置异常:', error);
        showToast('错误', `加载配置时发生网络错误: ${error.message}`, 'danger');
        setStatusError('网络错误');
    } finally {
        hideLoading();
    }
}

function setStatusError(text) {
    const status = document.getElementById('config-status');
    if (status) status.innerHTML = `<span class="text-danger"><i class="fas fa-exclamation-circle me-1"></i>${text}</span>`;
}

function populateConfigForm(config) {
    CONFIG_FIELDS.forEach(field => {
        const element = document.getElementById(field);
        if (element) {
            const value = config[field];
            if (element.type === 'checkbox') element.checked = Boolean(value);
            else if (element.type === 'number') element.value = value || '';
            else element.value = value || '';
        }
    });
}

function getConfigFromForm() {
    const config = {};
    CONFIG_FIELDS.forEach(field => {
        const element = document.getElementById(field);
        if (element) {
            if (element.type === 'checkbox') config[field] = element.checked;
            else if (element.type === 'number') {
                const value = parseFloat(element.value);
                config[field] = isNaN(value) ? null : value;
            } else {
                config[field] = element.value.trim() || null;
            }
        }
    });
    return config;
}

function updateConfigStatus(meta) {
    try {
        const configPath = document.getElementById('config-file-path');
        if (configPath) configPath.textContent = meta.config_path || 'simple_trade/config.json';
        
        const lastModified = document.getElementById('config-last-modified');
        if (lastModified) lastModified.textContent = meta.last_modified ? formatDateTime(meta.last_modified) : '未知';
        
        const status = document.getElementById('config-status');
        if (status) status.innerHTML = '<span class="text-success"><i class="fas fa-check-circle me-1"></i>已加载</span>';
    } catch (error) {
        console.error('更新配置状态失败:', error);
    }
}

// ==================== 配置保存 ====================

function handleSaveConfig() {
    const newConfig = getConfigFromForm();
    const validation = validateConfig(newConfig);
    if (!validation.valid) {
        showToast('验证失败', validation.message, 'danger');
        return;
    }
    if (JSON.stringify(newConfig) === JSON.stringify(originalConfig)) {
        showToast('提示', '配置没有变化', 'info');
        return;
    }
    showConfirmDialog('保存配置', '确定要保存配置更改吗？保存后将立即生效。', () => saveConfig(newConfig));
}

async function saveConfig(config) {
    showLoading('正在保存配置...');
    try {
        const response = await fetch('/api/config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        const result = await response.json();
        
        if (result.success) {
            currentConfig = config;
            originalConfig = JSON.parse(JSON.stringify(config));
            showToast('成功', '配置保存成功', 'success');
            if (result.meta) updateConfigStatus(result.meta);
            if (result.requires_restart) showToast('提示', '部分配置更改需要重启系统后生效', 'warning');
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

// ==================== 配置重置 ====================

function handleResetConfig() {
    showConfirmDialog('恢复默认配置', '确定要恢复默认配置吗？这将清除所有自定义设置。', () => resetConfig());
}

async function resetConfig() {
    showLoading('正在恢复默认配置...');
    try {
        const response = await fetch('/api/config/reset', { method: 'POST' });
        const result = await response.json();
        if (result.success) {
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

// ==================== 页面离开检查 ====================

function hasConfigChanged() {
    return JSON.stringify(getConfigFromForm()) !== JSON.stringify(originalConfig);
}

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

console.log('系统配置管理 - 表单模块加载完成');
