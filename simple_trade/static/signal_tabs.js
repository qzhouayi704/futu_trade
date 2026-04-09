/**
 * 信号分组 Tab 切换逻辑
 * 负责按策略分组展示信号、Tab 切换、WebSocket 信号更新
 */

window.SignalTabs = {
    activeTab: 'all',
    signalsByStrategy: {},

    /** 当已启用策略变更时，重新渲染 Tab */
    onStrategiesChanged(enabledStrategies) {
        this.renderTabs(enabledStrategies);
        this.updateSignals(this.signalsByStrategy);
    },

    /** 渲染信号 Tab 按钮 */
    renderTabs(enabledStrategies) {
        const container = document.getElementById('signal-tabs');
        if (!container) return;

        // 保留"全部"Tab
        let html = `<button class="signal-tab ${this.activeTab === 'all' ? 'active' : ''}"
                            data-strategy="all" onclick="SignalTabs.switchTab('all')">
                        全部 <span class="tab-badge" id="tab-badge-all">0</span>
                    </button>`;

        // 为每个已启用策略添加 Tab
        for (const [sid, info] of Object.entries(enabledStrategies)) {
            const name = info.strategy_name || sid;
            const isActive = this.activeTab === sid;
            html += `<button class="signal-tab ${isActive ? 'active' : ''}"
                            data-strategy="${sid}" onclick="SignalTabs.switchTab('${sid}')">
                        ${name} <span class="tab-badge" id="tab-badge-${sid}">0</span>
                    </button>`;
        }

        container.innerHTML = html;
    },

    /** 切换 Tab */
    switchTab(strategyId) {
        this.activeTab = strategyId;
        // 更新 Tab 样式
        document.querySelectorAll('.signal-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.strategy === strategyId);
        });
        // 重新渲染信号列表
        this._renderFilteredSignals();
    },

    /** 更新信号数据（由 WebSocket 推送触发） */
    updateSignals(signalsByStrategy) {
        this.signalsByStrategy = signalsByStrategy || {};
        this._updateBadges();
        this._renderFilteredSignals();
    },

    /** 更新各 Tab 的信号数量徽标 */
    _updateBadges() {
        let totalCount = 0;
        for (const [sid, signals] of Object.entries(this.signalsByStrategy)) {
            const count = (signals || []).length;
            totalCount += count;
            const badge = document.getElementById(`tab-badge-${sid}`);
            if (badge) badge.textContent = count;
        }
        const allBadge = document.getElementById('tab-badge-all');
        if (allBadge) allBadge.textContent = totalCount;
    },

    /** 根据当前 Tab 过滤并渲染信号 */
    _renderFilteredSignals() {
        let signals = [];
        if (this.activeTab === 'all') {
            // 合并所有策略信号
            for (const list of Object.values(this.signalsByStrategy)) {
                signals = signals.concat(list || []);
            }
        } else {
            signals = this.signalsByStrategy[this.activeTab] || [];
        }

        const container = document.getElementById('signals-container');
        if (!container) return;

        if (signals.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <span class="empty-icon">📭</span>
                    <p>暂无信号</p>
                </div>`;
            return;
        }

        container.innerHTML = signals.map(s => this._renderSignalCard(s)).join('');
    },

    /** 渲染单个信号卡片 */
    _renderSignalCard(signal) {
        const isBuy = (signal.signal_type || '').toUpperCase() === 'BUY';
        const typeClass = isBuy ? 'signal-buy' : 'signal-sell';
        const typeText = isBuy ? '买入' : '卖出';
        const typeIcon = isBuy ? '🟢' : '🔴';
        const time = signal.timestamp ? new Date(signal.timestamp).toLocaleTimeString('zh-CN') : '--';

        return `
        <div class="signal-card ${typeClass}">
            <div class="signal-card-header">
                <span class="signal-stock">${signal.stock_code || ''} ${signal.stock_name || ''}</span>
                <span class="signal-type-badge ${typeClass}">${typeIcon} ${typeText}</span>
            </div>
            <div class="signal-card-body">
                <div class="signal-price">价格: ${signal.price || '--'}</div>
                <div class="signal-reason">${signal.reason || ''}</div>
                <div class="signal-meta">
                    <span class="signal-strategy">${signal.strategy_name || ''}</span>
                    <span class="signal-time">${time}</span>
                </div>
            </div>
        </div>`;
    }
};
