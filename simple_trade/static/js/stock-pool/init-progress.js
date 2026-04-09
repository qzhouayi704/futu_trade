/**
 * 股票池管理 - 初始化进度模块（入口文件）
 * 功能：页面初始化、进度条管理、工具函数、浏览板块、优先级编辑
 * 
 * 依赖：
 * - plate-manager.js (板块管理)
 * - stock-manager.js (股票管理)
 * - pagination.js (分页)
 */

// ==================== 全局状态 ====================
const StockPoolState = {
    loadingModal: null,
    deleteModal: null,
    browsePlatesModal: null,
    initProgressModal: null,
    currentDeleteAction: null,
    platesData: [],
    filteredPlates: [],
    stocksData: [],
    filteredStocks: [],
    stocksTotalCount: 0,
    availablePlatesData: [],
    filteredAvailablePlates: [],
    selectedPlates: new Set(),
    loadingCounter: 0,
    progressPollInterval: null,
    initializationInProgress: false,
    platesPagination: { currentPage: 1, pageSize: 20, totalItems: 0, filteredData: [] },
    stocksPagination: { currentPage: 1, pageSize: 20, totalItems: 0, filteredData: [] }
};

// ==================== 页面初始化 ====================
document.addEventListener('DOMContentLoaded', function() {
    initializeStockPoolPage();
});

/**
 * 初始化股票池管理页面
 */
function initializeStockPoolPage() {
    console.log('初始化股票池管理页面...');

    try {
        const loadingModalEl = document.getElementById('loadingModal');
        const deleteModalEl = document.getElementById('deleteModal');
        const browsePlatesModalEl = document.getElementById('browsePlatesModal');
        const initProgressModalEl = document.getElementById('initProgressModal');

        if (!loadingModalEl || typeof bootstrap === 'undefined') {
            console.error('模态框元素或 Bootstrap 未加载');
            return;
        }

        StockPoolState.loadingModal = new bootstrap.Modal(loadingModalEl);
        StockPoolState.deleteModal = new bootstrap.Modal(deleteModalEl);
        StockPoolState.browsePlatesModal = new bootstrap.Modal(browsePlatesModalEl);
        StockPoolState.initProgressModal = new bootstrap.Modal(initProgressModalEl);

        console.log('模态框初始化成功');
    } catch (e) {
        console.error('模态框初始化失败:', e);
        return;
    }

    bindEvents();
    loadPageData();
    console.log('股票池管理页面初始化完成');
}

/**
 * 绑定事件
 */
function bindEvents() {
    document.getElementById('add-plate-btn').addEventListener('click', addPlate);
    document.getElementById('refresh-plates').addEventListener('click', loadPlates);
    document.getElementById('browse-plates-btn').addEventListener('click', browsePlates);
    document.getElementById('plate-code-input').addEventListener('keypress', e => { if (e.key === 'Enter') addPlate(); });
    
    document.getElementById('add-stocks-btn').addEventListener('click', addStocks);
    document.getElementById('refresh-stocks').addEventListener('click', loadStocks);
    document.getElementById('stock-codes-input').addEventListener('keypress', e => { if (e.key === 'Enter') addStocks(); });
    
    document.getElementById('search-stocks').addEventListener('input', filterStocks);
    document.getElementById('plate-filter').addEventListener('change', filterStocks);
    document.getElementById('stock-market-filter').addEventListener('change', filterStocks);
    document.getElementById('plate-market-filter').addEventListener('change', filterPlates);
    document.getElementById('plate-type-filter').addEventListener('change', filterPlates);
    
    const priorityFilter = document.getElementById('plate-priority-filter');
    if (priorityFilter) priorityFilter.addEventListener('change', filterPlates);
    
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
    
    const refreshBtn = document.getElementById('refresh-data-btn');
    if (refreshBtn) refreshBtn.addEventListener('click', refreshAllData);
    
    const manualInitBtn = document.getElementById('manual-init-btn');
    if (manualInitBtn) manualInitBtn.addEventListener('click', manualInitStockPool);
    
    const initCancelBtn = document.getElementById('init-cancel-btn');
    if (initCancelBtn) initCancelBtn.addEventListener('click', cancelInitialization);
    
    const initRetryBtn = document.getElementById('init-retry-btn');
    if (initRetryBtn) initRetryBtn.addEventListener('click', retryInitialization);
    
    const initCompleteBtn = document.getElementById('init-complete-btn');
    if (initCompleteBtn) initCompleteBtn.addEventListener('click', () => StockPoolState.initProgressModal.hide());
    
    bindPaginationEvents();
}

/**
 * 加载页面数据
 */
async function loadPageData() {
    try {
        showLoading('加载数据中...');
        await Promise.all([loadPlatesInternal(), loadStocksInternal()]);
        updateStatistics();
    } catch (error) {
        console.error('加载页面数据失败:', error);
        showToast('错误', '加载页面数据失败', 'danger');
    } finally {
        hideLoading();
    }
}

// ==================== 工具函数 ====================

function showLoading(message = '处理中，请稍候...') {
    StockPoolState.loadingCounter++;
    document.getElementById('loading-message').textContent = message;
    if (StockPoolState.loadingCounter === 1) {
        StockPoolState.loadingModal.show();
    }
}

function hideLoading() {
    StockPoolState.loadingCounter = Math.max(0, StockPoolState.loadingCounter - 1);
    if (StockPoolState.loadingCounter === 0) {
        const modalElement = document.getElementById('loadingModal');
        if (!modalElement) return;
        
        const forceHideTimeout = setTimeout(() => forceHideModal(modalElement), 500);
        
        const hiddenHandler = () => {
            clearTimeout(forceHideTimeout);
            modalElement.removeEventListener('hidden.bs.modal', hiddenHandler);
            cleanupModalState();
        };
        
        modalElement.addEventListener('hidden.bs.modal', hiddenHandler);
        
        try {
            if (StockPoolState.loadingModal) StockPoolState.loadingModal.hide();
        } catch (e) {
            clearTimeout(forceHideTimeout);
            forceHideModal(modalElement);
        }
    }
}

function forceHideModal(modalElement) {
    try {
        modalElement.classList.remove('show');
        modalElement.style.display = 'none';
        modalElement.setAttribute('aria-hidden', 'true');
        cleanupModalState();
    } catch (e) {
        console.error('强制隐藏失败:', e);
    }
}

function cleanupModalState() {
    document.body.classList.remove('modal-open');
    document.body.style.overflow = '';
    document.body.style.paddingRight = '';
    document.querySelectorAll('.modal-backdrop').forEach(b => b.remove());
}

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
        <div class="toast" id="${toastId}" role="alert">
            <div class="toast-header ${config.bg} text-white">
                <i class="fas ${config.icon} me-2"></i>
                <strong class="me-auto">${title}</strong>
                <small class="text-white-50">${new Date().toLocaleTimeString()}</small>
                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast"></button>
            </div>
            <div class="toast-body">${message}</div>
        </div>
    `;
    
    toastContainer.insertAdjacentHTML('beforeend', toastHtml);
    
    const toastElement = document.getElementById(toastId);
    const toast = new bootstrap.Toast(toastElement, { autohide: true, delay: type === 'danger' ? 8000 : 5000 });
    toast.show();
    
    toastElement.addEventListener('hidden.bs.toast', () => toastElement.remove());
}

// ==================== 初始化进度 ====================

async function manualInitStockPool() {
    if (StockPoolState.initializationInProgress) {
        showToast('警告', '初始化正在进行中', 'warning');
        return;
    }

    try {
        StockPoolState.initializationInProgress = true;
        resetInitProgressModal();
        StockPoolState.initProgressModal.show();
        
        const response = await fetch('/api/init', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force_refresh: true })
        });
        
        const result = await response.json();
        
        if (result.success) {
            startProgressPolling();
        } else {
            showInitError(result.message || '初始化启动失败');
        }
    } catch (error) {
        console.error('启动初始化失败:', error);
        showInitError('启动初始化请求失败');
    }
}

function resetInitProgressModal() {
    updateProgressBar(0);
    document.getElementById('init-current-action').textContent = '准备初始化...';
    document.getElementById('init-current-step').textContent = '0';
    document.getElementById('init-total-steps').textContent = '0';
    document.getElementById('init-success-alert').style.display = 'none';
    document.getElementById('init-error-alert').style.display = 'none';
    document.getElementById('init-cancel-btn').style.display = 'block';
    document.getElementById('init-complete-btn').style.display = 'none';
    document.getElementById('init-retry-btn').style.display = 'none';
}

function startProgressPolling() {
    if (StockPoolState.progressPollInterval) clearInterval(StockPoolState.progressPollInterval);
    
    StockPoolState.progressPollInterval = setInterval(async () => {
        try {
            const response = await fetch('/api/init/progress');
            const result = await response.json();
            
            if (result.success) {
                const progress = result.data;
                updateProgressDisplay(progress);
                
                if (progress.completed) {
                    stopProgressPolling();
                    handleInitializationComplete(progress);
                }
            }
        } catch (error) {
            console.error('获取进度失败:', error);
        }
    }, 1000);
}

function stopProgressPolling() {
    if (StockPoolState.progressPollInterval) {
        clearInterval(StockPoolState.progressPollInterval);
        StockPoolState.progressPollInterval = null;
    }
}

function updateProgressDisplay(progress) {
    updateProgressBar(progress.progress_percentage);
    document.getElementById('init-current-action').textContent = progress.current_action || '处理中...';
    document.getElementById('init-current-step').textContent = progress.current_step || 0;
    document.getElementById('init-total-steps').textContent = progress.total_steps || 0;
}

function updateProgressBar(percentage) {
    const progressBar = document.getElementById('init-progress-bar');
    const progressText = document.getElementById('init-progress-percentage');
    const safePercentage = Math.max(0, Math.min(100, percentage || 0));
    progressBar.style.width = `${safePercentage}%`;
    progressBar.setAttribute('aria-valuenow', safePercentage);
    progressText.textContent = safePercentage;
}

async function handleInitializationComplete(progress) {
    StockPoolState.initializationInProgress = false;
    if (progress.error) {
        showInitError(progress.error);
    } else {
        await showInitSuccess();
    }
}

async function showInitSuccess() {
    try {
        await loadPageData();
        document.getElementById('init-plates-count').textContent = StockPoolState.platesData.length;
        document.getElementById('init-stocks-count').textContent = StockPoolState.stocksData.length;
        document.getElementById('init-success-alert').style.display = 'block';
        document.getElementById('init-cancel-btn').style.display = 'none';
        document.getElementById('init-complete-btn').style.display = 'block';
        showToast('成功', `股票池初始化完成！`, 'success');
    } catch (error) {
        console.error('加载初始化后数据失败:', error);
        showInitError('初始化完成但数据加载失败');
    }
}

function showInitError(errorMessage) {
    StockPoolState.initializationInProgress = false;
    stopProgressPolling();
    document.getElementById('init-error-message').textContent = errorMessage;
    document.getElementById('init-error-alert').style.display = 'block';
    document.getElementById('init-cancel-btn').style.display = 'none';
    document.getElementById('init-retry-btn').style.display = 'block';
    showToast('错误', `股票池初始化失败: ${errorMessage}`, 'danger');
}

function cancelInitialization() {
    stopProgressPolling();
    StockPoolState.initializationInProgress = false;
    StockPoolState.initProgressModal.hide();
    showToast('信息', '股票池初始化已取消', 'info');
}

function retryInitialization() {
    manualInitStockPool();
}

// ==================== 导出到全局 ====================
window.StockPoolState = StockPoolState;
window.initializeStockPoolPage = initializeStockPoolPage;
window.loadPageData = loadPageData;
window.showLoading = showLoading;
window.hideLoading = hideLoading;
window.showToast = showToast;
window.manualInitStockPool = manualInitStockPool;

console.log('股票池管理页面脚本加载完成');
