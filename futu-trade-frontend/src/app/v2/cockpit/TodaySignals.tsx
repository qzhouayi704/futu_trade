"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ArrowUpDown, Minus, RefreshCw, Search, TrendingUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { v2Api, type V2AlertPerformanceItem } from "@/lib/api/v2";
import { candidateReasonText } from "../CandidateTable";
import { pct, tone } from "../format";
import {
  marketDateKey, signalClock, signalSortColumns, sortTodaySignals, todaySignalRow, todaySignalSummary, toggleSignalSort,
  type SignalSort, type SignalSortColumn, type TodaySignalRow,
} from "./today-signal-metrics";

const scopes = [
  { id: "candidates", label: "候选池" },
  { id: "watching", label: "资金观察" },
  { id: "confirmed", label: "买点确认" },
  { id: "alerts", label: "正式预警" },
] as const;
const stages = { SETUP: "候选准备", WATCHING: "资金观察", CONFIRMED: "买点确认" };

function SortHeader({ column, sort, onSort }: { column: SignalSortColumn; sort: SignalSort; onSort: (value: SignalSort) => void }) {
  const ascending = sort === column.ascending;
  const descending = sort === column.descending;
  const next = toggleSignalSort(sort, column);
  const Icon = ascending ? ArrowUp : descending ? ArrowDown : ArrowUpDown;
  return <th scope="col" aria-sort={ascending ? "ascending" : descending ? "descending" : undefined} className="border-b border-border px-3 py-2 font-medium">
    <button type="button" onClick={() => onSort(next)} aria-label={`${column.label}排序`}
      title={`按${column.label}${next === column.ascending ? "升序" : "降序"}排列`}
      className={`inline-flex min-h-7 items-center gap-1 whitespace-nowrap rounded-sm outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring ${ascending || descending ? "text-foreground" : "text-muted-foreground"}`}>
      {column.label}<Icon aria-hidden="true" className="h-3 w-3 shrink-0" />
    </button>
  </th>;
}

function signalLabel(item: V2AlertPerformanceItem): string {
  if (item.action === "SELL") return "卖出提醒";
  if (item.action === "ROTATE") return "换入提醒";
  if (item.action === "BUY") return "买入提醒";
  return stages[item.entry_stage];
}

function versionLabel(version: string): string {
  return `版本 ${version.split("-").at(-1)?.slice(0, 8) || "未知"}`;
}

function SignalDetails({ item }: { item: V2AlertPerformanceItem }) {
  return <details className="mt-1 text-[11px] text-muted-foreground"><summary className="cursor-pointer">阶段记录 · {item.alert_count}次</summary><div className="mt-1 space-y-1">
    {(["SETUP", "WATCHING", "CONFIRMED"] as const).map((stage) => {
      const point = item.stage_points[stage];
      return point && <div key={stage}>{stages[stage]} {signalClock(point.time)} / {point.price.toFixed(3)}</div>;
    })}
    <div className="max-w-52 break-words">{candidateReasonText(item.reason_code)}</div>
    <div>当日最高阶段：{stages[item.max_stage]}</div>
    <div>最近同类信号：{signalClock(item.last_alert_time)}</div>
    {item.same_day.observed_from && <div>可见路径自 {signalClock(item.same_day.observed_from)} 起</div>}
  </div></details>;
}

function ChangeCounts({ counts }: { counts: { up: number; down: number; flat: number } }) {
  return <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
    <span className="flex items-center gap-1"><ArrowUp className="h-3 w-3" />上涨 {counts.up}</span>
    <span className="flex items-center gap-1"><Minus className="h-3 w-3" />持平 {counts.flat}</span>
    <span className="flex items-center gap-1"><ArrowDown className="h-3 w-3" />下跌 {counts.down}</span>
  </div>;
}

function Observation({ row }: { row: TodaySignalRow }) {
  const result = row.item.same_day;
  const settled = result.status === "READY";
  const label = row.change == null ? "等待行情"
    : row.change === 0 ? "与信号价持平"
    : row.item.direction === "SELL"
      ? row.change < 0 ? "卖出后回落" : "卖出后反涨"
      : row.change > 0 ? "信号后上涨" : "信号后回落";
  const adverse = row.change != null && (row.item.direction === "SELL" ? row.change > 0 : row.change < 0);
  return <div className="space-y-1">
    <div className={adverse ? "text-amber-700 dark:text-amber-400" : "text-foreground"}>{label}</div>
    <div className="text-[11px] text-muted-foreground">
      {settled ? "已补收盘" : result.status === "PARTIAL" ? "待补收盘" : "盘中未结算"}
    </div>
    {result.observed_through
      ? <div className="text-[11px] text-muted-foreground">行情截至 {signalClock(result.observed_through)}</div>
      : row.change != null && !settled && <div className="text-[11px] text-amber-700 dark:text-amber-400">采样时间未提供</div>}
    {!result.intraday_covered && <div className="text-[11px] text-amber-700 dark:text-amber-400">缺少信号后路径</div>}
  </div>;
}

export function TodaySignals() {
  const [tradeDate, setTradeDate] = useState(marketDateKey);
  const [scope, setScope] = useState<(typeof scopes)[number]["id"]>("candidates");
  const [search, setSearch] = useState("");
  const [version, setVersion] = useState("");
  const [sort, setSort] = useState<SignalSort>("latest");
  const [slowQuery, setSlowQuery] = useState(false);
  useEffect(() => {
    const update = () => setTradeDate(marketDateKey());
    const timer = window.setInterval(update, 60_000);
    window.addEventListener("focus", update);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", update); };
  }, []);
  const query = useQuery({
    queryKey: ["v2", "alert-performance", tradeDate, scope],
    queryFn: ({ signal }) => v2Api.alertPerformance(tradeDate, scope, signal),
    retry: false,
    staleTime: 45_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });
  useEffect(() => {
    setSlowQuery(false);
    if (!query.isFetching) return;
    const timer = window.setTimeout(() => setSlowQuery(true), 8_000);
    return () => window.clearTimeout(timer);
  }, [query.isFetching, tradeDate, scope]);
  // Never carry a previous date or scope into today's scorecard.
  const data = query.data?.trade_date === tradeDate && query.data.scope === scope ? query.data : undefined;
  const versions = [...new Set(data?.items.map((item) => item.strategy_version) || [])].sort();
  const activeVersion = versions.includes(version) ? version : "";
  const needle = search.trim().toLocaleLowerCase();
  const rows = sortTodaySignals((data?.items || [])
    .filter((item) => !activeVersion || item.strategy_version === activeVersion)
    .filter((item) => `${item.stock_code} ${item.stock_name}`.toLocaleLowerCase().includes(needle))
    .map(todaySignalRow), sort);
  const summary = todaySignalSummary(rows);

  return <section aria-labelledby="today-signals-title">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0">
        <h2 id="today-signals-title" className="flex items-center gap-2 text-sm font-semibold"><TrendingUp className="h-4 w-4 text-emerald-500" />今日信号表现</h2>
        <div className="mt-1 flex flex-wrap gap-x-2 text-[11px] text-muted-foreground"><span>{tradeDate}</span><span>参考价表现 · 非实盘盈亏 · 未计费用</span></div>
      </div>
      <div className="flex max-w-full items-center gap-2">
        <div className="flex min-w-0 flex-wrap border border-border bg-muted/25 p-0.5" role="group" aria-label="今日信号范围">
          {scopes.map((option) => <button key={option.id} type="button" aria-pressed={scope === option.id}
            onClick={() => { setScope(option.id); setVersion(""); }}
            className={`min-h-8 px-2 text-xs font-medium sm:px-3 ${scope === option.id ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>{option.label}</button>)}
        </div>
        <Button className="shrink-0" variant="outline" size="icon" onClick={() => query.refetch()} disabled={query.isFetching} aria-label="刷新今日信号" title="刷新今日信号">
          <RefreshCw className={`h-4 w-4 ${query.isFetching ? "animate-spin" : ""}`} />
        </Button>
      </div>
    </div>

    {query.isError && <div role="alert" className="mb-3 border-l-2 border-rose-500 bg-rose-500/8 px-3 py-2 text-xs text-rose-700 dark:text-rose-300">
      今日信号读取失败，本次请求已结束，稍后自动刷新。{data ? "下方保留上次成功数据，非最新结果。" : "暂时无法判断今日信号表现。"}
    </div>}
    {query.isLoading && <div role="status" className="flex h-40 items-center justify-center bg-muted/20 text-xs text-muted-foreground">{slowQuery ? "服务器查询较慢，本次请求最长等待20秒..." : "正在读取今日信号与后续行情..."}</div>}
    {data?.refresh_status === "STALE" && <div role="status" className="mb-3 border-l-2 border-amber-500 bg-amber-500/8 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">行情刷新暂时失败，保留 {signalClock(data.as_of)} 的缓存快照，非最新结果。</div>}
    {data && <>
      <div className="grid grid-cols-2 divide-y divide-border border-y border-border xl:grid-cols-4 xl:divide-y-0">
        <div className="px-3 py-3">
          <div className="text-[11px] text-muted-foreground">当前范围样本</div>
          <div className="mt-1 text-xl font-semibold tabular-nums">{summary.count}</div>
          <div className="mt-1 text-[11px] text-muted-foreground">有行情 {summary.observed} · 待行情 {summary.count - summary.observed} · 已结算 {summary.settled}</div>
        </div>
        <div className="border-l border-border px-3 py-3">
          <div className="text-[11px] text-muted-foreground">买入 / 观察后平均涨跌 · {summary.buys.count}个有行情</div>
          <div className={`mt-1 text-xl font-semibold tabular-nums ${tone(summary.buys.mean)}`}>{pct(summary.buys.mean)}</div>
          <ChangeCounts counts={summary.buys} />
        </div>
        <div className="px-3 py-3 xl:border-l xl:border-border">
          <div className="text-[11px] text-muted-foreground">卖出后股价平均涨跌 · {summary.sells.count}个有行情</div>
          <div className={`mt-1 text-xl font-semibold tabular-nums ${tone(summary.sells.mean)}`}>{pct(summary.sells.mean)}</div>
          <ChangeCounts counts={summary.sells} />
        </div>
        <div className="border-l border-border px-3 py-3">
          <div className="text-[11px] text-muted-foreground">买入 / 观察后曾涨至</div>
          <div className="mt-1 flex flex-wrap gap-x-4 text-sm tabular-nums"><span>+3% <strong className="text-xl">{summary.reached3}</strong>个</span><span>+5% <strong className="text-xl">{summary.reached5}</strong>个</span></div>
          <div className="mt-1 text-[11px] text-muted-foreground">{summary.paths}个有路径样本 · 最高可见涨幅</div>
        </div>
      </div>

      <div className="my-3 flex flex-wrap items-center justify-between gap-2">
        <label className="flex h-8 w-full items-center gap-2 border border-border px-2 sm:w-56"><Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" /><input value={search} onChange={(event) => setSearch(event.target.value)} aria-label="搜索今日信号股票" placeholder="股票名称或代码" className="min-w-0 w-full bg-transparent text-xs outline-none" /></label>
        <div className="flex max-w-full flex-wrap items-center gap-2 text-xs">
          {versions.length > 1 && <select aria-label="今日信号策略版本" value={activeVersion} onChange={(event) => setVersion(event.target.value)} className="h-8 max-w-full border border-border bg-background px-2"><option value="">全部策略版本</option>{versions.map((value) => <option key={value} value={value}>{versionLabel(value)}</option>)}</select>}
          <select aria-label="今日信号排序" value={sort} onChange={(event) => setSort(event.target.value as SignalSort)} className="h-8 max-w-full border border-border bg-background px-2">
            {signalSortColumns.map((column) => <optgroup key={column.field} label={column.label}>
              <option value={column.descending}>{column.label}：{column.field === "time" ? "新到旧" : "降序"}</option>
              <option value={column.ascending}>{column.label}：{column.field === "time" ? "旧到新" : "升序"}</option>
            </optgroup>)}
          </select>
          <span className="text-[11px] text-muted-foreground">{rows.length} / {data.count} 条</span>
        </div>
      </div>
      {data.excluded.total > 0 && <div className="mb-2 text-xs text-amber-700 dark:text-amber-400">已排除 {data.excluded.total} 条风控未通过或非正常交易时段的正式预警</div>}
      <div className="max-h-[480px] overflow-auto border-y border-border" role="region" aria-label="今日信号明细" tabIndex={0}>
        <table className="hidden w-full min-w-[1080px] text-left text-xs md:table">
          <thead className="sticky top-0 z-10 bg-background text-[11px] text-muted-foreground"><tr>
            {signalSortColumns.map((column) => <SortHeader key={column.field} column={column} sort={sort} onSort={setSort} />)}
            <th scope="col" className="border-b border-border px-3 py-2 font-medium">后续情况</th>
          </tr></thead>
          <tbody className="divide-y divide-border/70">
            {rows.map((row) => {
              const { item } = row;
              return <tr key={`${item.event_id}-${item.action}-${item.strategy_version}`} className="align-top hover:bg-muted/20">
                <td className="max-w-48 px-3 py-3"><div className="break-words font-semibold">{item.stock_name || item.stock_code}</div><div className="mt-1 text-[11px] text-muted-foreground">{item.stock_code}</div><div className="mt-1 break-all text-[10px] text-muted-foreground" title={item.strategy_version}>{versionLabel(item.strategy_version)}</div></td>
                <td className="w-48 px-3 py-3"><div className="font-medium">{signalLabel(item)}</div><div className="mt-1 text-[11px] text-muted-foreground">{item.delivered_at ? `已送达 ${signalClock(item.delivered_at)}` : "站内跟踪，非送达预警"}</div>
                  <SignalDetails item={item} />
                </td>
                <td className="px-3 py-3 tabular-nums"><div className="font-medium">{signalClock(item.signal_time)}</div></td>
                <td className="px-3 py-3 tabular-nums">{item.signal_price.toFixed(3)}</td>
                <td className="px-3 py-3 tabular-nums"><div className={`font-semibold ${tone(row.change)}`}>{pct(row.change)}</div><div className="mt-1 text-[11px] text-muted-foreground">{item.same_day.status === "READY" ? "收盘" : "末次可见"}</div></td>
                <td className={`px-3 py-3 tabular-nums ${tone(row.high)}`}>{pct(row.high)}</td>
                <td className={`px-3 py-3 tabular-nums ${tone(row.low)}`}>{pct(row.low)}</td>
                <td className="px-3 py-3"><Observation row={row} /></td>
              </tr>;
            })}
          </tbody>
        </table>
        <div className="divide-y divide-border/70 md:hidden">
          {rows.map((row) => {
            const { item } = row;
            return <article key={`${item.event_id}-${item.action}-${item.strategy_version}`} className="px-3 py-3 text-xs">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0"><div className="break-words font-semibold">{item.stock_name || item.stock_code}</div><div className="mt-1 text-[10px] text-muted-foreground">{item.stock_code} · {versionLabel(item.strategy_version)}</div></div>
                <div className="shrink-0 text-right"><div className={`font-semibold tabular-nums ${tone(row.change)}`}>{pct(row.change)}</div><div className="mt-1 text-[10px] text-muted-foreground">{item.same_day.status === "READY" ? "收盘涨跌" : "后续涨跌"}</div></div>
              </div>
              <div className="mt-2 flex flex-wrap gap-x-2 gap-y-1"><span>{signalLabel(item)}</span><span className="text-muted-foreground">{signalClock(item.signal_time)} / {item.signal_price.toFixed(3)}</span></div>
              <div className="mt-1 text-[10px] text-muted-foreground">{item.delivered_at ? `已送达 ${signalClock(item.delivered_at)}` : "站内跟踪，非送达预警"}</div>
              <div className="my-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground"><span>最高 <strong className={tone(row.high)}>{pct(row.high)}</strong></span><span>最低 <strong className={tone(row.low)}>{pct(row.low)}</strong></span></div>
              <Observation row={row} />
              <SignalDetails item={item} />
            </article>;
          })}
        </div>
        {!rows.length && <div className="flex min-h-28 items-center justify-center px-4 text-center text-xs text-muted-foreground">
          {data.count ? "没有匹配的股票或策略版本" : scope === "alerts" ? "今日暂无已送达的正式预警，候选与观察记录单独统计" : "今日当前范围暂无信号记录"}
        </div>}
      </div>
      <div className="mt-2 flex flex-wrap justify-between gap-1 text-[10px] text-muted-foreground"><span>同股同版本同动作合并 · 首次进入所选阶段计价 · 最高 / 最低均相对信号价</span><span>统计截至 {signalClock(data.as_of)} · {versions.length}个策略版本</span></div>
    </>}
  </section>;
}
