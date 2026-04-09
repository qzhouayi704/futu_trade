// 多策略面板组件 - 展示策略卡片列表

"use client";

import { useState, useEffect, useCallback } from "react";
import { Card } from "@/components/common";
import { strategyApi, multiStrategyApi } from "@/lib/api";
import { useMonitorStore } from "@/lib/stores";
import { useToast } from "@/components/common/Toast";
import { StrategyCard } from "./StrategyCard";
import type { Strategy, StrategyPreset } from "@/types";

interface StrategyWithPresets {
  id: string;
  name: string;
  description?: string;
  presets: StrategyPreset[];
}

export function StrategyPanel() {
  const { showToast } = useToast();
  const {
    enabledStrategies,
    autoTradeStrategyId,
    setEnabledStrategies,
    setAutoTradeStrategyId,
  } = useMonitorStore();

  const [allStrategies, setAllStrategies] = useState<StrategyWithPresets[]>([]);
  const [loading, setLoading] = useState(true);

  // 加载所有策略和已启用状态
  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [strategiesRes, enabledRes] = await Promise.all([
        strategyApi.getStrategies(),
        multiStrategyApi.getEnabledStrategies(),
      ]);

      if (strategiesRes.success && strategiesRes.data) {
        const list = (strategiesRes.data as any).strategies || strategiesRes.data || [];
        // 为每个策略加载预设
        const withPresets = await Promise.all(
          list.map(async (s: Strategy) => {
            try {
              const presetsRes = await strategyApi.getPresets(s.id);
              return {
                id: s.id,
                name: s.name,
                description: s.description,
                presets: presetsRes.success ? presetsRes.data?.presets || [] : [],
              };
            } catch {
              return { id: s.id, name: s.name, description: s.description, presets: [] };
            }
          })
        );
        setAllStrategies(withPresets);
      }

      if (enabledRes.success && enabledRes.data) {
        setEnabledStrategies(enabledRes.data.enabled_strategies || []);
        setAutoTradeStrategyId(enabledRes.data.auto_trade_strategy || null);
      }
    } catch (err: any) {
      console.error("加载策略数据失败:", err);
    } finally {
      setLoading(false);
    }
  }, [setEnabledStrategies, setAutoTradeStrategyId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // 启用/禁用策略
  const handleToggle = async (strategyId: string, enable: boolean, presetName: string) => {
    try {
      if (enable) {
        const res = await multiStrategyApi.enableStrategy(strategyId, presetName);
        if (res.success) {
          showToast("success", "成功", "策略已启用");
        } else {
          showToast("error", "错误", res.message || "启用失败");
          return;
        }
      } else {
        const res = await multiStrategyApi.disableStrategy(strategyId);
        if (res.success) {
          showToast("success", "成功", "策略已禁用");
          if (res.data?.auto_trade_paused) {
            showToast("warning", "提示", "自动交易已暂停（跟随策略被禁用）");
          }
        } else {
          showToast("error", "错误", res.message || "禁用失败");
          return;
        }
      }
      // 刷新已启用策略
      const enabledRes = await multiStrategyApi.getEnabledStrategies();
      if (enabledRes.success && enabledRes.data) {
        setEnabledStrategies(enabledRes.data.enabled_strategies || []);
        setAutoTradeStrategyId(enabledRes.data.auto_trade_strategy || null);
      }
    } catch (err: any) {
      showToast("error", "错误", err.message || "操作失败");
    }
  };

  // 切换预设
  const handlePresetChange = async (strategyId: string, presetName: string) => {
    try {
      const res = await multiStrategyApi.updateStrategyPreset(strategyId, presetName);
      if (res.success) {
        showToast("success", "成功", "预设已切换");
        const enabledRes = await multiStrategyApi.getEnabledStrategies();
        if (enabledRes.success && enabledRes.data) {
          setEnabledStrategies(enabledRes.data.enabled_strategies || []);
        }
      } else {
        showToast("error", "错误", res.message || "切换失败");
      }
    } catch (err: any) {
      showToast("error", "错误", err.message || "切换预设失败");
    }
  };

  // 设置自动交易策略
  const handleSetAutoTrade = async (strategyId: string) => {
    try {
      const res = await multiStrategyApi.setAutoTradeStrategy(strategyId);
      if (res.success) {
        setAutoTradeStrategyId(strategyId);
        showToast("success", "成功", "自动交易策略已设置");
      } else {
        showToast("error", "错误", res.message || "设置失败");
      }
    } catch (err: any) {
      showToast("error", "错误", err.message || "设置自动交易策略失败");
    }
  };

  if (loading) {
    return (
      <Card>
        <div className="p-6 text-center text-gray-500">加载策略信息...</div>
      </Card>
    );
  }

  return (
    <Card>
      <div className="p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <svg className="w-5 h-5 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
            策略面板
          </h3>
          <span className="text-sm text-gray-500">
            已启用 {enabledStrategies.length}/{allStrategies.length}
          </span>
        </div>

        {allStrategies.length === 0 ? (
          <div className="text-center py-8 text-gray-500">暂无可用策略</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {allStrategies.map((strategy) => {
              const enabled = enabledStrategies.find(
                (e) => e.strategy_id === strategy.id
              ) || null;
              return (
                <StrategyCard
                  key={strategy.id}
                  strategy={strategy}
                  enabled={enabled}
                  isAutoTrade={autoTradeStrategyId === strategy.id}
                  onToggle={handleToggle}
                  onPresetChange={handlePresetChange}
                  onSetAutoTrade={handleSetAutoTrade}
                />
              );
            })}
          </div>
        )}
      </div>
    </Card>
  );
}
