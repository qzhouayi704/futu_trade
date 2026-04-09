/**
 * SignalPanel - 信号历史面板
 *
 * 显示最近 50 条交易信号和止损提示的历史列表：
 * - 突破做多信号：绿灯闪烁 + "动能突破，做多"
 * - 支撑低吸信号：黄灯闪烁 + "支撑有效，试多"
 * - 止损提示：红灯闪烁 + "突破回落止损" / "支撑破位止损"
 * - 新信号到达时高亮闪烁动画
 * - 提示音开关控制
 * - VWAP 超限时禁用买入按钮，显示"偏离过大，禁止追高"
 *
 * 需求引用: 9.3, 10.3, 12.5, 12.6, 16.4, 16.6, 18.6
 */

"use client";

import { useMemo } from "react";
import type {
  ScalpingSignalData,
  VwapExtensionAlertData,
  StopLossAlertData,
} from "@/types/scalping";

// ==================== 组件接口 ====================

export interface SignalPanelProps {
  signals: ScalpingSignalData[];
  onSoundToggle: (enabled: boolean) => void;
  soundEnabled: boolean;
  vwapExtension: VwapExtensionAlertData | null;
  stopLossAlerts: StopLossAlertData[];
}

// ==================== 统一历史条目类型 ====================

type HistoryItemKind = "signal" | "stop_loss";

interface HistoryItem {
  kind: HistoryItemKind;
  timestamp: string;
  signal?: ScalpingSignalData;
  stopLoss?: StopLossAlertData;
}

// ==================== 信号显示配置 ====================

const SIGNAL_CONFIG = {
  breakout_long: {
    label: "动能突破，做多",
    dotClass: "bg-green-500",
    textClass: "text-green-400",
  },
  support_long: {
    label: "支撑有效，试多",
    dotClass: "bg-yellow-500",
    textClass: "text-yellow-400",
  },
} as const;

const STOP_LOSS_CONFIG = {
  breakout_stop: { label: "突破回落止损" },
  support_stop: { label: "支撑破位止损" },
} as const;

// ==================== 工具函数 ====================

/** VWAP 超限判定（导出供属性测试使用） */
export function isVwapDisabled(
  vwapExtension: VwapExtensionAlertData | null,
): boolean {
  return vwapExtension !== null;
}

/** 格式化时间戳为 HH:MM:SS */
function formatTime(timestamp: string): string {
  try {
    const d = new Date(timestamp);
    return d.toLocaleTimeString("zh-CN", { hour12: false });
  } catch {
    return "--:--:--";
  }
}

/** 格式化价格 */
function formatPrice(price: number): string {
  return price.toFixed(2);
}

/** 渲染信号评分星级 */
function renderScoreStars(score?: number, qualityLevel?: string): string {
  if (score === undefined || score === null) {
    return "";
  }

  // 根据质量等级返回星级
  if (qualityLevel === "high" || score >= 7) {
    return "⭐⭐⭐"; // 高质量
  } else if (qualityLevel === "medium" || score >= 5) {
    return "⭐⭐"; // 中等
  } else {
    return "⭐"; // 低质量（理论上不应该出现，因为已被过滤）
  }
}

/** 获取评分颜色类 */
function getScoreColorClass(score?: number, qualityLevel?: string): string {
  if (score === undefined || score === null) {
    return "text-gray-500";
  }

  if (qualityLevel === "high" || score >= 7) {
    return "text-yellow-400"; // 高质量 - 金色
  } else if (qualityLevel === "medium" || score >= 5) {
    return "text-blue-400"; // 中等 - 蓝色
  } else {
    return "text-gray-400"; // 低质量
  }
}

// ==================== 最大历史条目数 ====================

const MAX_HISTORY = 50;

// ==================== 组件实现 ====================

export function SignalPanel({
  signals,
  onSoundToggle,
  soundEnabled,
  vwapExtension,
  stopLossAlerts,
}: SignalPanelProps) {
  const buyDisabled = isVwapDisabled(vwapExtension);

  // 合并 signals 和 stopLossAlerts 到统一历史列表，按时间倒序
  const historyItems = useMemo<HistoryItem[]>(() => {
    const items: HistoryItem[] = [];

    for (const s of signals) {
      items.push({ kind: "signal", timestamp: s.timestamp, signal: s });
    }
    for (const sl of stopLossAlerts) {
      items.push({ kind: "stop_loss", timestamp: sl.timestamp, stopLoss: sl });
    }

    // 按时间倒序（最新在上）
    items.sort(
      (a, b) =>
        new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
    );

    // 限制最多 50 条
    return items.slice(0, MAX_HISTORY);
  }, [signals, stopLossAlerts]);

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-gray-700 bg-gray-900 p-3">
      {/* 标题栏 */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-200">信号面板</h3>
        <div className="flex items-center gap-3">
          {/* 提示音开关 */}
          <button
            type="button"
            onClick={() => onSoundToggle(!soundEnabled)}
            className={`rounded px-2 py-0.5 text-xs transition-colors ${
              soundEnabled
                ? "bg-blue-600 text-white"
                : "bg-gray-700 text-gray-400"
            }`}
            aria-label={soundEnabled ? "关闭提示音" : "开启提示音"}
          >
            {soundEnabled ? "🔔 提示音" : "🔕 静音"}
          </button>

          {/* 买入按钮 */}
          <button
            type="button"
            disabled={buyDisabled}
            className={`rounded px-3 py-0.5 text-xs font-medium transition-colors ${
              buyDisabled
                ? "cursor-not-allowed bg-gray-700 text-gray-500"
                : "bg-green-600 text-white hover:bg-green-500"
            }`}
          >
            买入
          </button>
        </div>
      </div>

      {/* VWAP 超限提示 */}
      {buyDisabled && (
        <div className="rounded bg-red-900/40 px-2 py-1 text-center text-xs text-red-400">
          偏离过大，禁止追高
        </div>
      )}

      {/* 信号历史列表 */}
      <div className="flex max-h-64 flex-col gap-1 overflow-y-auto">
        {historyItems.length === 0 ? (
          <div className="py-4 text-center text-xs text-gray-500">
            暂无信号
          </div>
        ) : (
          historyItems.map((item, index) => (
            <SignalRow key={`${item.timestamp}-${index}`} item={item} isLatest={index === 0} />
          ))
        )}
      </div>
    </div>
  );
}

// ==================== 信号行子组件 ====================

function SignalRow({
  item,
  isLatest,
}: {
  item: HistoryItem;
  isLatest: boolean;
}) {
  if (item.kind === "signal" && item.signal) {
    return <SignalSignalRow signal={item.signal} isLatest={isLatest} />;
  }
  if (item.kind === "stop_loss" && item.stopLoss) {
    return <StopLossRow stopLoss={item.stopLoss} isLatest={isLatest} />;
  }
  return null;
}

function SignalSignalRow({
  signal,
  isLatest,
}: {
  signal: ScalpingSignalData;
  isLatest: boolean;
}) {
  const config = SIGNAL_CONFIG[signal.signal_type];
  const scoreStars = renderScoreStars(signal.score, signal.quality_level);
  const scoreColorClass = getScoreColorClass(signal.score, signal.quality_level);

  return (
    <div
      className={`flex items-center gap-2 rounded px-2 py-1 text-xs ${
        isLatest ? "animate-pulse bg-gray-800" : "bg-gray-800/50"
      }`}
    >
      {/* 指示灯 */}
      <span
        className={`inline-block h-2 w-2 shrink-0 rounded-full ${config.dotClass} ${
          isLatest ? "animate-ping" : ""
        }`}
      />
      {/* 信号文字 */}
      <span className={`font-medium ${config.textClass}`}>
        {config.label}
      </span>
      {/* 评分星级 */}
      {scoreStars && (
        <span className={`shrink-0 ${scoreColorClass}`} title={`评分: ${signal.score}/10`}>
          {scoreStars}
        </span>
      )}
      {/* 价格 */}
      <span className="text-gray-400">
        ¥{formatPrice(signal.trigger_price)}
      </span>
      {/* 时间 */}
      <span className="ml-auto shrink-0 text-gray-500">
        {formatTime(signal.timestamp)}
      </span>
    </div>
  );
}

function StopLossRow({
  stopLoss,
  isLatest,
}: {
  stopLoss: StopLossAlertData;
  isLatest: boolean;
}) {
  const config = STOP_LOSS_CONFIG[stopLoss.signal_type];

  return (
    <div
      className={`flex items-center gap-2 rounded px-2 py-1 text-xs ${
        isLatest ? "animate-pulse bg-gray-800" : "bg-gray-800/50"
      }`}
    >
      {/* 红色指示灯 */}
      <span
        className={`inline-block h-2 w-2 shrink-0 rounded-full bg-red-500 ${
          isLatest ? "animate-ping" : ""
        }`}
      />
      {/* 止损文字 */}
      <span className="font-medium text-red-400">{config.label}</span>
      {/* 价格 */}
      <span className="text-gray-400">
        ¥{formatPrice(stopLoss.current_price)}
      </span>
      {/* 回撤幅度 */}
      <span className="text-red-500">
        -{stopLoss.drawdown_percent.toFixed(1)}%
      </span>
      {/* 时间 */}
      <span className="ml-auto shrink-0 text-gray-500">
        {formatTime(stopLoss.timestamp)}
      </span>
    </div>
  );
}
