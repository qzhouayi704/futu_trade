"use client";

import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { v2Api, type V2OvernightObservation } from "@/lib/api/v2";
import { candidateReasonText } from "./CandidateTable";
import { clock, money } from "./format";

const statusText = {
  WATCHING: "待当日确认", SUSPENDED: "暂缓观察", INVALIDATED: "线索失效", EXPIRED: "观察到期",
};
const statusTone = {
  WATCHING: "text-sky-700 dark:text-sky-400", SUSPENDED: "text-amber-700 dark:text-amber-400",
  INVALIDATED: "text-rose-600 dark:text-rose-400", EXPIRED: "text-muted-foreground",
};

export function OvernightRows({ items }: { items: V2OvernightObservation[] }) {
  return <div className="overflow-x-auto border-y border-border">
    <table className="w-full min-w-[980px] text-left text-xs">
      <thead className="border-b border-border bg-muted/35 text-muted-foreground"><tr>
        {["股票", "观察状态", "来源 / 到期", "来源价格 / 评分", "来源资金证据", "最近判断"].map((label) =>
          <th key={label} className="px-3 py-2 font-medium">{label}</th>)}
      </tr></thead>
      <tbody className="divide-y divide-border/70">{items.map((item) => <tr key={item.setup_id} className="align-top">
        <td className="px-3 py-3"><div className="font-semibold">{item.stock_name || item.stock_code}</div><div className="mt-1 text-muted-foreground">{item.stock_code}</div></td>
        <td className="px-3 py-3"><div className={`font-medium ${statusTone[item.status]}`}>{statusText[item.status]}</div><div className="mt-1 text-muted-foreground">{item.age_sessions <= 3 ? `第 ${item.age_sessions} / 3 个交易日` : "已超期"}</div><div className="mt-1 text-[11px] text-muted-foreground">{item.selected ? "列入订阅优先名单" : "未列入当前优先名单"}</div></td>
        <td className="px-3 py-3 tabular-nums"><div>{item.source_date} {clock(item.source_time)}</div><div className="mt-1 text-muted-foreground">到期 {item.expires_date}</div></td>
        <td className="px-3 py-3 tabular-nums"><div>{item.reference_price.toFixed(3)}</div><div className="mt-1 text-muted-foreground">评分 {item.score.toFixed(1)}</div></td>
        <td className="px-3 py-3 tabular-nums"><div>净额 {money(item.day_main_net)}</div><div className="mt-1 text-muted-foreground">独立流入 {item.independent_buy_events} 次</div></td>
        <td className="max-w-64 px-3 py-3"><div>{candidateReasonText(item.reason_code)}</div><div className="mt-1 text-muted-foreground">{item.last_event_time.slice(0, 10)} {clock(item.last_event_time)}</div></td>
      </tr>)}</tbody>
    </table>
    {!items.length && <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">没有可展示的跨日线索</div>}
  </div>;
}

export function OvernightCandidates() {
  const query = useQuery({ queryKey: ["v2", "overnight-candidates"], queryFn: v2Api.overnightCandidates, refetchInterval: 30_000 });
  const data = query.data;
  return <section>
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3 text-xs">
      <div className="space-y-1"><div className="font-semibold">跨日重点 · 研究观察，尚未开放买入提醒</div><div className="text-muted-foreground">{data?.trade_date || "今日"} · 优先名单 {data?.selected_count ?? 0} 只 · 记录 {data?.count ?? 0} 只</div></div>
      <Button variant="outline" size="icon" disabled={query.isFetching} onClick={() => query.refetch()} title="刷新跨日观察" aria-label="刷新跨日观察"><RefreshCw className={query.isFetching ? "animate-spin" : ""} /></Button>
    </div>
    {(query.isError || (data && ["UNAVAILABLE", "STALE", "NOT_LOADED"].includes(data.status))) && <div className="mb-3 border-l-2 border-amber-500 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-200">跨日数据或交易日历尚未就绪，当前不使用旧线索生成跨日确认。</div>}
    {data?.status === "MARKET_CLOSED" && <div className="mb-3 text-xs text-muted-foreground">今日休市，未生成当日跨日优先名单。</div>}
    {query.isLoading ? <div className="h-36 animate-pulse bg-muted/30" /> : <OvernightRows items={data?.items || []} />}
  </section>;
}
