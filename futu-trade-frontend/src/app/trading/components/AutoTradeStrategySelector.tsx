// 自动交易策略选择器

"use client";

import { useState, useEffect, useCallback } from "react";
import { Card } from "@/components/common";
import { multiStrategyApi } from "@/lib/api";
import { useMonitorStore } from "@/lib/stores";
import { useToast } from "@/components/common/Toast";

export function AutoTradeStrategySelector() {
  const { showToast } = useToast();
  const {
    enabledStrategies,
    autoTradeStrategyId,
    setEnabledStrategies,
    setAutoTradeStrategyId,
  } = useMonitorStore();

  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await multiStrategyApi.getEnabledStrategies();
      if (res.success && res.data) {
        setEnabledStrategies(res.data.enabled_strategies || []);
        setAutoTradeStrategyId(res.data.auto_trade_strategy || null);
      }
    } catch (err) {
      console.error("加载策略数据失败:", err);
    } finally {
      setLoading(false);
    }
  }, [setEnabledStrategies, setAutoTradeStrategyId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleChange = async (strategyId: string) => {
    if (!strategyId) return;
    try {
      const res = await multiStrategyApi.setAutoTradeStrategy(strategyId);
      if (res.success) {
        setAutoTradeStrategyId(strategyId);
        showToast("success", "成功", "自动交易策略已切换");
      } else {
        showToast("error", "错误", res.message || "设置失败");
      }
    } catch (err: any) {
      showToast("error", "错误", err.message || "设置失败");
    }
  };

  // 检查当前跟随策略是否仍在已启用列表中
  const isCurrentValid =
    !autoTradeStrategyId ||
    enabledStrategies.some((s) => s.strategy_id === autoTradeStrategyId);

  const currentStrategy = enabledStrategies.find(
    (s) => s.strategy_id === autoTradeStrategyId
  );

  if (loading) {
    return (
      <Card>
        <div className="p-4 text-center text-gray-500 text-sm">加载中...</div>
      </Card>
    );
  }

  return (
    <Card>
      <div className="p-4">
        <h4 className="text-sm font-semibold text-gray-900 flex items-center gap-2 mb-3">
          <svg className="w-4 h-4 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          自动交易跟随策略
        </h4>

        {/* 警告：跟随策略已被禁用 */}
        {!isCurrentValid && autoTradeStrategyId && (
          <div className="mb-3 p-2 bg-amber-50 border border-amber-200 rounded-md text-xs text-amber-700 flex items-center gap-1.5">
            <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
            当前跟随策略已被禁用，自动交易已暂停。请重新选择。
          </div>
        )}

        {enabledStrategies.length === 0 ? (
          <p className="text-sm text-gray-500">暂无已启用的策略，请先在策略面板中启用策略。</p>
        ) : (
          <div className="space-y-2">
            <select
              value={autoTradeStrategyId || ""}
              onChange={(e) => handleChange(e.target.value)}
              className="w-full text-sm border border-gray-300 rounded-md px-3 py-2 bg-white"
            >
              <option value="" disabled>
                选择跟随策略
              </option>
              {enabledStrategies.map((s) => (
                <option key={s.strategy_id} value={s.strategy_id}>
                  {s.strategy_name} ({s.preset_name})
                </option>
              ))}
            </select>

            {currentStrategy && isCurrentValid && (
              <div className="text-xs text-gray-500">
                当前跟随: {currentStrategy.strategy_name} · {currentStrategy.preset_name}
                <span className="ml-2 text-green-600">
                  买入信号 {currentStrategy.signal_count_buy} · 卖出信号{" "}
                  {currentStrategy.signal_count_sell}
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
