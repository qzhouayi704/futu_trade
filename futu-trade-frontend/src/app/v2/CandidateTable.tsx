import { ShieldAlert } from "lucide-react";
import type { V2Candidate } from "@/lib/api/v2";
import { clock, money, pct, tone } from "./format";

const statusTone: Record<string, string> = {
  CONFIRMED: "bg-emerald-500/12 text-emerald-600 dark:text-emerald-400",
  SETUP: "bg-amber-500/12 text-amber-700 dark:text-amber-400",
  WATCHING: "bg-sky-500/12 text-sky-700 dark:text-sky-400",
  INVALIDATED: "bg-rose-500/12 text-rose-700 dark:text-rose-400",
};

const reasonLabel: Record<string, string> = {
  HOT_ACTIVE_DAILY_SETUP: "热门活跃，等待资金确认",
  FIRST_STRONG_INFLOW_WATCH: "首次强流入，继续观察",
  CAPITAL_MEMORY_REVERSAL_WATCH: "全天吸收转强，等待多次资金确认",
  CAPITAL_MEMORY_MULTI_INFLOW_SHADOW_CONFIRMED: "资金记忆多次流入影子确认",
  CAPITAL_MEMORY_TURNED_DISTRIBUTING: "近期资金转为明显流出",
  LOW_POSITION_ACCUMULATION_WATCH: "低位多次吸收，等待环境确认",
  LOW_POSITION_60M_ACCUMULATION_CONFIRMED: "低位60分钟吸收确认",
  LOW_POSITION_15M_ACCUMULATION_CONFIRMED: "低位15分钟吸收确认",
  LEGACY_RALLY_STRONG_WATCH: "量价齐升，等待多次流入确认",
  LEGACY_RALLY_SETUP_WATCH: "量价齐升，升级观察",
  SOFT_GATE_STRONG_SIGNAL_REENTRY: "强信号恢复观察",
  FAST_15M_MULTI_INFLOW_CONFIRMED: "15分钟多次流入确认",
  STRICT_MOMENTUM_WATCH: "严格动量，等待三次资金确认",
  STRICT_MOMENTUM_SHADOW_CONFIRMED: "严格热门动量影子确认",
  WEAK_MARKET_60M_STRONG_STOCK_CONFIRMED: "弱市60分钟强势确认",
  EXTREME_MARKET_60M_MULTI_INFLOW_CONFIRMED: "极弱市60分钟多次确认",
};

const strategyLabel: Record<string, string> = {
  capital_absorption: "低位吸收",
  capital_memory_reversal: "资金转强",
  momentum_continuation: "严格动量",
};

const memoryStateLabel: Record<string, string> = {
  NEUTRAL: "中性",
  ACCUMULATING: "持续流入",
  REVERSING: "流出修复",
  ABSORBING: "吸收中",
  DECAYING: "优势衰减",
  DISTRIBUTING: "资金流出",
};

function FlowCell({ item }: { item: V2Candidate }) {
  const memory = item.capital_memory;
  const windows = [900, 3600].map((seconds) => item.capital_windows.find((window) => window.window_seconds === seconds));
  return (
    <div className="min-w-56 text-xs tabular-nums">
      {memory && (
        <div className="mb-1 flex items-center gap-2">
          <span className="font-medium">{memoryStateLabel[memory.state] || memory.state}</span>
          <span className="text-muted-foreground">记忆 {memory.score.toFixed(0)}</span>
          <span className={tone(memory.decayed_main_net)}>衰减 {money(memory.decayed_main_net)}</span>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        {windows.map((window, index) => (
          <div key={index}>
            <span className="text-muted-foreground">{index ? "60m" : "15m"} </span>
            <span className={tone(window?.main_net)}>{money(window?.main_net)}</span>
            <span className="ml-1 text-muted-foreground">{window ? `${window.independent_buy_events}/${window.independent_sell_events}` : "--"}</span>
          </div>
        ))}
      </div>
      {memory && <div className="mt-1 text-[11px] text-muted-foreground">全天 {money(memory.day_main_net)} · 15m {money(memory.recent_15m_main_net)} · {memory.recent_15m_buy_events}/{memory.recent_15m_sell_events} 次</div>}
    </div>
  );
}

export function CandidateTable({ items, compact = false }: { items: V2Candidate[]; compact?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[920px] text-left text-xs">
        <thead className="border-b border-border bg-muted/35 text-muted-foreground">
          <tr>
            <th className="px-3 py-2 font-medium">标的</th><th className="px-3 py-2 font-medium">状态</th>
            <th className="px-3 py-2 font-medium">评分</th><th className="px-3 py-2 font-medium">现价 / 确认价</th>
            <th className="px-3 py-2 font-medium">资金净额 · 流入/流出次数</th><th className="px-3 py-2 font-medium">位置 / 环境</th>
            <th className="px-3 py-2 font-medium">更新时间</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/70">
          {items.slice(0, compact ? 6 : undefined).map((item) => {
            const current = item.quote?.last_price;
            const fromConfirm = current && item.confirmed_price ? (current / item.confirmed_price - 1) * 100 : null;
            const shadowConfirmed = item.status === "CONFIRMED" && item.alert_eligible === false;
            const displayStatus = shadowConfirmed ? "影子确认" : item.status;
            const displayTone = shadowConfirmed
              ? statusTone.WATCHING
              : statusTone[item.status] || "bg-muted text-muted-foreground";
            return (
              <tr key={item.stock_code} className="h-14 hover:bg-muted/25">
                <td className="px-3 py-2"><div className="font-semibold">{item.stock_name || item.stock_code}</div><div className="text-muted-foreground">{item.stock_code}</div></td>
                <td className="max-w-52 px-3 py-2"><span className={`inline-flex rounded px-2 py-1 font-medium ${displayTone}`}>{displayStatus}</span><div className="mt-1 truncate text-[11px] text-muted-foreground" title={reasonLabel[item.reason_code] || item.reason_code}>{reasonLabel[item.reason_code] || item.reason_code}</div></td>
                <td className="px-3 py-2">
                  <div className="text-base font-semibold tabular-nums">{(item.portfolio_score ?? item.score)?.toFixed(1) ?? "--"}</div>
                  <div className="mt-1 flex max-w-48 flex-wrap gap-1">
                    {item.strategy_sources?.map((source) => (
                      <span key={source} className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-700 dark:text-emerald-400">
                        {strategyLabel[source] || source}
                      </span>
                    ))}
                    {!item.strategy_sources?.length && <span className="text-[10px] text-muted-foreground">条件组合观察</span>}
                  </div>
                </td>
                <td className="px-3 py-2 tabular-nums"><div>{current?.toFixed(3) ?? "--"} / {item.confirmed_price?.toFixed(3) ?? "--"}</div><div className={tone(fromConfirm)}>{pct(fromConfirm)}</div></td>
                <td className="px-3 py-2"><FlowCell item={item} /></td>
                <td className="px-3 py-2"><div>日线 {item.price_position?.daily_percentile == null ? "--" : pct(item.price_position.daily_percentile * 100, 0)} · {item.market_context?.market_regime || "--"}</div><div className="text-muted-foreground">全市 {pct((item.market_context?.market_breadth ?? 0) * 100, 0)} · 板块 {item.market_context?.sector_breadth == null ? "--" : pct(item.market_context.sector_breadth * 100, 0)}</div></td>
                <td className="px-3 py-2 text-muted-foreground">{clock(item.updated_at)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {!items.length && <div className="flex h-36 items-center justify-center gap-2 text-sm text-muted-foreground"><ShieldAlert className="h-4 w-4" />暂无候选状态</div>}
    </div>
  );
}
