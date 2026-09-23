"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, RefreshCw, TrendingUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  v2Api,
  type V2AlertPerformanceItem,
  type V2AlertPeriodResult,
} from "@/lib/api/v2";
import { clock, pct, tone } from "./format";
import {
  lifecycleCounts, permissionText, signalHeadline, stageText, statusText,
  strategySourceLabel, strategySourcesText,
} from "./signal-lifecycle";

const horizons = ["1", "3", "5", "10"] as const;

const scopes = [
  { id: "candidates", label: "候选池" },
  { id: "watching", label: "资金观察" },
  { id: "confirmed", label: "买点确认" },
  { id: "alerts", label: "正式预警" },
] as const;

type PerformanceScope = (typeof scopes)[number]["id"];

const reasonLabel: Record<string, string> = {
  LOW_POSITION_15M_ACCUMULATION_CONFIRMED: "低位15分钟资金吸收确认",
  FAST_15M_MULTI_INFLOW_CONFIRMED: "15分钟多次流入确认",
  STRONG_TREND_SECOND_INFLOW_CONFIRMED: "强势股二次资金确认",
  STRONG_TREND_SECOND_INFLOW_WATCH: "强势资金观察，等待再次确认",
  POST_INVALIDATION_REVERSAL_WATCH: "失效后低位资金反转观察",
  POST_INVALIDATION_FLOW_RECOVERY_CONFIRMED: "失效候选低位资金恢复确认",
  OVERNIGHT_PRIORITY_LOW_REENTRY_SHADOW_CONFIRMED: "前日强势股次日低位影子确认",
  WEAK_MARKET_60M_STRONG_STOCK_CONFIRMED: "弱市60分钟强股资金确认",
  EXTREME_MARKET_60M_MULTI_INFLOW_CONFIRMED: "极弱市60分钟多次流入确认",
  HARD_STOP_3_PCT: "触及3%硬止损",
  TAKE_PROFIT_5_PCT: "达到5%止盈目标",
  REPEATED_OUTFLOW_AND_STRUCTURE_BREAK: "多次流出且价格结构破位",
  SUSTAINED_DOWNTREND_AND_VWAP_BREAK: "持续下跌且VWAP失守",
  TRAIL_AFTER_SUPPORT_LOST: "失去资金支撑，触发回撤保护",
  PROFIT_FLOOR_AFTER_SUPPORT_LOST: "失去资金支撑，跌破利润保护线",
  CONFIRMED_CANDIDATE_NET_ADVANTAGE: "新候选相对当前持仓优势明确",
};

function localDateKey(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Hong_Kong" }).format(new Date());
}

function ratio(value: number | null): string {
  return value == null ? "待观察" : `${(value * 100).toFixed(1)}%`;
}

function versionLabel(value: string): string {
  const revision = value.split("-").at(-1) || value;
  return `策略版本 ${revision.slice(0, 8)}`;
}

function stagePath(item: V2AlertPerformanceItem): string {
  return (["SETUP", "WATCHING", "CONFIRMED"] as const)
    .flatMap((stage) => {
      const point = item.stage_points[stage];
      return point
        ? [`${stageText[stage]} ${clock(point.time)} / ${point.price.toFixed(3)}`]
        : [];
    })
    .join(" · ");
}

function PeriodCell({ value }: { value: V2AlertPeriodResult }) {
  if (
    value.status === "PENDING" &&
    value.close_return_pct == null &&
    value.max_return_pct == null
  ) {
    return <span className="text-xs text-muted-foreground">待观察</span>;
  }
  const live = value.status === "LIVE";
  const partial = value.status === "PARTIAL";
  const current = live || partial ? value.latest_return_pct ?? null : value.close_return_pct;
  return <div className="min-w-24 space-y-0.5 tabular-nums">
    <div className={`text-xs font-semibold ${tone(current)}`}>
      {live ? "当前" : partial ? "末次可见" : "收盘"} {pct(current)}
    </div>
    <div className="text-[11px] text-muted-foreground">
      最好 <span className={tone(value.max_return_pct)}>{pct(value.max_return_pct)}</span>
    </div>
    <div className="text-[11px] text-muted-foreground">
      最差 <span className={tone(value.max_drawdown_pct)}>{pct(value.max_drawdown_pct)}</span>
    </div>
    <div className={value.is_stale ? "text-[10px] font-medium text-amber-700 dark:text-amber-400" : "text-[10px] text-muted-foreground"}>
      {value.observed_through
        ? value.is_stale
          ? `行情已中断，末次 ${clock(value.observed_through)}`
          : `截至 ${clock(value.observed_through)}`
        : value.intraday_covered ? "信号后分钟统计"
        : value.status === "OBSERVING" ? "盘中跟踪" : value.trading_day?.slice(5) || "待观察"}
    </div>
    {value.observed_from && <div className="text-[10px] text-muted-foreground">
      可见路径自 {clock(value.observed_from)} 起
    </div>}
    {partial && <div className="text-[10px] text-amber-700 dark:text-amber-400">待补收盘数据</div>}
  </div>;
}

export function AlertPerformance() {
  const [tradeDate, setTradeDate] = useState(localDateKey);
  const [scope, setScope] = useState<PerformanceScope>("candidates");
  const query = useQuery({
    queryKey: ["v2", "alert-performance", tradeDate, scope],
    queryFn: ({ signal }) => v2Api.alertPerformance(tradeDate, scope, signal),
    retry: false,
    staleTime: 45_000,
    refetchInterval: 60_000,
  });
  const data = query.data;
  const lifecycle = data ? lifecycleCounts(data) : null;

  return <section>
    <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
      <div>
        <div className="flex items-center gap-2 text-sm font-semibold">
          <TrendingUp className="h-4 w-4 text-emerald-500" />预警后续表现
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          按首次进入所选阶段的参考价计算；盘中结果尚未结算，未计交易费用。
        </p>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <div className="flex h-9 border border-border bg-muted/25 p-0.5" aria-label="复盘样本范围">
          {scopes.map((item) => <button
            key={item.id}
            type="button"
            onClick={() => setScope(item.id)}
            className={`px-3 text-xs font-medium ${scope === item.id ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
          >{item.label}</button>)}
        </div>
        <label className="flex h-9 items-center gap-2 border border-border bg-background px-2 text-xs">
          <CalendarDays className="h-4 w-4 text-muted-foreground" />
          <input
            type="date"
            value={tradeDate}
            onChange={(event) => setTradeDate(event.target.value)}
            className="bg-transparent outline-none"
            aria-label="选择预警日期"
          />
        </label>
        <Button
          variant="outline"
          size="icon"
          onClick={() => query.refetch()}
          disabled={query.isFetching}
          aria-label="刷新预警表现"
          title="刷新预警表现"
        >
          <RefreshCw className={`h-4 w-4 ${query.isFetching ? "animate-spin" : ""}`} />
        </Button>
      </div>
    </div>

    {query.isError && <div className="border-l-2 border-rose-500 bg-rose-500/8 px-3 py-3 text-sm text-rose-700 dark:text-rose-300">
      预警后续数据读取失败，本次请求已结束，稍后自动刷新。
    </div>}
    {data?.refresh_status === "STALE" && <div role="status" className="mb-3 border-l-2 border-amber-500 bg-amber-500/8 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">行情刷新暂时失败，当前为 {clock(data.as_of)} 的缓存快照，非最新结果。</div>}

    {query.isLoading && <div className="h-48 animate-pulse bg-muted/30" />}

    {data && <>
      <div className="grid grid-cols-2 border-y border-border md:grid-cols-5">
        <div className="px-3 py-3"><div className="text-[11px] text-muted-foreground">当日样本</div><div className="mt-1 text-lg font-semibold tabular-nums">{data.count}</div></div>
        {horizons.map((horizon) => {
          const metric = data.summary.periods[horizon];
          return <div key={horizon} className="border-l border-border px-3 py-3">
            <div className="text-[11px] text-muted-foreground">{horizon}日胜率 · {metric.completed_count}个已完成</div>
            <div className="mt-1 flex items-baseline gap-2"><strong className="text-lg tabular-nums">{ratio(metric.win_ratio)}</strong><span className={`text-xs ${tone(metric.mean_return_pct)}`}>均值 {pct(metric.mean_return_pct)}</span></div>
            <div className="mt-1 text-[11px] text-muted-foreground">最高达到1.5%：{ratio(metric.reached_1_5_ratio)} · {metric.opportunity_count}个有路径数据</div>
          </div>;
        })}
      </div>

      {data.excluded.total > 0 && <div className="mt-3 border-l-2 border-amber-500 bg-amber-500/8 px-3 py-2 text-xs text-amber-800 dark:text-amber-200">
        已排除 {data.excluded.total} 条无效正式预警：风控未通过 {data.excluded.by_reason.RISK_NOT_APPROVED || 0} 条，非正常交易时段 {data.excluded.by_reason.OUTSIDE_REGULAR_SESSION || 0} 条。
      </div>}

      {lifecycle && <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-y border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
        <span>当前有效 <strong className="text-foreground">{lifecycle.active}</strong></span>
        <span>当前已失效 <strong className="text-foreground">{lifecycle.invalidated}</strong></span>
        <span>当日曾确认 <strong className="text-foreground">{lifecycle.confirmed}</strong></span>
        <span>正式提醒资格或接口已接受 <strong className="text-foreground">{lifecycle.formal}</strong></span>
      </div>}

      {Object.keys(data.summary_by_strategy_source).length > 0 && <div className="mt-3 overflow-x-auto border-y border-border">
        <table className="w-full min-w-[680px] text-left text-xs">
          <thead className="bg-muted/25 text-[11px] text-muted-foreground"><tr>
            <th className="px-3 py-2 font-medium">基准时策略</th>
            <th className="px-3 py-2 font-medium">样本</th>
            <th className="px-3 py-2 font-medium">当日平均涨跌</th>
            <th className="px-3 py-2 font-medium">当日达到1.5%</th>
            <th className="px-3 py-2 font-medium">1日平均涨跌</th>
          </tr></thead>
          <tbody className="divide-y divide-border/70">
            {Object.entries(data.summary_by_strategy_source).map(([source, summary]) => <tr key={source}>
              <td className="px-3 py-2 font-medium">{strategySourceLabel(source)}</td>
              <td className="px-3 py-2 tabular-nums">{summary.alert_count}</td>
              <td className={`px-3 py-2 tabular-nums ${tone(summary.same_day.mean_return_pct)}`}>{pct(summary.same_day.mean_return_pct)}</td>
              <td className="px-3 py-2 tabular-nums">{ratio(summary.same_day.reached_1_5_ratio)}</td>
              <td className={`px-3 py-2 tabular-nums ${tone(summary.periods["1"].mean_return_pct)}`}>{pct(summary.periods["1"].mean_return_pct)}</td>
            </tr>)}
          </tbody>
        </table>
      </div>}

      <div className="mt-3 overflow-x-auto border-y border-border">
        <table className="w-full min-w-[1280px] text-left">
          <thead className="bg-muted/35 text-[11px] text-muted-foreground"><tr>
            <th className="px-3 py-2 font-medium">股票</th>
            <th className="px-3 py-2 font-medium">提醒</th>
            <th className="px-3 py-2 font-medium">预警基准</th>
            <th className="px-3 py-2 font-medium">当日</th>
            {horizons.map((horizon) => <th key={horizon} className="px-3 py-2 font-medium">{horizon}个交易日</th>)}
          </tr></thead>
          <tbody className="divide-y divide-border/70 text-xs">
            {data.items.map((item) => <tr key={`${item.signal_date}-${item.stock_code}-${item.action}-${item.strategy_version}`} className="align-top">
              <td className="px-3 py-3"><div className="font-semibold">{item.stock_name || item.stock_code}</div><div className="mt-0.5 text-[11px] text-muted-foreground">{item.stock_code}</div></td>
              <td className="px-3 py-3"><div className="font-medium">{signalHeadline(item)}</div><div className="mt-0.5 text-[11px] text-muted-foreground">当前：{statusText[item.current_status]} · {permissionText[item.alert_permission]}</div><div className="mt-0.5 text-[11px] text-muted-foreground">首次 {stageText[item.entry_stage]} → 最高 {stageText[item.max_stage]}</div><div className="mt-0.5 max-w-72 text-[11px] text-muted-foreground">基准时策略：{strategySourcesText(item.strategy_sources)}</div><div className="mt-1 max-w-72 text-[11px] text-muted-foreground">{stagePath(item)}</div><div className="mt-1 max-w-72 text-[11px] text-muted-foreground" title={reasonLabel[item.current_reason_code] || item.current_reason_code}>{reasonLabel[item.current_reason_code] || "查看当前判断详情"}</div></td>
              <td className="px-3 py-3 tabular-nums"><div className="font-semibold">{item.signal_price.toFixed(3)}</div><div className="mt-0.5 text-[11px] text-muted-foreground">{stageText[item.entry_stage]} · {clock(item.signal_time)} · {item.alert_count}次</div><div className="text-[11px] text-muted-foreground">状态更新 {clock(item.current_state_time)}</div><div className="text-[11px] text-muted-foreground">{item.risk_result === "NOT_REQUIRED" ? "候选跟踪" : `风控 ${item.risk_result === "APPROVED" ? "通过" : "受限"}`}</div><div className="text-[10px] text-muted-foreground">{versionLabel(item.strategy_version)}</div></td>
              <td className="px-3 py-3"><PeriodCell value={item.same_day} /></td>
              {horizons.map((horizon) => <td key={horizon} className="px-3 py-3"><PeriodCell value={item.periods[horizon]} /></td>)}
            </tr>)}
          </tbody>
        </table>
        {!data.items.length && <div className="flex h-36 items-center justify-center text-sm text-muted-foreground">所选日期没有符合当前范围的复盘样本</div>}
      </div>
      <div className="mt-2 text-right text-[11px] text-muted-foreground">
        信号后有路径数据 {data.intraday_coverage_count}/{data.count} · 策略版本 {Object.keys(data.summary_by_strategy_version).length} 个 · 后续日线更新至 {data.available_kline_through || "尚无可用交易日"}
      </div>
    </>}
  </section>;
}
