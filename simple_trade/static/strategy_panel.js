/**
 * 多策略面板交互逻辑
 * 负责策略卡片渲染、启用/禁用、预设切换、信号计数更新
 */

window.StrategyPanel = {
    enabledStrategies: {},
    allStrategies: {},
    autoTradeStrategy: null,

    /** 初始化：加载策略数据并渲染 */
    async init() {
        await this.loadAllStrategies();
        await this.loadEnabledStrategies();
    },

    /** 加载所有可用策略（复用已有 API） */
    async loadAllStrategies() {
        try {
            const resp = await fetch('/api/strategy/list');
            const data = await resp.json();
            if (data.success) {
                this.allStrategies = data.data.strategies || {};
            }
        } catch (e) {
            console.error('[策略面板] 加载策略列表失败:', e);
        }
    },

    /** 加载已启用策略 */
    async loadEnabledStrategies() {
        try {
            const resp = await fetch('/api/strategy/enabled');
            const data = await resp.json();
            if (data.success) {
                const list = data.data.enabled_strategies || [];
                this.enabledStrategies = {};
                list.forEach(s => { this.enabledStrategies[s.strategy_id] = s; });
                this.autoTradeStrategy = data.data.auto_trade_strategy;
                this.renderStrategyCards();
            }
        } catch (e) {
            console.error('[策略面板] 加载已启用策略失败:', e);
        }
    },

    /** 渲染策略卡片列表 */
    renderStrategyCards() {
        const container = document.getElementById('strategy-cards-container');
        if (!container) return;

        const strategyIds = Object.keys(this.allStrategies);
        if (strategyIds.length === 0) {
            container.innerHTML = '<div class="empty-state"><span class="empty-icon">📭</span><p>暂无可用策略</p></div>';
            return;
        }

        container.innerHTML = strategyIds.map(id => this._renderCard(id)).join('');
        this._updateCountBadge();
    },

    /** 渲染单张策略卡片 */
    _renderCard(strategyId) {
        const info = this.allStrategies[strategyId] || {};
        const enabled = this.enabledStrategies[strategyId];
        const isEnabled = !!enabled;
        const isAutoTrade = this.autoTradeStrategy === strategyId;
        const presetName = enabled ? enabled.preset_name : (info.default_preset || '');
        const presets = info.presets || {};
        const buyCount = enabled ? (enabled.signal_count_buy || 0) : 0;
        const sellCount = enabled ? (enabled.signal_count_sell || 0) : 0;

        const presetOptions = Object.keys(presets).map(p =>
            `<option value="${p}" ${p === presetName ? 'selected' : ''}>${p}</option>`
        ).join('');

        return `
        <div class="strategy-card ${isEnabled ? 'enabled' : 'disabled'}" data-strategy-id="${strategyId}">
            <div class="strategy-card-header">
                <div class="strategy-card-title">
                    <span class="strategy-name">${info.name || strategyId}</span>
                    ${isAutoTrade ? '<span class="auto-trade-badge">🤖 自动交易</span>' : ''}
                </div>
                <label class="strategy-toggle">
                    <input type="checkbox" ${isEnabled ? 'checked' : ''}
                           onchange="StrategyPanel.toggleStrategy('${strategyId}', this.checked)">
                    <span class="toggle-slider"></span>
                </label>
            </div>
            <div class="strategy-card-body">
                <div class="preset-selector">
                    <label>参数方案：</label>
                    <select class="form-select form-select-sm"
                            ${!isEnabled ? 'disabled' : ''}
                            onchange="StrategyPanel.changePreset('${strategyId}', this.value)">
                        ${presetOptions}
                    </select>
                </div>
                <div class="signal-counts">
                    <span class="buy-count">🟢 买入: ${buyCount}</span>
                    <span class="sell-count">🔴 卖出: ${sellCount}</span>
                </div>
            </div>
        </div>`;
    },

    /** 启用/禁用策略 */
    async toggleStrategy(strategyId, enabled) {
        const url = enabled ? '/api/strategy/enable' : '/api/strategy/disable';
        const body = enabled
            ? { strategy_id: strategyId, preset_name: this._getDefaultPreset(strategyId) }
            : { strategy_id: strategyId };

        try {
            const resp = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            const data = await resp.json();
            if (data.success) {
                await this.loadEnabledStrategies();
                // 通知信号 Tab 更新
                if (window.SignalTabs) window.SignalTabs.onStrategiesChanged(this.enabledStrategies);
            } else {
                showToast(data.message || '操作失败', 'error');
                await this.loadEnabledStrategies(); // 回滚 UI
            }
        } catch (e) {
            console.error('[策略面板] 切换策略失败:', e);
            showToast('网络错误', 'error');
            await this.loadEnabledStrategies();
        }
    },

    /** 切换预设 */
    async changePreset(strategyId, presetName) {
        try {
            const resp = await fetch(`/api/strategy/${strategyId}/preset`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ preset_name: presetName })
            });
            const data = await resp.json();
            if (!data.success) {
                showToast(data.message || '切换预设失败', 'error');
                await this.loadEnabledStrategies();
            }
        } catch (e) {
            console.error('[策略面板] 切换预设失败:', e);
            showToast('网络错误', 'error');
        }
    },

    /** 更新信号计数（由 WebSocket 推送触发） */
    updateSignalCounts(signalsByStrategy) {
        for (const [sid, signals] of Object.entries(signalsByStrategy)) {
            if (!this.enabledStrategies[sid]) continue;
            const buyCount = signals.filter(s => s.signal_type === 'BUY').length;
            const sellCount = signals.filter(s => s.signal_type === 'SELL').length;
            this.enabledStrategies[sid].signal_count_buy = buyCount;
            this.enabledStrategies[sid].signal_count_sell = sellCount;
        }
        // 更新卡片上的计数显示
        document.querySelectorAll('.strategy-card').forEach(card => {
            const sid = card.dataset.strategyId;
            const info = this.enabledStrategies[sid];
            if (!info) return;
            const counts = card.querySelector('.signal-counts');
            if (counts) {
                counts.innerHTML = `
                    <span class="buy-count">🟢 买入: ${info.signal_count_buy || 0}</span>
                    <span class="sell-count">🔴 卖出: ${info.signal_count_sell || 0}</span>`;
            }
        });
    },

    /** 获取策略的默认预设名称 */
    _getDefaultPreset(strategyId) {
        const info = this.allStrategies[strategyId] || {};
        return info.default_preset || Object.keys(info.presets || {})[0] || '';
    },

    /** 更新已启用策略计数徽标 */
    _updateCountBadge() {
        const badge = document.getElementById('enabled-strategy-count');
        const count = Object.keys(this.enabledStrategies).length;
        if (badge) badge.textContent = `${count} 个策略已启用`;
    }
};

// 页面加载后初始化
document.addEventListener('DOMContentLoaded', function() {
    StrategyPanel.init();
});
