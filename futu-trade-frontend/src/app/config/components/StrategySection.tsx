// 策略配置分组 - 即时切换策略和预设

"use client";

import React, { useState, useEffect } from "react";
import { strategyApi } from "@/lib/api";
import { useToast } from "@/components/common/Toast";
import type { Strategy, StrategyPreset } from "@/types";

export function StrategySection() {
  const { showToast } = useToast();
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [presets, setPresets] = useState<StrategyPreset[]>([]);
  const [activeStrategyId, setActiveStrategyId] = useState<string>("");
  const [activePreset, setActivePreset] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState(false);
  const [isOpen, setIsOpen] = useState(false);

  const loadData = async () => {
    setLoading(true);
    try {
      const [strategiesRes, activeRes] = await Promise.all([
        strategyApi.getStrategies(),
        strategyApi.getActiveStrategy(),
      ]);

      if (strategiesRes.success && strategiesRes.data) {
        setStrategies(strategiesRes.data);
      }

      if (activeRes.success && activeRes.data) {
        const { strategy_id, preset_name } = activeRes.data;
        setActiveStrategyId(strategy_id);
        setActivePreset(preset_name);

        const presetsRes = await strategyApi.getPresets(strategy_id);
        if (presetsRes.success && presetsRes.data) {
          setPresets(presetsRes.data.presets || []);
        }
      }
    } catch {
      showToast("error", "错误", "加载策略信息失败");
    } finally {
      setLoading(false);
    }
  };

  const handleStrategyChange = async (strategyId: string) => {
    if (strategyId === activeStrategyId || switching) return;
    setSwitching(true);
    try {
      const res = await strategyApi.switchStrategy(strategyId);
      if (res.success) {
        setActiveStrategyId(strategyId);
        showToast("success", "成功", "策略已切换");

        const presetsRes = await strategyApi.getPresets(strategyId);
        if (presetsRes.success && presetsRes.data) {
          const newPresets = presetsRes.data.presets || [];
          setPresets(newPresets);
          const defaultPreset = presetsRes.data.active_preset || newPresets[0]?.name || "";
          setActivePreset(defaultPreset);
        }
      } else {
        showToast("error", "错误", res.message || "策略切换失败");
      }
    } catch {
      showToast("error", "错误", "策略切换失败");
    } finally {
      setSwitching(false);
    }
  };

  const handlePresetChange = async (presetName: string) => {
    if (presetName === activePreset || switching) return;
    setSwitching(true);
    try {
      const res = await strategyApi.switchPreset(presetName);
      if (res.success) {
        setActivePreset(presetName);
        showToast("success", "成功", "预设已切换");
      } else {
        showToast("error", "错误", res.message || "预设切换失败");
      }
    } catch {
      showToast("error", "错误", "预设切换失败");
    } finally {
      setSwitching(false);
    }
  };

  useEffect(() => {
    if (isOpen && strategies.length === 0) {
      loadData();
    }
  }, [isOpen]);

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors"
      >
        <div className="flex items-center gap-2">
          <i className="fas fa-chess text-gray-600"></i>
          <span className="font-medium text-gray-900">策略配置</span>
          {activeStrategyId && (
            <span className="text-xs text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">
              {strategies.find((s) => s.id === activeStrategyId)?.name || activeStrategyId}
            </span>
          )}
        </div>
        <i className={`fas fa-chevron-down text-gray-400 transition-transform ${isOpen ? "rotate-180" : ""}`}></i>
      </button>

      {isOpen && (
        <div className="px-4 py-4 bg-white space-y-6">
          {loading ? (
            <div className="flex items-center justify-center py-6">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500"></div>
              <span className="ml-2 text-sm text-gray-500">加载策略信息...</span>
            </div>
          ) : (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  当前策略
                  {switching && <span className="ml-2 text-xs text-gray-400">切换中...</span>}
                </label>
                <div className="space-y-2">
                  {strategies.length > 0 ? (
                    strategies.map((strategy) => (
                      <label
                        key={strategy.id}
                        className={`flex items-center p-3 rounded-lg border cursor-pointer transition-colors ${
                          switching ? "opacity-50 cursor-not-allowed" : ""
                        } ${
                          activeStrategyId === strategy.id
                            ? "border-blue-500 bg-blue-50"
                            : "border-gray-200 hover:border-gray-300"
                        }`}
                      >
                        <input
                          type="radio"
                          name="strategy"
                          value={strategy.id}
                          checked={activeStrategyId === strategy.id}
                          onChange={() => handleStrategyChange(strategy.id)}
                          disabled={switching}
                          className="h-4 w-4 text-blue-600"
                        />
                        <div className="ml-3">
                          <div className="font-medium text-gray-900">{strategy.name}</div>
                          {strategy.description && (
                            <div className="text-sm text-gray-500">{strategy.description}</div>
                          )}
                        </div>
                      </label>
                    ))
                  ) : (
                    <div className="p-4 text-center text-gray-500 bg-gray-50 rounded-lg">暂无可用策略</div>
                  )}
                </div>
              </div>

              {presets.length > 0 && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">当前预设</label>
                  <div className="space-y-2">
                    {presets.map((preset) => (
                      <label
                        key={preset.name}
                        className={`flex items-center p-3 rounded-lg border cursor-pointer transition-colors ${
                          switching ? "opacity-50 cursor-not-allowed" : ""
                        } ${
                          activePreset === preset.name
                            ? "border-blue-500 bg-blue-50"
                            : "border-gray-200 hover:border-gray-300"
                        }`}
                      >
                        <input
                          type="radio"
                          name="preset"
                          value={preset.name}
                          checked={activePreset === preset.name}
                          onChange={() => handlePresetChange(preset.name)}
                          disabled={switching}
                          className="h-4 w-4 text-blue-600"
                        />
                        <div className="ml-3">
                          <div className="font-medium text-gray-900">{preset.name}</div>
                          {preset.description && (
                            <div className="text-sm text-gray-500">{preset.description}</div>
                          )}
                        </div>
                      </label>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
