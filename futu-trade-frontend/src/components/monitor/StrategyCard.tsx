// 单个策略卡片组件

"use client";

import type { EnabledStrategy, StrategyPreset } from "@/types";

interface StrategyCardProps {
  strategy: {
    id: string;
    name: string;
    description?: string;
    presets: StrategyPreset[];
  };
  enabled: EnabledStrategy | null;
  isAutoTrade: boolean;
  onToggle: (strategyId: string, enabled: boolean, presetName: string) => void;
  onPresetChange: (strategyId: string, presetName: string) => void;
  onSetAutoTrade: (strategyId: string) => void;
}

export function StrategyCard({
  strategy,
  enabled,
  isAutoTrade,
  onToggle,
  onPresetChange,
  onSetAutoTrade,
}: StrategyCardProps) {
  const isEnabled = !!enabled;
  const currentPreset = enabled?.preset_name || strategy.presets[0]?.name || "";
  const buyCount = enabled?.signal_count_buy || 0;
  const sellCount = enabled?.signal_count_sell || 0;

  return (
    <div
      className={`rounded-lg border-2 p-4 transition-all ${
        isEnabled
          ? "border-blue-400 bg-blue-50/50 shadow-sm"
          : "border-gray-200 bg-white opacity-75"
      }`}
    >
      {/* 头部：名称 + 开关 */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span
            className={`w-2.5 h-2.5 rounded-full ${
              isEnabled ? "bg-green-500" : "bg-gray-300"
            }`}
          />
          <h3 className="font-semibold text-gray-900">{strategy.name}</h3>
        </div>
        <button
          onClick={() => onToggle(strategy.id, !isEnabled, currentPreset)}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
            isEnabled ? "bg-blue-600" : "bg-gray-300"
          }`}
          role="switch"
          aria-checked={isEnabled}
          aria-label={`${isEnabled ? "禁用" : "启用"}${strategy.name}`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
              isEnabled ? "translate-x-6" : "translate-x-1"
            }`}
          />
        </button>
      </div>

      {/* 描述 */}
      {strategy.description && (
        <p className="text-xs text-gray-500 mb-3">{strategy.description}</p>
      )}

      {/* 预设选择 */}
      <div className="mb-3">
        <label className="text-xs text-gray-600 mb-1 block">预设参数</label>
        <select
          value={currentPreset}
          onChange={(e) => onPresetChange(strategy.id, e.target.value)}
          disabled={!isEnabled}
          className="w-full text-sm border border-gray-300 rounded-md px-2 py-1.5 bg-white disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {strategy.presets.map((preset) => (
            <option key={preset.name} value={preset.name}>
              {preset.name}
              {preset.description ? ` - ${preset.description}` : ""}
            </option>
          ))}
        </select>
      </div>

      {/* 信号计数 + 自动交易标记 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 text-sm">
          <span className="flex items-center gap-1 text-red-600">
            <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M5.293 9.707a1 1 0 010-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 01-1.414 1.414L11 7.414V15a1 1 0 11-2 0V7.414L6.707 9.707a1 1 0 01-1.414 0z" clipRule="evenodd" />
            </svg>
            {buyCount}
          </span>
          <span className="flex items-center gap-1 text-green-600">
            <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M14.707 10.293a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 111.414-1.414L9 12.586V5a1 1 0 012 0v7.586l2.293-2.293a1 1 0 011.414 0z" clipRule="evenodd" />
            </svg>
            {sellCount}
          </span>
        </div>

        {isEnabled && (
          <button
            onClick={() => onSetAutoTrade(strategy.id)}
            className={`text-xs px-2 py-1 rounded-md transition-colors ${
              isAutoTrade
                ? "bg-amber-100 text-amber-700 font-medium"
                : "text-gray-500 hover:bg-gray-100"
            }`}
            title={isAutoTrade ? "当前自动交易策略" : "设为自动交易策略"}
          >
            {isAutoTrade ? "⚡ 自动交易中" : "设为自动交易"}
          </button>
        )}
      </div>
    </div>
  );
}
