/**
 * 简化版富途量化交易系统 - 公共工具库
 * 统一的工具函数和UI组件
 */

// ============================================================
// 全局命名空间
// ============================================================
const TradeUtils = {
    // 版本信息
    version: '1.0.0',
    
    // 模态框引用（由各页面初始化）
    _loadingModal: null,
    _loadingCounter: 0,
    
    // ========================================================
    // 初始化方法
    // ========================================================
    
    /**
     * 初始化公共组件
     * @param {Object} options - 配置选项
     */
    init(options = {}) {
        console.log('TradeUtils 初始化...');
        
        // 初始化加载模态框
        const loadingModalEl = document.getElementById('loadingModal');
        if (loadingModalEl) {
            this._loadingModal = new bootstrap.Modal(loadingModalEl);
        }
        
        console.log('TradeUtils 初始化完成');
    },
    
    // ========================================================
    // 消息提示
    // ========================================================
    
    /**
     * 显示Toast消息
     * @param {string} title - 标题
     * @param {string} message - 消息内容
     * @param {string} type - 类型: success/danger/warning/info
     */
    showToast(title, message, type = 'info') {
        let toastContainer = document.getElementById('toast-container');
        
        // 如果容器不存在，创建一个
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'toast-container';
            toastContainer.className = 'position-fixed top-0 end-0 p-3';
            toastContainer.style.zIndex = '1100';
            document.body.appendChild(toastContainer);
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
            <div class="toast" id="${toastId}" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="toast-header ${config.bg} text-white">
                    <i class="fas ${config.icon} me-2"></i>
                    <strong class="me-auto">${title}</strong>
                    <small class="text-white-50">${this.formatTime(new Date().toISOString())}</small>
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
    },
    
    // ========================================================
    // 加载状态
    // ========================================================
    
    /**
     * 显示加载中状态
     * @param {string} message - 加载消息
     */
    showLoading(message = '处理中，请稍候...') {
        this._loadingCounter++;
        
        const loadingMessage = document.getElementById('loading-message');
        if (loadingMessage) {
            loadingMessage.textContent = message;
        }
        
        // 只有第一次调用时才显示模态框
        if (this._loadingCounter === 1 && this._loadingModal) {
            this._loadingModal.show();
        }
        
        console.log(`showLoading: ${message}, counter: ${this._loadingCounter}`);
    },
    
    /**
     * 隐藏加载中状态
     */
    hideLoading() {
        this._loadingCounter = Math.max(0, this._loadingCounter - 1);
        console.log(`hideLoading: counter: ${this._loadingCounter}`);
        
        // 只有当所有加载操作完成时才隐藏模态框
        if (this._loadingCounter === 0 && this._loadingModal) {
            this._loadingModal.hide();
        }
    },
    
    /**
     * 强制隐藏加载状态（重置计数器）
     */
    forceHideLoading() {
        this._loadingCounter = 0;
        if (this._loadingModal) {
            this._loadingModal.hide();
        }
    },
    
    // ========================================================
    // 格式化函数
    // ========================================================
    
    /**
     * 格式化价格
     * @param {number} price - 价格
     * @returns {string} 格式化后的价格
     */
    formatPrice(price) {
        if (price == null || price === '' || price === 0 || isNaN(price)) {
            return '-';
        }
        try {
            const numPrice = parseFloat(price);
            if (isNaN(numPrice) || numPrice === 0) {
                return '-';
            }
            return numPrice.toFixed(2);
        } catch (e) {
            return '-';
        }
    },
    
    /**
     * 格式化百分比
     * @param {number} percent - 百分比值
     * @returns {string} 格式化后的百分比
     */
    formatPercent(percent) {
        if (percent == null || percent === '' || isNaN(percent)) {
            return '0.00%';
        }
        try {
            const numPercent = parseFloat(percent);
            if (isNaN(numPercent)) {
                return '0.00%';
            }
            return numPercent.toFixed(2) + '%';
        } catch (e) {
            return '0.00%';
        }
    },
    
    /**
     * 格式化成交量
     * @param {number} volume - 成交量
     * @returns {string} 格式化后的成交量
     */
    formatVolume(volume) {
        if (volume == null || volume === 0) return '-';
        
        if (volume >= 1000000) {
            return (volume / 1000000).toFixed(1) + 'M';
        } else if (volume >= 1000) {
            return (volume / 1000).toFixed(1) + 'K';
        } else {
            return volume.toString();
        }
    },
    
    /**
     * 格式化时间戳（完整格式）
     * @param {string} timestamp - ISO时间戳
     * @returns {string} 格式化后的时间
     */
    formatTimestamp(timestamp) {
        try {
            const date = new Date(timestamp);
            return date.toLocaleString('zh-CN', {
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
        } catch (error) {
            return timestamp;
        }
    },
    
    /**
     * 格式化时间（简短格式）
     * @param {string} timestamp - ISO时间戳
     * @returns {string} 格式化后的时间
     */
    formatTime(timestamp) {
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
    },
    
    /**
     * 格式化日期时间（完整格式）
     * @param {string} timestamp - ISO时间戳
     * @returns {string} 格式化后的日期时间
     */
    formatDateTime(timestamp) {
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
    },
    
    /**
     * 格式化数字（千分位）
     * @param {number} num - 数字
     * @returns {string} 格式化后的数字
     */
    formatNumber(num) {
        if (num == null) return '-';
        return parseFloat(num).toLocaleString('zh-CN');
    },
    
    /**
     * 格式化相对时间
     * @param {string} isoString - ISO时间字符串
     * @returns {string} 相对时间描述
     */
    formatRelativeTime(isoString) {
        if (!isoString) return '--';
        
        try {
            const date = new Date(isoString);
            const now = new Date();
            const diff = now - date;
            
            if (diff < 60000) {
                return '刚刚';
            } else if (diff < 3600000) {
                return Math.floor(diff / 60000) + '分钟前';
            } else if (diff < 86400000) {
                return Math.floor(diff / 3600000) + '小时前';
            } else {
                return date.toLocaleDateString();
            }
        } catch (error) {
            return '--';
        }
    },
    
    // ========================================================
    // API 调用封装
    // ========================================================
    
    /**
     * 发起API请求
     * @param {string} url - API地址
     * @param {Object} options - 请求选项
     * @returns {Promise<Object>} API响应
     */
    async apiCall(url, options = {}) {
        const defaultOptions = {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        };
        
        const mergedOptions = { ...defaultOptions, ...options };
        
        // 如果有body且是对象，转为JSON
        if (mergedOptions.body && typeof mergedOptions.body === 'object') {
            mergedOptions.body = JSON.stringify(mergedOptions.body);
        }
        
        try {
            const response = await fetch(url, mergedOptions);
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('API调用失败:', error);
            return {
                success: false,
                message: '网络请求失败: ' + error.message
            };
        }
    },
    
    /**
     * GET请求
     * @param {string} url - API地址
     * @returns {Promise<Object>} API响应
     */
    async get(url) {
        return this.apiCall(url, { method: 'GET' });
    },
    
    /**
     * POST请求
     * @param {string} url - API地址
     * @param {Object} data - 请求数据
     * @returns {Promise<Object>} API响应
     */
    async post(url, data = {}) {
        return this.apiCall(url, { 
            method: 'POST',
            body: data
        });
    },
    
    /**
     * PUT请求
     * @param {string} url - API地址
     * @param {Object} data - 请求数据
     * @returns {Promise<Object>} API响应
     */
    async put(url, data = {}) {
        return this.apiCall(url, { 
            method: 'PUT',
            body: data
        });
    },
    
    /**
     * DELETE请求
     * @param {string} url - API地址
     * @returns {Promise<Object>} API响应
     */
    async delete(url) {
        return this.apiCall(url, { method: 'DELETE' });
    },
    
    // ========================================================
    // 系统错误处理
    // ========================================================
    
    /**
     * 显示系统错误
     * @param {string} title - 错误标题
     * @param {string} message - 错误消息
     * @param {string} type - 类型: danger/warning/info
     */
    showSystemError(title, message, type = 'danger') {
        // 移除已存在的系统错误提示
        this.hideSystemError();
        
        const typeConfig = {
            danger: { bg: 'alert-danger', icon: 'fa-exclamation-triangle' },
            warning: { bg: 'alert-warning', icon: 'fa-exclamation-circle' },
            info: { bg: 'alert-info', icon: 'fa-info-circle' }
        };
        
        const config = typeConfig[type] || typeConfig.danger;
        
        const errorHtml = `
            <div class="alert ${config.bg} alert-dismissible fade show system-error-alert" role="alert" 
                 style="position: fixed; top: 70px; left: 50%; transform: translateX(-50%); 
                        z-index: 1050; max-width: 90%; min-width: 400px;">
                <div class="d-flex align-items-start">
                    <i class="fas ${config.icon} me-2 mt-1"></i>
                    <div class="flex-grow-1">
                        <h6 class="alert-heading mb-1">${title}</h6>
                        <div>${message}</div>
                    </div>
                    <button type="button" class="btn-close" onclick="TradeUtils.hideSystemError()"></button>
                </div>
            </div>
        `;
        
        document.body.insertAdjacentHTML('beforeend', errorHtml);
        
        // 自动隐藏（除非是错误类型）
        if (type !== 'danger') {
            setTimeout(() => {
                this.hideSystemError();
            }, 10000);
        }
    },
    
    /**
     * 隐藏系统错误
     */
    hideSystemError() {
        const errorAlert = document.querySelector('.system-error-alert');
        if (errorAlert) {
            errorAlert.remove();
        }
    },
    
    /**
     * 显示详细错误信息
     * @param {string} title - 错误标题
     * @param {Array} errors - 错误列表
     * @param {Array} suggestions - 建议列表
     */
    showDetailedError(title, errors, suggestions = []) {
        const errorList = errors.map(error => `<li>${error}</li>`).join('');
        const suggestionList = suggestions.length > 0 ? 
            `<div class="mt-2"><strong>建议解决方案：</strong><ul class="mb-0">${suggestions.map(s => `<li>${s}</li>`).join('')}</ul></div>` : 
            '';
        
        const message = `
            <div>
                <strong>错误详情：</strong>
                <ul class="mb-2">${errorList}</ul>
                ${suggestionList}
            </div>
        `;
        
        this.showSystemError(title, message, 'danger');
    },
    
    /**
     * 显示连接错误
     */
    showConnectionError() {
        const suggestions = [
            '检查富途牛牛客户端是否已启动并登录',
            '确认OpenAPI已开启（富途牛牛 → 设置 → API开发者）',
            '检查网络连接是否正常',
            '确认API服务器地址和端口配置正确'
        ];
        
        this.showDetailedError(
            '连接失败', 
            ['无法连接到富途API服务'], 
            suggestions
        );
    },
    
    // ========================================================
    // 按钮状态管理
    // ========================================================
    
    /**
     * 设置按钮加载状态
     * @param {HTMLElement|string} button - 按钮元素或选择器
     * @param {boolean} loading - 是否加载中
     */
    setButtonLoading(button, loading) {
        const btn = typeof button === 'string' ? document.querySelector(button) : button;
        if (!btn) return;
        
        if (loading) {
            btn.classList.add('btn-loading');
            btn.disabled = true;
        } else {
            btn.classList.remove('btn-loading');
            btn.disabled = false;
        }
    },
    
    // ========================================================
    // WebSocket 连接状态
    // ========================================================
    
    /**
     * 更新连接状态显示
     * @param {boolean} connected - 是否已连接
     */
    updateConnectionStatus(connected) {
        let statusElement = document.querySelector('.connection-status');
        
        if (!statusElement) {
            statusElement = document.createElement('div');
            statusElement.className = 'connection-status';
            document.body.appendChild(statusElement);
        }
        
        if (connected) {
            statusElement.className = 'connection-status connected';
            statusElement.innerHTML = '<i class="fas fa-wifi"></i> 已连接';
        } else {
            statusElement.className = 'connection-status disconnected';
            statusElement.innerHTML = '<i class="fas fa-wifi"></i> 已断开';
        }
    },
    
    // ========================================================
    // 工具方法
    // ========================================================
    
    /**
     * 获取URL参数
     * @param {string} name - 参数名
     * @returns {string|null} 参数值
     */
    getUrlParam(name) {
        const urlParams = new URLSearchParams(window.location.search);
        return urlParams.get(name);
    },
    
    /**
     * 防抖函数
     * @param {Function} func - 要执行的函数
     * @param {number} wait - 等待时间(毫秒)
     * @returns {Function} 防抖后的函数
     */
    debounce(func, wait = 300) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },
    
    /**
     * 节流函数
     * @param {Function} func - 要执行的函数
     * @param {number} limit - 间隔时间(毫秒)
     * @returns {Function} 节流后的函数
     */
    throttle(func, limit = 300) {
        let inThrottle;
        return function(...args) {
            if (!inThrottle) {
                func.apply(this, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    },
    
    /**
     * 深拷贝对象
     * @param {Object} obj - 要拷贝的对象
     * @returns {Object} 拷贝后的对象
     */
    deepCopy(obj) {
        return JSON.parse(JSON.stringify(obj));
    },
    
    /**
     * 生成唯一ID
     * @param {string} prefix - ID前缀
     * @returns {string} 唯一ID
     */
    generateId(prefix = 'id') {
        return `${prefix}-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    }
};

// ============================================================
// 全局快捷方法（兼容旧代码）
// ============================================================

// 为了向后兼容，将常用方法暴露到全局
window.showToast = (title, message, type) => TradeUtils.showToast(title, message, type);
window.showLoading = (message) => TradeUtils.showLoading(message);
window.hideLoading = () => TradeUtils.hideLoading();
window.showSystemError = (title, message, type) => TradeUtils.showSystemError(title, message, type);
window.hideSystemError = () => TradeUtils.hideSystemError();
window.showDetailedError = (title, errors, suggestions) => TradeUtils.showDetailedError(title, errors, suggestions);
window.showConnectionError = () => TradeUtils.showConnectionError();

// 格式化函数
window.formatPrice = (price) => TradeUtils.formatPrice(price);
window.formatPercent = (percent) => TradeUtils.formatPercent(percent);
window.formatVolume = (volume) => TradeUtils.formatVolume(volume);
window.formatTimestamp = (timestamp) => TradeUtils.formatTimestamp(timestamp);
window.formatTime = (timestamp) => TradeUtils.formatTime(timestamp);
window.formatDateTime = (timestamp) => TradeUtils.formatDateTime(timestamp);
window.formatNumber = (num) => TradeUtils.formatNumber(num);

// 暴露到全局
window.TradeUtils = TradeUtils;

console.log('TradeUtils 公共工具库加载完成 v' + TradeUtils.version);
