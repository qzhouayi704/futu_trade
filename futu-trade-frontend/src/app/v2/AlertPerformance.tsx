"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, RefreshCw, TrendingUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { v2Api, type V2AlertPeriodResult } from "@/lib/api/v2";
import { clock, pct, tone } from "./format";

const horizons = ["1", "3", "5", "10"] as const;

const actionLabel: Record<string, string> = {
  CANDIDATE: "进入候选",
  BUY: "买入提醒",
  SELL: "卖出提醒",
  ROTATE: "换入提醒",
};

const scopes = [
  { id: "candidates", label: "候选池" },
  { id: "watching", label: "资金观察" },
  { id: "alerts", label: "正式预警" },
] as const;

type PerformanceScope = (typeof scopes)[number]["id"];

const stageLabel: Record<string, string> = {
  SETUP: "候选准备",
  WATCHING: "资金观察",
  CONFIRMED: "买点确认",
};

const reasonLabel: Record<string, string> = {
  LOW_POSITION_15M_ACCUMULATION_CONFIRMED: "低位15分钟资金吸收确认",
  FAST_15M_MULTI_INFLOW_CONFIRMED: "15分钟多次流入确认",
  STRONG_TREND_SECOND_INFLOW_CONFIRMED: "强势股二次资金确认",
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
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

function ratio(value: number | null): string {
  return value == null ? "待观察" : `${(value * 100).toFixed(1)}%`;
}

function PeriodCell({ value }: { value: V2AlertPeriodResult }) {
  if (
    value.status === "PENDING" &&
    value.close_return_pct == null &&
    value.max_return_pct == null
  ) {
    return <span className="text-xs text-muted-foreground">待观察</span>;
  }
  return <div className="min-w-24 space-y-0.5 tabular-nums">
    <div className={`text-xs font-semibold ${tone(value.close_return_pct)}`}>
      收盘 {pct(value.close_return_pct)}
    </div>
    <div className="text-[11px] text-muted-foreground">
      最好 <span className={tone(value.max_return_pct)}>{pct(value.max_return_pct)}</span>
    </div>
    <div className="text-[11px] text-muted-foreground">
      最差 <span className={tone(value.max_drawdown_pct)}>{pct(value.max_drawdown_pct)}</span>
    </div>
    <div className="text-[10px] text-muted-foreground">
      {value.source === "TICKER_MINUTE"
        ? "逐笔分钟统计"
        : value.status === "OBSERVING" ? "盘中跟踪" : value.trading_day?.slice(5) || "待观察"}
    </div>
  </div>;
}

export function AlertPerformance() {
  const [tradeDate, setTradeDate] = useState(localDateKey);
  const [scope, setScope] = useState<PerformanceScope>("candidates");
  const query = useQuery({
    queryKey: ["v2", "alert-performance", tradeDate, scope],
    queryFn: () => v2Api.alertPerformance(tradeDate, scope),
    refetchInterval: 60_000,
  });
  const data = query.data;

  return <section>
    <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
      <div>
        <div className="flex items-center gap-2 text-sm font-semibold">
          <TrendingUp className="h-4 w-4 text-emerald-500" />预警后续表现
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          按首次进入所选阶段时的价格计算；同一股票当天后续升级合并统计。
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
      预警后续数据读取失败，系统会继续重试。
    </div>}

    {query.isLoading && <div className="h-48 animate-pulse bg-muted/30" />}

    {data && <>
      <div className="grid grid-cols-2 border-y border-border md:grid-cols-5">
        <div className="px-3 py-3"><div className="text-[11px] text-muted-foreground">当日样本</div><div className="mt-1 text-lg font-semibold tabular-nums">{data.count}</div></div>
        {horizons.map((horizon) => {
          const metric = data.summary.periods[horizon];
          return <div key={horizon} className="border-l border-border px-3 py-3">
            <div className="text-[11px] text-muted-foreground">{horizon}日胜率 · {metric.completed_count}个已完成</div>
            <div className="mt-1 flex items-baseline gap-2"><strong className="text-lg tabular-nums">{ratio(metric.win_ratio)}</strong><span className={`text-xs ${tone(metric.mean_return_pct)}`}>均值 {pct(metric.mean_return_pct)}</span></div>
          </div>;
        })}
      </div>

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
            {data.items.map((item) => <tr key={`${item.signal_date}-${item.stock_code}-${item.action}`} className="align-top">
              <td className="px-3 py-3"><div className="font-semibold">{item.stock_name || item.stock_code}</div><div className="mt-0.5 text-[11px] text-muted-foreground">{item.stock_code}</div></td>
              <td className="px-3 py-3"><div className="font-medium">{actionLabel[item.action] || "交易提醒"}</div><div className="mt-0.5 text-[11px] text-muted-foreground">{stageLabel[item.entry_stage]} → {stageLabel[item.max_stage]}</div><div className="mt-1 max-w-52 text-[11px] text-muted-foreground" title={reasonLabel[item.reason_code] || item.reason_code}>{reasonLabel[item.reason_code] || "系统交易条件确认"}</div></td>
              <td className="px-3 py-3 tabular-nums"><div className="font-semibold">{item.signal_price.toFixed(3)}</div><div className="mt-0.5 text-[11px] text-muted-foreground">{clock(item.signal_time)} · {item.alert_count}次</div><div className="text-[11px] text-muted-foreground">{item.risk_result === "NOT_REQUIRED" ? "候选跟踪" : `风控 ${item.risk_result === "APPROVED" ? "通过" : "受限"}`}</div></td>
              <td className="px-3 py-3"><PeriodCell value={item.same_day} /></td>
              {horizons.map((horizon) => <td key={horizon} className="px-3 py-3"><PeriodCell value={item.periods[horizon]} /></td>)}
            </tr>)}
          </tbody>
        </table>
        {!data.items.length && <div className="flex h-36 items-center justify-center text-sm text-muted-foreground">所选日期没有符合当前范围的复盘样本</div>}
      </div>
      <div className="mt-2 text-right text-[11px] text-muted-foreground">
        当日逐笔覆盖 {data.intraday_coverage_count}/{data.count} · 后续日线更新至 {data.available_kline_through || "尚无可用交易日"}
      </div>
    </>}
  </section>;
}
