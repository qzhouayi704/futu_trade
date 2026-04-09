/**
 * ScalpingDetailModal - 日内交易概览
 *
 * 4 区域布局：
 * 1. 风险警报条（仅有风险时显示）
 * 2. 多空态势 + 交易动态
 * 3. 成交量堆积 + 盘口力量
 * 4. 关键价位
 */

"use client";

import { useMemo } from "react";
import { useScalpingSocket } from "@/app/enhanced-heat/components/scalping/useScalpingSocket";
import type {
  PriceLevelData,
  ScalpingSignalData,
  DeltaUpdateData,
  TrapAlertData,
  FakeBreakoutAlertData,
  FakeLiquidityAlertData,
  MomentumIgnitionData,
  TrueBreakoutConfirmData,
  StopLossAlertData,
  TickOutlierData,
  VwapExtensionAlertData,
  PocUpdateData,
  PatternAlertData,
  ActionSignalData,
} from "@/types/scalping";

interface StockInfo {
  code: string;
  name: string;
}

interface ScalpingDetailModalProps {
  stock: StockInfo;
  onClose: () => void;
}

// ==================== 辅助函数 ====================

function formatVolume(v: number): string {
  if (v >= 10000) return `${(v / 10000).toFixed(1)}万`;
  return v.toLocaleString();
}

function formatDelta(delta: number): string {
  const abs = Math.abs(delta);
  if (abs >= 10000) return `${(delta / 10000).toFixed(1)}万`;
  return delta.toFixed(0);
}

function timeStr(ts: string): string {
  return new Date(ts).toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ==================== 第一层: 环境状态条 ====================

function EnvironmentStatusBar({ deltaData }: { deltaData: DeltaUpdateData[] }) {
  const r6 = deltaData.slice(-6);
  if (r6.length < 3) return null;

  const deltas = r6.map(d => d.delta);
  const positiveCount = deltas.filter(d => d > 0).length;
  const negativeCount = deltas.filter(d => d < 0).length;
  const isIncreasing = deltas.length >= 3 && deltas[deltas.length - 1] > deltas[deltas.length - 2] && deltas[deltas.length - 2] > deltas[deltas.length - 3];
  const isDecreasing = deltas.length >= 3 && Math.abs(deltas[deltas.length - 1]) < Math.abs(deltas[deltas.length - 2]);

  let momentum: { icon: string; label: string; color: string; bg: string };
  if (positiveCount >= 3 && isIncreasing) {
    momentum = { icon: "🟢", label: "多方加速", color: "text-green-400", bg: "bg-green-900/40" };
  } else if (positiveCount >= 3 && isDecreasing) {
    momentum = { icon: "🟡", label: "多方减速", color: "text-yellow-400", bg: "bg-yellow-900/30" };
  } else if (negativeCount >= 3 && isIncreasing) {
    momentum = { icon: "🔴", label: "空方加速", color: "text-red-400", bg: "bg-red-900/40" };
  } else if (negativeCount >= 3 && isDecreasing) {
    momentum = { icon: "🟡", label: "空方减速", color: "text-yellow-400", bg: "bg-yellow-900/30" };
  } else {
    momentum = { icon: "⚪", label: "多空拉锯", color: "text-gray-400", bg: "bg-gray-800/40" };
  }

  return (
    <div className={`flex items-center gap-3 border-b border-gray-700/50 px-4 py-1.5 ${momentum.bg}`}>
      <span className={`text-xs font-medium ${momentum.color}`}>{momentum.icon} {momentum.label}</span>
    </div>
  );
}

// ==================== 第二层: 行为模式预警列表 ====================

const SEVERITY_STYLE: Record<string, { bg: string; border: string; text: string }> = {
  danger: { bg: "bg-red-950/60", border: "border-red-800/50", text: "text-red-300" },
  warning: { bg: "bg-amber-950/50", border: "border-amber-800/40", text: "text-amber-300" },
  info: { bg: "bg-emerald-950/50", border: "border-emerald-800/40", text: "text-emerald-300" },
};

const DIRECTION_ICON: Record<string, string> = {
  bullish: "📈", bearish: "📉", neutral: "➡️",
};

function PatternAlertsList({ alerts }: { alerts: PatternAlertData[] }) {
  if (alerts.length === 0) return null;
  const recent = alerts.slice(-5);

  return (
    <div className="flex flex-col gap-1">
      {recent.map((a, i) => {
        const style = SEVERITY_STYLE[a.severity] || SEVERITY_STYLE.info;
        return (
          <div key={`${a.pattern_type}-${i}`} className={`flex items-center gap-2 rounded px-3 py-1.5 text-xs border ${style.bg} ${style.border}`}>
            <span className="shrink-0">{DIRECTION_ICON[a.direction] || "⚡"}</span>
            <span className={`font-medium ${style.text}`}>{a.title}</span>
            <span className="text-gray-400 flex-1 truncate">{a.description}</span>
            <span className="shrink-0 text-gray-500">{timeStr(a.timestamp)}</span>
          </div>
        );
      })}
    </div>
  );
}

// ==================== 第三层: 行动提示卡 ====================

function ActionSignalCard({ signals }: { signals: ActionSignalData[] }) {
  if (signals.length === 0) return null;
  const latest = signals[signals.length - 1];
  const isLong = latest.action === "long";
  const isAction = latest.level === "action";

  const bgColor = isLong
    ? (isAction ? "bg-green-900/50 border-green-600/60" : "bg-green-900/20 border-green-800/40")
    : (isAction ? "bg-red-900/50 border-red-600/60" : "bg-red-900/20 border-red-800/40");
  const textColor = isLong ? "text-green-300" : "text-red-300";
  const actionLabel = isLong ? "做多" : "做空/离场";
  const levelLabel = isAction ? "行动" : "关注";
  const levelBadge = isAction ? "bg-green-600 text-white" : "bg-yellow-700 text-yellow-100";

  return (
    <div className={`rounded-lg border p-3 ${bgColor}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className={`text-lg`}>{isLong ? "✅" : "❌"}</span>
          <span className={`text-sm font-bold ${textColor}`}>{actionLabel}提示</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${levelBadge}`}>{levelLabel}</span>
        </div>
        <span className={`text-lg font-bold ${textColor}`}>{latest.score.toFixed(1)}分</span>
      </div>

      {/* 评分因子 */}
      <div className="flex flex-wrap gap-1.5 mb-2">
        {latest.components.map((c, i) => (
          <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800/60 text-gray-300" title={c.detail}>
            {c.name}(+{c.score})
          </span>
        ))}
      </div>

      {/* 止损参考 */}
      {latest.stop_loss_ref != null && (
        <div className="text-[10px] text-gray-400">
          📍 止损参考: <span className="text-red-400 font-mono">{latest.stop_loss_ref.toFixed(3)}</span>
        </div>
      )}
    </div>
  );
}

// ==================== 区域 1: 风险警报条 ====================

function RiskAlertBanner({
  trapAlerts,
  fakeBreakoutAlerts,
  fakeLiquidityAlerts,
}: {
  trapAlerts: TrapAlertData[];
  fakeBreakoutAlerts: FakeBreakoutAlertData[];
  fakeLiquidityAlerts: FakeLiquidityAlertData[];
}) {
  const alerts: { text: string; time: string }[] = [];

  // 取最新的警报
  const latestTrap = trapAlerts[trapAlerts.length - 1];
  if (latestTrap) {
    const label =
      latestTrap.trap_type === "bull_trap"
        ? "诱多风险：价格触及高点后买方动量衰减"
        : "诱空风险：跌破支撑但卖方量能不足";
    alerts.push({ text: label, time: latestTrap.timestamp });
  }

  const latestFakeBreak = fakeBreakoutAlerts[fakeBreakoutAlerts.length - 1];
  if (latestFakeBreak) {
    alerts.push({
      text: `假突破：突破 ${latestFakeBreak.breakout_price.toFixed(2)} 后回落，量能衰减 ${(latestFakeBreak.velocity_decay_ratio * 100).toFixed(0)}%`,
      time: latestFakeBreak.timestamp,
    });
  }

  const latestFakeLiq = fakeLiquidityAlerts[fakeLiquidityAlerts.length - 1];
  if (latestFakeLiq) {
    alerts.push({
      text: `虚假流动性：${latestFakeLiq.disappear_price.toFixed(2)} 处大单消失`,
      time: latestFakeLiq.timestamp,
    });
  }

  if (alerts.length === 0) return null;

  return (
    <div className="flex flex-col gap-1 border-b border-red-900/50 bg-red-950/60 px-4 py-2">
      {alerts.map((a, i) => (
        <div key={i} className="flex items-center gap-2 text-xs">
          <span className="shrink-0 text-red-400">⚠️</span>
          <span className="text-red-200">{a.text}</span>
          <span className="ml-auto shrink-0 text-red-400/60">{timeStr(a.time)}</span>
        </div>
      ))}
    </div>
  );
}

// ==================== 区域 2 左: 多空态势 ====================

function BullBearStatus({ deltaData }: { deltaData: DeltaUpdateData[] }) {
  const recent = deltaData.slice(-20);

  // 多空判定
  const { totalBuy, totalSell, status, statusColor, statusBg } = useMemo(() => {
    let buy = 0;
    let sell = 0;
    for (const d of recent) {
      if (d.delta > 0) buy += d.delta;
      else sell += Math.abs(d.delta);
    }
    const total = buy + sell || 1;
    const buyPct = buy / total;

    let st: string, sc: string, sb: string;
    if (buyPct > 0.6) {
      st = "🟢 多方主导"; sc = "text-green-400"; sb = "bg-green-900/30";
    } else if (buyPct < 0.4) {
      st = "🔴 空方主导"; sc = "text-red-400"; sb = "bg-red-900/30";
    } else {
      st = "⚪ 多空均衡"; sc = "text-gray-400"; sb = "bg-gray-800/30";
    }
    return { totalBuy: buy, totalSell: sell, status: st, statusColor: sc, statusBg: sb };
  }, [recent]);

  const maxAbs = Math.max(...recent.map((d) => Math.abs(d.delta)), 1);
  const totalVol = totalBuy + totalSell || 1;
  const buyPct = Math.round((totalBuy / totalVol) * 100);

  return (
    <div className="flex flex-col gap-2">
      {/* 总结徽标 */}
      <div className={`inline-flex items-center gap-1.5 rounded px-2 py-1 text-sm font-medium ${statusColor} ${statusBg}`}>
        {status}
      </div>

      {/* Delta 柱状图 (20根) */}
      <div className="relative" style={{ height: 80 }}>
        {/* 零线 */}
        <div className="absolute left-0 right-0 border-t border-dashed border-gray-600" style={{ top: "50%" }} />

        <div className="absolute inset-0 flex items-center justify-end gap-[2px]">
          {recent.map((d, i) => {
            const pct = Math.abs(d.delta) / maxAbs;
            const h = Math.max(pct * 36, 1);
            const isPos = d.delta >= 0;
            const color = isPos ? "#26a69a" : "#ef5350";

            return (
              <div
                key={`${d.timestamp}-${i}`}
                className="flex flex-col items-center justify-center"
                style={{ width: 10, height: 80 }}
              >
                {isPos ? (
                  <>
                    <div style={{ flex: 1 }} />
                    <div className="rounded-t-sm" style={{ width: 8, height: h, backgroundColor: color }} />
                    <div style={{ flex: 1 }} />
                  </>
                ) : (
                  <>
                    <div style={{ flex: 1 }} />
                    <div className="rounded-b-sm" style={{ width: 8, height: h, backgroundColor: color }} />
                    <div style={{ flex: 1 }} />
                  </>
                )}
              </div>
            );
          })}
        </div>

        {/* 时间标签 */}
        {recent.length > 1 && (
          <div className="absolute bottom-0 left-0 right-0 flex justify-between text-[9px] text-gray-500">
            <span>{timeStr(recent[0].timestamp)}</span>
            <span>{timeStr(recent[recent.length - 1].timestamp)}</span>
          </div>
        )}
      </div>

      {/* 四级资金流 + 买卖力量占比 */}
      <div className="flex flex-col gap-1.5">
        {/* 四级资金流占比条 */}
        {(() => {
          const totalV = recent.reduce((s, d) => s + d.volume, 0) || 1;
          const sl = recent.reduce((s, d) => s + (d.super_large_volume || 0), 0);
          const lg = recent.reduce((s, d) => s + (d.large_volume || 0), 0);
          const md = recent.reduce((s, d) => s + (d.medium_volume || 0), 0);
          const sm = recent.reduce((s, d) => s + (d.small_volume || 0), 0);
          const slP = Math.round((sl / totalV) * 100);
          const lgP = Math.round((lg / totalV) * 100);
          const mdP = Math.round((md / totalV) * 100);
          const smP = 100 - slP - lgP - mdP;

          return (
            <div className="flex flex-col gap-0.5">
              <div className="flex h-[8px] overflow-hidden rounded-full bg-gray-800">
                {slP > 0 && <div className="bg-purple-500" style={{ width: `${slP}%` }} title={`超大单 ${slP}%`} />}
                {lgP > 0 && <div className="bg-orange-500" style={{ width: `${lgP}%` }} title={`大单 ${lgP}%`} />}
                {mdP > 0 && <div className="bg-blue-500/70" style={{ width: `${mdP}%` }} title={`中单 ${mdP}%`} />}
                {smP > 0 && <div className="bg-gray-600" style={{ width: `${smP}%` }} title={`小单 ${smP}%`} />}
              </div>
              <div className="flex items-center gap-2 text-[9px] text-gray-400">
                {slP > 0 && <span className="text-purple-400">🐋超大{slP}%</span>}
                {lgP > 0 && <span className="text-orange-400">🔶大单{lgP}%</span>}
                <span className="text-blue-400/70">📦中单{mdP}%</span>
                <span className="text-gray-500">🔹小单{smP}%</span>
                {/* 大单净流入 */}
                {(() => {
                  const bigBuy = recent.reduce((s, d) => s + (d.big_buy_volume || 0), 0);
                  const bigSell = recent.reduce((s, d) => s + (d.big_sell_volume || 0), 0);
                  const net = bigBuy - bigSell;
                  if (bigBuy + bigSell === 0) return null;
                  const color = net > 0 ? "text-green-400" : net < 0 ? "text-red-400" : "text-gray-400";
                  const arrow = net > 0 ? "↑" : net < 0 ? "↓" : "→";
                  return (
                    <span className={`ml-auto font-medium ${color}`}>
                      💰大单净{net > 0 ? "买" : "卖"}{arrow}{formatVolume(Math.abs(net))}
                    </span>
                  );
                })()}
              </div>
            </div>
          );
        })()}

        {/* 成交买卖力量占比条 */}
        <div className="flex items-center gap-3 text-[10px]">
          <span className="text-green-400 shrink-0">主买 {buyPct}%</span>
          <div className="flex h-[6px] flex-1 overflow-hidden rounded-full bg-gray-700">
            <div className="bg-green-500/80 transition-all" style={{ width: `${buyPct}%` }} />
            <div className="bg-red-500/80 transition-all" style={{ width: `${100 - buyPct}%` }} />
          </div>
          <span className="text-red-400 shrink-0">{100 - buyPct}% 主卖</span>
        </div>
      </div>
    </div>
  );
}

// ==================== 区域 2 右: 交易动态 ====================

interface TimelineEvent {
  time: string;
  icon: string;
  text: string;
  color: string;
}

function TradingActivity({
  signals,
  momentumIgnitions,
  trueBreakoutConfirms,
  stopLossAlerts,
  tickOutliers,
  vwapExtension,
}: {
  signals: ScalpingSignalData[];
  momentumIgnitions: MomentumIgnitionData[];
  trueBreakoutConfirms: TrueBreakoutConfirmData[];
  stopLossAlerts: StopLossAlertData[];
  tickOutliers: TickOutlierData[];
  vwapExtension: VwapExtensionAlertData | null;
}) {
  // 最新信号卡片
  const latestSignal = signals[signals.length - 1];
  const latestStopLoss = stopLossAlerts[stopLossAlerts.length - 1];

  // 融合事件时间线
  const events: TimelineEvent[] = useMemo(() => {
    const items: TimelineEvent[] = [];

    for (const m of momentumIgnitions.slice(-5)) {
      items.push({
        time: m.timestamp,
        icon: "🔥",
        text: `动能点火 ${m.multiplier.toFixed(1)}x`,
        color: "text-orange-400",
      });
    }
    for (const t of trueBreakoutConfirms.slice(-5)) {
      items.push({
        time: t.timestamp,
        icon: "✅",
        text: `真突破确认 ${t.breakout_price.toFixed(2)}`,
        color: "text-green-400",
      });
    }
    for (const o of tickOutliers.slice(-5)) {
      items.push({
        time: o.timestamp,
        icon: "⚡",
        text: `异常大单 ${formatVolume(o.volume)}@${o.price.toFixed(2)}`,
        color: "text-yellow-400",
      });
    }
    if (vwapExtension) {
      items.push({
        time: vwapExtension.timestamp,
        icon: "📊",
        text: `VWAP 偏离 ${vwapExtension.deviation_percent.toFixed(1)}%`,
        color: "text-blue-400",
      });
    }

    items.sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime());
    return items.slice(0, 5);
  }, [momentumIgnitions, trueBreakoutConfirms, tickOutliers, vwapExtension]);

  // 质量星级
  const qualityStars = (level?: "high" | "medium" | "low") => {
    if (level === "high") return "⭐⭐⭐";
    if (level === "medium") return "⭐⭐";
    return "⭐";
  };

  return (
    <div className="flex flex-col gap-3">
      {/* 信号卡片 */}
      {latestSignal ? (
        <div className="rounded border border-gray-700 bg-gray-800/50 p-2">
          <div className="flex items-center gap-2">
            <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${latestSignal.signal_type === "breakout_long"
              ? "bg-green-900/60 text-green-400"
              : "bg-blue-900/60 text-blue-400"
              }`}>
              {latestSignal.signal_type === "breakout_long" ? "突破追多" : "支撑低吸"}
            </span>
            <span className="text-xs text-white">{latestSignal.trigger_price.toFixed(2)}</span>
            <span className="text-[10px]">{qualityStars(latestSignal.quality_level)}</span>
          </div>
          {latestStopLoss && (
            <div className="mt-1 text-[10px] text-red-400">
              止损: {latestStopLoss.current_price.toFixed(2)} ({latestStopLoss.drawdown_percent.toFixed(1)}%)
            </div>
          )}
          <div className="mt-1 text-[9px] text-gray-500">{timeStr(latestSignal.timestamp)}</div>
        </div>
      ) : (
        <div className="text-xs text-gray-500">暂无交易信号</div>
      )}

      {/* 事件时间线 */}
      {events.length > 0 ? (
        <div className="space-y-1">
          {events.map((e, i) => (
            <div key={i} className="flex items-center gap-1.5 text-[11px]">
              <span className="text-gray-500">{timeStr(e.time)}</span>
              <span>{e.icon}</span>
              <span className={e.color}>{e.text}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-xs text-gray-500">暂无近期事件</div>
      )}
    </div>
  );
}

// ==================== 区域 3 左: 成交量堆积图 ====================

function VolumeProfileChart({ pocData }: { pocData: PocUpdateData | null }) {
  if (!pocData || !pocData.volume_profile) {
    return <div className="text-xs text-gray-500">暂无成交量分布数据</div>;
  }

  const entries = Object.entries(pocData.volume_profile)
    .map(([price, vol]) => ({ price: parseFloat(price), volume: vol as number }))
    .sort((a, b) => b.price - a.price);

  if (entries.length === 0) {
    return <div className="text-xs text-gray-500">暂无成交量分布数据</div>;
  }

  const maxVol = Math.max(...entries.map((e) => e.volume), 1);
  const pocPrice = pocData.poc_price;

  return (
    <div className="flex flex-col gap-[2px] overflow-y-auto" style={{ maxHeight: 180 }}>
      {entries.map((e) => {
        const pct = (e.volume / maxVol) * 100;
        const isPoc = Math.abs(e.price - pocPrice) < 0.01;
        return (
          <div key={e.price} className="flex items-center gap-1.5">
            <span className={`w-[50px] shrink-0 text-right text-[10px] font-mono ${isPoc ? "text-yellow-400 font-bold" : "text-gray-400"}`}>
              {e.price.toFixed(2)}
            </span>
            <div className="relative h-[14px] flex-1">
              <div
                className={`absolute inset-y-0 left-0 rounded-r-sm ${isPoc ? "bg-yellow-500/70" : "bg-cyan-600/50"}`}
                style={{ width: `${Math.max(pct, 2)}%` }}
              />
              <span className="absolute inset-y-0 left-1 flex items-center text-[9px] text-white/60">
                {formatVolume(e.volume)}
              </span>
            </div>
            {isPoc && <span className="text-[9px] text-yellow-400">POC</span>}
          </div>
        );
      })}
    </div>
  );
}

// ==================== 区域 3 右: 盘口力量对比 ====================

function OrderBookBalance({ priceLevels }: { priceLevels: PriceLevelData[] }) {
  const { resistances, supports, buyTotal, sellTotal } = useMemo(() => {
    const res = priceLevels
      .filter((l) => l.side === "resistance")
      .sort((a, b) => a.price - b.price)
      .slice(-6);
    const sup = priceLevels
      .filter((l) => l.side === "support")
      .sort((a, b) => b.price - a.price)
      .slice(0, 6);
    const sellT = res.reduce((s, l) => s + l.volume, 0);
    const buyT = sup.reduce((s, l) => s + l.volume, 0);
    return { resistances: res, supports: sup, buyTotal: buyT, sellTotal: sellT };
  }, [priceLevels]);

  const all = [...resistances, ...supports];
  if (all.length === 0) {
    return <div className="text-xs text-gray-500">暂无盘口数据</div>;
  }

  const maxVol = Math.max(...all.map((l) => l.volume), 1);
  const ratio = sellTotal > 0 ? (buyTotal / sellTotal).toFixed(2) : "∞";

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-col gap-[2px] overflow-y-auto" style={{ maxHeight: 150 }}>
        {/* 卖盘（从低到高显示） */}
        {resistances.map((l) => {
          const pct = (l.volume / maxVol) * 100;
          return (
            <div key={`r-${l.price}`} className="flex items-center gap-1.5">
              <span className="w-[50px] shrink-0 text-right text-[10px] font-mono text-red-400">{l.price.toFixed(2)}</span>
              <div className="relative h-[14px] flex-1">
                <div className="absolute inset-y-0 left-0 rounded-r-sm bg-red-500/50" style={{ width: `${Math.max(pct, 2)}%` }} />
                <span className="absolute inset-y-0 left-1 flex items-center text-[9px] text-white/60">{formatVolume(l.volume)}</span>
              </div>
              <span className="w-[28px] text-[9px] text-red-400/60">卖</span>
            </div>
          );
        })}

        {/* 分隔线 */}
        <div className="my-0.5 border-t border-dashed border-gray-600" />

        {/* 买盘（从高到低显示） */}
        {supports.map((l) => {
          const pct = (l.volume / maxVol) * 100;
          return (
            <div key={`s-${l.price}`} className="flex items-center gap-1.5">
              <span className="w-[50px] shrink-0 text-right text-[10px] font-mono text-green-400">{l.price.toFixed(2)}</span>
              <div className="relative h-[14px] flex-1">
                <div className="absolute inset-y-0 left-0 rounded-r-sm bg-green-500/50" style={{ width: `${Math.max(pct, 2)}%` }} />
                <span className="absolute inset-y-0 left-1 flex items-center text-[9px] text-white/60">{formatVolume(l.volume)}</span>
              </div>
              <span className="w-[28px] text-[9px] text-green-400/60">买</span>
            </div>
          );
        })}
      </div>

      {/* 汇总 */}
      <div className="flex items-center justify-between text-[10px] text-gray-500 px-1 mt-1">
        <span className="text-green-400">挂买: {formatVolume(buyTotal)}</span>
        <span className="text-gray-300">挂单比: {ratio}</span>
        <span className="text-red-400">挂卖: {formatVolume(sellTotal)}</span>
      </div>
    </div>
  );
}

// ==================== 主组件 ====================

export default function ScalpingDetailModal({ stock, onClose }: ScalpingDetailModalProps) {
  const {
    deltaData,
    pocData,
    priceLevels,
    signals,
    momentumIgnitions,
    trapAlerts,
    fakeBreakoutAlerts,
    trueBreakoutConfirms,
    fakeLiquidityAlerts,
    vwapExtension,
    stopLossAlerts,
    tickOutliers,
    patternAlerts,
    actionSignals,
  } = useScalpingSocket(stock.code);

  const hasPatternAlerts = patternAlerts.length > 0;
  const hasActionSignals = actionSignals.length > 0;

  return (
    <>
      {/* 遮罩 */}
      <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} />

      {/* Modal */}
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          className="flex max-h-[90vh] w-[80vw] max-w-[1100px] flex-col overflow-hidden rounded-lg border border-gray-700 bg-gray-900 shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        >
          {/* 头部 */}
          <div className="flex items-center justify-between border-b border-gray-700 px-5 py-2.5">
            <div>
              <h3 className="text-lg font-semibold text-white">{stock.name}</h3>
              <span className="text-sm text-gray-400">{stock.code} · 日内交易概览</span>
            </div>
            <button
              onClick={onClose}
              className="rounded p-1.5 text-gray-400 transition-colors hover:bg-gray-800 hover:text-white"
              aria-label="关闭"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* 第一层: 环境状态条 */}
          <EnvironmentStatusBar deltaData={deltaData} />

          {/* 区域 1: 风险警报条 */}
          <RiskAlertBanner
            trapAlerts={trapAlerts}
            fakeBreakoutAlerts={fakeBreakoutAlerts}
            fakeLiquidityAlerts={fakeLiquidityAlerts}
          />

          {/* 第三层: 行动提示卡（最醒目位置） */}
          {hasActionSignals && (
            <div className="border-b border-gray-700 px-5 py-2">
              <ActionSignalCard signals={actionSignals} />
            </div>
          )}

          {/* 第二层: 行为模式预警 */}
          {hasPatternAlerts && (
            <div className="border-b border-gray-700 px-5 py-2">
              <div className="mb-1 text-xs font-medium text-gray-400">行为预警</div>
              <PatternAlertsList alerts={patternAlerts} />
            </div>
          )}

          {/* 可滚动内容区 */}
          <div className="flex-1 overflow-y-auto">
            {/* 区域 2: 多空态势 + 交易动态 */}
            <div className="grid grid-cols-5 gap-4 border-b border-gray-700 px-5 py-3">
              <div className="col-span-3">
                <div className="mb-1.5 text-xs font-medium text-gray-400">成交力量 <span className="text-gray-500 font-normal">真实成交</span></div>
                <BullBearStatus deltaData={deltaData} />
              </div>
              <div className="col-span-2">
                <div className="mb-1.5 text-xs font-medium text-gray-400">交易动态</div>
                <TradingActivity
                  signals={signals}
                  momentumIgnitions={momentumIgnitions}
                  trueBreakoutConfirms={trueBreakoutConfirms}
                  stopLossAlerts={stopLossAlerts}
                  tickOutliers={tickOutliers}
                  vwapExtension={vwapExtension}
                />
              </div>
            </div>

            {/* 区域 3: 成交量堆积 + 盘口力量 */}
            <div className="grid grid-cols-2 gap-4 border-b border-gray-700 px-5 py-3">
              <div>
                <div className="mb-1.5 text-xs font-medium text-gray-400">成交量堆积（Volume Profile）</div>
                <VolumeProfileChart pocData={pocData} />
              </div>
              <div>
                <div className="mb-1.5 text-xs font-medium text-gray-400">盘口挂单 <span className="text-gray-500 font-normal">可撤销</span></div>
                <OrderBookBalance priceLevels={priceLevels} />
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
