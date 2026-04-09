/**
 * 自动交易策略选择器
 * 负责在自动交易页面展示策略下拉框，设置/获取跟随策略
 */

window.AutoTradeStrategySelector = {
    currentStrategyId: null,
    enabledStrategies: [],

    /** 初始化 */
    async init() {
        await this.loadData();
        this._bindEvents();
    },

    /** 加载已启用策略和当前自动交易策略 */
    async loadData() {
        try {
            const [enabledResp, autoTradeResp] = await Promise.all([
                fetch('/api/strategy/enabled'),
                fetch('/api/strategy/auto-trade')
            ]);
            const enabledData = await enabledResp.json();
            const autoTradeData = await autoTradeResp.json();

            if (enabledData.success) {
                this.enabledStrategies = enabledData.data.enabled_strategies || [];
            }
            if (autoTradeData.success) {
                this.currentStrategyId = autoTradeData.data.auto_trade_strategy;
            }
            this.render();
        } catch (e) {
            console.error('[自动交易选择器] 加载数据失败:', e);
        }
    },

    /** 渲染策略选择下拉框 */
    render() {
        const select = document.getElementById('auto-trade-strategy-select');
        if (!select) return;

        let html = '<option value="">-- 不跟随策略 --</option>';
        this.enabledStrategies.forEach(s => {
            const selected = s.strategy_id === this.currentStrategyId ? 'selected' : '';
            html += `<option value="${s.strategy_id}" ${selected}>${s.strategy_name} (${s.preset_name})</option>`;
        });
        select.innerHTML = html;

        // 检查当前策略是否在已启用列表中
        this._checkWarning();
    },

    /** 选择策略 */
    async selectStrategy(strategyId) {
        if (!strategyId) return;
        try {
            const resp = await fetch('/api/strategy/auto-trade', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ strategy_id: strategyId })
            });
            const data = await resp.json();
            if (data.success) {
                this.currentStrategyId = strategyId;
                this._checkWarning();
            } else {
                // 显示错误（复用 trading.js 的 showToast 或 alert）
                if (window.tradingPanel && window.tradingPanel.showToast) {
                    window.tradingPanel.showToast(data.message || '设置失败', 'error');
                } else {
                    alert(data.message || '设置自动交易策略失败');
                }
                await this.loadData(); // 回滚
            }
        } catch (e) {
            console.error('[自动交易选择器] 设置策略失败:', e);
        }
    },

    /** 绑定事件 */
    _bindEvents() {
        const select = document.getElementById('auto-trade-strategy-select');
        if (select) {
            select.addEventListener('change', (e) => {
                this.selectStrategy(e.target.value);
            });
        }
    },

    /** 检查当前策略是否已启用，未启用则显示警告 */
    _checkWarning() {
        const warning = document.getElementById('auto-trade-strategy-warning');
        if (!warning) return;

        if (this.currentStrategyId) {
            const found = this.enabledStrategies.some(s => s.strategy_id === this.currentStrategyId);
            warning.style.display = found ? 'none' : 'inline';
        } else {
            warning.style.display = 'none';
        }
    }
};

// 页面加载后初始化
document.addEventListener('DOMContentLoaded', function() {
    AutoTradeStrategySelector.init();
});
