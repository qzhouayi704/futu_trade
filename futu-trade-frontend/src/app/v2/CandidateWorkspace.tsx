"use client";

import { useDeferredValue, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, History, Loader2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { v2Api, type V2Candidate, type V2CandidateHistoryItem } from "@/lib/api/v2";
import {
  CandidateTable,
  candidateMemoryStateText,
  candidateReasonText,
  candidateStatusText,
} from "./CandidateTable";
import { clock, money } from "./format";

type CandidateView = "current" | "entered" | "all";

const views: Array<{ id: CandidateView; label: string }> = [
  { id: "current", label: "当前候选" },
  { id: "entered", label: "今日记录" },
  { id: "all", label: "全部评估" },
];

const stageLabel: Record<string, string> = {
  EVALUATED: "仅评估",
  INVALIDATED: "曾经失效",
  SETUP: "曾进入准备",
  WATCHING: "曾进入观察",
  CONFIRMED: "曾确认买点",
};

const eventLabel: Record<string, string> = {
  CANDIDATE_ENTERED: "进入候选",
  CANDIDATE_UPDATED: "候选状态更新",
  CANDIDATE_INVALIDATED: "候选失效",
  CANDIDATE_REJECTED: "本次评估未入选",
  BUY_CONFIRMED: "买点确认",
  BUY_INVALIDATED: "买点失效",
};

const statusOptions = [
  ["", "全部状态"],
  ["CONFIRMED", "信号已确认"],
  ["WATCHING", "观察确认中"],
  ["SETUP", "候选准备中"],
  ["INVALIDATED", "信号已失效"],
  ["IDLE", "当前未入选"],
] as const;

function Timeline({ stockCode, tradeDate }: { stockCode: string; tradeDate: string }) {
  const timeline = useQuery({
    queryKey: ["v2", "candidate-timeline", stockCode, tradeDate],
    queryFn: () => v2Api.candidateTimeline(stockCode, tradeDate),
  });
  if (timeline.isLoading) {
    return <div className="flex h-20 items-center justify-center text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /></div>;
  }
  return <div className="max-h-64 overflow-y-auto border-l-2 border-sky-500/50 bg-muted/20 px-4 py-2">
    {(timeline.data?.items || []).map((event) => (
      <div key={event.event_id} className="grid min-h-9 grid-cols-[54px_110px_1fr] items-center gap-3 border-b border-border/50 text-[11px] last:border-0 md:grid-cols-[54px_110px_150px_1fr_120px]">
        <span className="font-mono text-muted-foreground">{clock(event.exchange_time)}</span>
        <span className="font-medium">{candidateStatusText(event.new_state || "IDLE")}</span>
        <span className="hidden text-muted-foreground md:block">{event.old_state ? `${candidateStatusText(event.old_state)} → ` : ""}{candidateStatusText(event.new_state || "IDLE")}</span>
        <span className="truncate text-muted-foreground" title={candidateReasonText(event.reason_code)}>{candidateReasonText(event.reason_code)}</span>
        <span className="hidden tabular-nums text-muted-foreground md:block">评分 {event.score?.toFixed(1) ?? "--"}</span>
      </div>
    ))}
    {!timeline.data?.items.length && <div className="py-6 text-center text-xs text-muted-foreground">当天没有轨迹记录</div>}
  </div>;
}

function HistoryRow({ item, tradeDate }: { item: V2CandidateHistoryItem; tradeDate: string }) {
  const [open, setOpen] = useState(false);
  const currentPrice = item.quote?.last_price;
  const memory = item.capital_memory;
  return <>
    <tr className="h-14 hover:bg-muted/25">
      <td className="w-10 px-2 py-2">
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setOpen((value) => !value)} aria-label={open ? "收起股票轨迹" : "展开股票轨迹"}>
          {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </Button>
      </td>
      <td className="px-3 py-2"><div className="font-semibold">{item.stock_name || item.stock_code}</div><div className="text-muted-foreground">{item.stock_code}</div></td>
      <td className="px-3 py-2"><div className="font-medium">{candidateStatusText(item.latest_status)}</div><div className="text-[11px] text-muted-foreground">最高：{stageLabel[item.max_stage] || item.max_stage}</div></td>
      <td className="px-3 py-2 tabular-nums"><div className="text-base font-semibold">{item.latest_score?.toFixed(1) ?? "--"}</div><div className="text-[11px] text-muted-foreground">{item.event_count} 条 · {item.strategy_version_count} 版</div></td>
      <td className="px-3 py-2 tabular-nums"><div>{currentPrice?.toFixed(3) ?? "--"}</div><div className="text-[11px] text-muted-foreground">{memory ? candidateMemoryStateText(memory.state || "NEUTRAL") : "资金未知"} · {money(memory?.day_main_net)}</div></td>
      <td className="max-w-64 px-3 py-2"><div className="truncate" title={candidateReasonText(item.latest_reason_code)}>{candidateReasonText(item.latest_reason_code)}</div><div className="text-[11px] text-muted-foreground">{eventLabel[item.latest_event_type] || "候选判断更新"}</div></td>
      <td className="px-3 py-2 text-muted-foreground"><div>{clock(item.first_seen_at)} 首次</div><div>{clock(item.last_seen_at)} 最新</div></td>
    </tr>
    {open && <tr><td colSpan={7} className="p-0"><Timeline stockCode={item.stock_code} tradeDate={tradeDate} /></td></tr>}
  </>;
}

export function CandidateWorkspace({ currentItems }: { currentItems: V2Candidate[] }) {
  const [view, setView] = useState<CandidateView>("current");
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search.trim());
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [view, deferredSearch, status]);

  const history = useQuery({
    queryKey: ["v2", "candidate-history", view, page, deferredSearch, status],
    queryFn: () => v2Api.candidateHistory({
      scope: view === "all" ? "all" : "entered",
      page,
      search: deferredSearch || undefined,
      status: status || undefined,
    }),
    enabled: view !== "current",
    refetchInterval: 30_000,
  });
  const totalPages = Math.max(1, Math.ceil((history.data?.total || 0) / (history.data?.page_size || 50)));

  return <div>
    <div className="mb-3 flex flex-col gap-3 border-b border-border pb-3 lg:flex-row lg:items-center lg:justify-between">
      <div className="inline-flex w-fit border border-border bg-muted/30 p-0.5">
        {views.map((item) => <button key={item.id} onClick={() => setView(item.id)} className={`h-8 px-3 text-xs font-medium ${view === item.id ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>{item.label}</button>)}
      </div>
      {view !== "current" && <div className="flex flex-col gap-2 sm:flex-row">
        <div className="relative w-full sm:w-64"><Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" /><Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索股票代码或名称" className="h-9 pl-8 text-xs" /></div>
        <select value={status} onChange={(event) => setStatus(event.target.value)} className="h-9 border border-input bg-background px-3 text-xs text-foreground" aria-label="筛选候选状态">
          {statusOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </div>}
    </div>

    {view === "current" ? <CandidateTable items={currentItems} /> : <>
      <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground">
        <span>{history.data?.trade_date || "今日"} · 共 {history.data?.total ?? 0} 只股票</span>
        <span>{view === "entered" ? "仅显示真正进入过候选流程的股票" : "包含所有被系统评估的股票"}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[980px] text-left text-xs">
          <thead className="border-b border-border bg-muted/35 text-muted-foreground"><tr>
            <th className="w-10 px-2 py-2"><History className="h-4 w-4" /></th><th className="px-3 py-2 font-medium">标的</th><th className="px-3 py-2 font-medium">最新 / 最高状态</th><th className="px-3 py-2 font-medium">最新评分 / 记录</th><th className="px-3 py-2 font-medium">现价 / 全天资金</th><th className="px-3 py-2 font-medium">最新判断</th><th className="px-3 py-2 font-medium">时间</th>
          </tr></thead>
          <tbody className="divide-y divide-border/70">{(history.data?.items || []).map((item) => <HistoryRow key={item.stock_code} item={item} tradeDate={history.data?.trade_date || ""} />)}</tbody>
        </table>
        {history.isLoading && <div className="flex h-36 items-center justify-center text-muted-foreground"><Loader2 className="h-5 w-5 animate-spin" /></div>}
        {!history.isLoading && !history.data?.items.length && <div className="flex h-36 items-center justify-center text-sm text-muted-foreground">没有符合条件的当天记录</div>}
      </div>
      <div className="mt-3 flex items-center justify-end gap-2 text-xs text-muted-foreground">
        <span>第 {page} / {totalPages} 页</span>
        <Button variant="outline" size="icon" className="h-8 w-8" disabled={page <= 1} onClick={() => setPage((value) => value - 1)} aria-label="上一页"><ChevronLeft className="h-4 w-4" /></Button>
        <Button variant="outline" size="icon" className="h-8 w-8" disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)} aria-label="下一页"><ChevronRight className="h-4 w-4" /></Button>
      </div>
    </>}
  </div>;
}
