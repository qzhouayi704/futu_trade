"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FlaskConical, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { v2Api } from "@/lib/api/v2";
import type { PaperLedgerView } from "@/types/v2/paper-ledger";
import { paperLabel, paperMoney, paperTime } from "./labels";

const cell = "px-3 py-3 text-left align-top";
const sections = [{ id: "orders", label: "模拟计划" }, { id: "fills", label: "模拟成交" }, { id: "signals", label: "信号处理" }] as const;
type Section = (typeof sections)[number]["id"];

function Reason({ code }: { code: string | null | undefined }) {
  return <span title={code || undefined}>{paperLabel(code)}</span>;
}

export function PaperLedgerContent({ data, section = "orders" }: { data: PaperLedgerView; section?: Section }) {
  const ledger = data.ledger;
  if (!ledger) return <div className="border-y border-border py-12 text-center text-sm text-muted-foreground" role="status">
    {data.status === "DISABLED" ? "模拟实验未启用，暂无账本" : data.status === "ERROR" ? "模拟启动异常，暂无可读账本" : "模拟账本尚未初始化"}
    {data.runtime?.error && <div className="mt-2"><Reason code={data.runtime.error} /></div>}
  </div>;
  const staleCodes = [...new Set([...ledger.stale_position_codes, ...(data.runtime?.stale_position_codes || [])])];
  return <div className="space-y-5">
    <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted-foreground">
      <span className="break-all">账户：{ledger.account_id}</span><span className="break-all">实验：{ledger.experiment_id}</span>
      <span>账本截至：{paperTime(ledger.as_of)}</span><span>报告读取：{paperTime(ledger.reported_at)}</span>
      <span>香港时间 · 港元</span>
    </div>
    {(data.status === "ERROR" || ledger.run_error_code) && <div role="alert" className="border-l-2 border-rose-500 bg-rose-500/5 p-3 text-sm">模拟实验异常：<Reason code={data.runtime?.error || ledger.run_error_code} /></div>}
    {data.status === "STOPPED" && <div className="border-l-2 border-amber-500 p-3 text-sm">模拟已停止{ledger.run_record_status !== "CLOSED" ? "，账本运行记录未正常关闭，需复核" : ""}</div>}
    {staleCodes.length > 0 && <div role="alert" className="border-l-2 border-amber-500 bg-amber-500/5 p-3 text-sm break-words">持仓估值行情已过期：{staleCodes.join("、")}。估算权益不是可成交金额或最终收益。</div>}
    <dl className="grid grid-cols-2 divide-x divide-border border-y border-border md:grid-cols-5">
      {[["账本现金", ledger.cash], ["预留资金", ledger.reserved_cash], ["报告时估算权益", ledger.marked_equity], ["已平仓净盈亏", ledger.closed_order_count ? ledger.closed_order_net_pnl : null], ["累计模拟费用", ledger.fees]].map(([label, value]) =>
        <div key={label} className="min-w-0 px-3 py-4"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-2 break-all text-lg font-semibold tabular-nums">{paperMoney(value)}</dd></div>)}
    </dl>
    <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted-foreground">
      <span>{ledger.order_count} 个计划 · {ledger.fill_count} 笔成交</span>
      {data.runtime && <span>已处理 {data.runtime.processed} · 队列 {data.runtime.queue_size} · 输入缺口 {data.runtime.dropped}</span>}
      <span className="break-all">{ledger.strategy_id} · {ledger.strategy_version}</span>
      <span className="break-words">实验股票：{ledger.stock_codes.join("、")}</span>
    </div>
    <div className="overflow-x-auto border-y border-border">
      {section === "orders" && <table className="w-full min-w-[1020px] text-sm"><thead className="bg-muted/30 text-xs text-muted-foreground"><tr>{["股票 / 批准时间", "状态 / 原因", "买入范围 / 失效价", "计划 / 待买数量", "已买 / 已卖 / 持有", "入场截止 / 退出期限", "已平仓净盈亏"].map(label => <th key={label} className={cell}>{label}</th>)}</tr></thead>
        <tbody className="divide-y divide-border">{ledger.orders.map(order => <tr key={order.plan_id}>
          <td className={cell}><div className="font-medium">{order.stock_code}</div><div className="mt-1 text-xs text-muted-foreground">{paperTime(order.approved_at)}</div></td>
          <td className={`${cell} max-w-52 break-words`}><Reason code={order.status} /><div className="mt-1 text-xs text-muted-foreground"><Reason code={order.exit_reason || order.entry_end_reason} /></div></td>
          <td className={`${cell} tabular-nums`}>{paperMoney(order.entry_min, 3)} ~ {paperMoney(order.entry_limit, 3)}<div className="mt-1 text-xs text-muted-foreground">失效 {paperMoney(order.stop_price, 3)}</div></td>
          <td className={`${cell} tabular-nums`}>{order.quantity} / {order.entry_remaining}</td>
          <td className={`${cell} tabular-nums`}>{order.bought} / {order.sold} / {order.held}</td>
          <td className={`${cell} text-xs`}>{paperTime(order.valid_until)}<div className="mt-1 text-muted-foreground">{paperTime(order.exit_at)}</div></td>
          <td className={`${cell} tabular-nums`}>{paperMoney(order.closed_net_pnl)}</td>
        </tr>)}{ledger.orders.length === 0 && <tr><td colSpan={7} className="py-12 text-center text-muted-foreground">暂无模拟计划</td></tr>}</tbody></table>}
      {section === "fills" && <table className="w-full min-w-[660px] text-sm"><thead className="bg-muted/30 text-xs text-muted-foreground"><tr>{["成交时间", "股票", "方向", "数量", "模拟成交价", "模拟费用"].map(label => <th className={cell} key={label}>{label}</th>)}</tr></thead>
        <tbody className="divide-y divide-border">{ledger.recent_fills.map(fill => <tr key={fill.fill_id}><td className={cell}>{paperTime(fill.exchange_time)}</td><td className={cell}>{fill.stock_code}</td><td className={cell}>{fill.side === "BUY" ? "模拟买入" : fill.side === "SELL" ? "模拟卖出" : "方向待核查"}</td><td className={cell}>{fill.quantity}</td><td className={cell}>{paperMoney(fill.price, 3)}</td><td className={cell}>{paperMoney(fill.fee)}</td></tr>)}{ledger.recent_fills.length === 0 && <tr><td colSpan={6} className="py-12 text-center text-muted-foreground">暂无模拟成交</td></tr>}</tbody></table>}
      {section === "signals" && <table className="w-full min-w-[600px] text-sm"><thead className="bg-muted/30 text-xs text-muted-foreground"><tr>{["处理时间", "股票", "处理结果"].map(label => <th className={cell} key={label}>{label}</th>)}</tr></thead>
        <tbody className="divide-y divide-border">{ledger.recent_signals.map(item => <tr key={item.event_id}><td className={cell}>{paperTime(item.processed_at)}</td><td className={cell}>{item.stock_code}</td><td className={cell}><Reason code={item.reason} /></td></tr>)}{ledger.recent_signals.length === 0 && <tr><td colSpan={3} className="py-12 text-center text-muted-foreground">暂无信号处理记录</td></tr>}</tbody></table>}
    </div>
    <p className="text-xs text-muted-foreground">{section === "orders" ? `显示 ${ledger.orders.length} / ${ledger.order_count} 个计划，活动计划优先` : section === "fills" ? `最近 ${ledger.recent_fills.length} 笔模拟成交` : `最近 ${ledger.recent_signals.length} 条信号处理记录`}</p>
  </div>;
}

export function PaperLedger() {
  const [section, setSection] = useState<Section>("orders");
  const query = useQuery({ queryKey: ["v2", "paper-ledger"], queryFn: ({ signal }) => v2Api.paperLedger(signal),
    refetchInterval: 15_000, refetchIntervalInBackground: false, retry: false });
  return <section className="space-y-5">
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="flex items-center gap-2 text-base font-semibold"><FlaskConical className="h-5 w-5" />模拟账本</h2>
        <p className="mt-1 text-xs text-muted-foreground">独立纸面账户 · 非实盘 · 采样盘口近似成交</p></div>
      <div className="flex items-center gap-3"><span className="text-sm">{query.isError ? "读取失败" : query.data ? paperLabel(query.data.status) : "正在读取"}</span>
        <Tooltip><TooltipTrigger asChild><Button variant="outline" size="icon" disabled={query.isFetching} onClick={() => query.refetch()} aria-label="刷新模拟账本"><RefreshCw className={`h-4 w-4 ${query.isFetching ? "animate-spin" : ""}`} /></Button></TooltipTrigger><TooltipContent>刷新模拟账本</TooltipContent></Tooltip></div>
    </header>
    <nav className="flex overflow-x-auto border-b border-border" aria-label="模拟账本视图">{sections.map(item => <button key={item.id} onClick={() => setSection(item.id)} aria-current={item.id === section ? "page" : undefined} className={`h-10 shrink-0 border-b-2 px-4 text-sm ${item.id === section ? "border-emerald-500" : "border-transparent text-muted-foreground"}`}>{item.label}</button>)}</nav>
    {query.isError && <div role="alert" className="border-l-2 border-rose-500 p-3 text-sm">模拟账本读取失败{query.data ? "，下方为上次读取结果" : "，暂不能判断账户状态"}。请重试。</div>}
    {query.data ? <PaperLedgerContent data={query.data} section={section} /> : query.isPending ? <div role="status" className="py-12 text-center text-sm text-muted-foreground">正在读取模拟账本...</div> : null}
  </section>;
}
