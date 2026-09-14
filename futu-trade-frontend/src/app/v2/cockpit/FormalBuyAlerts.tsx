"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { TrendingUp } from "lucide-react";
import { v2Api } from "@/lib/api/v2";
import { pct, tone } from "../format";
import { statusText } from "../signal-lifecycle";
import { marketDateKey, signalClock, todaySignalRow } from "./today-signal-metrics";

export function FormalBuyAlerts() {
  const [tradeDate, setTradeDate] = useState(marketDateKey);
  useEffect(() => {
    const update = () => setTradeDate(marketDateKey());
    const timer = window.setInterval(update, 60_000);
    window.addEventListener("focus", update);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", update); };
  }, []);
  const query = useQuery({
    queryKey: ["v2", "alert-performance", tradeDate, "alerts"],
    queryFn: ({ signal }) => v2Api.alertPerformance(tradeDate, "alerts", signal),
    retry: false,
    staleTime: 45_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });
  const data = query.data?.trade_date === tradeDate && query.data.scope === "alerts" ? query.data : undefined;
  const buys = (data?.items || [])
    .filter((item) => item.action === "BUY" && item.risk_result === "APPROVED" && item.alert_permission === "DELIVERED")
    .map(todaySignalRow)
    .sort((a, b) => Date.parse(b.item.signal_time) - Date.parse(a.item.signal_time));

  return <section aria-labelledby="formal-buy-title">
    <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h2 id="formal-buy-title" className="flex items-center gap-2 text-sm font-semibold"><TrendingUp className="h-4 w-4 text-emerald-500" />今日正式买入提醒</h2>
      <span className="text-xs text-muted-foreground">{tradeDate} · {data ? `${buys.length} 条微信接口已接受` : "读取中"}</span>
      <span className="text-[11px] text-muted-foreground">历史提醒，当前状态及行情可能已变化；参考价非实盘成交价</span>
    </div>
    {query.isError && <div role="alert" className="border-l-2 border-rose-500 px-3 py-2 text-xs text-rose-700">正式提醒记录读取失败，不能据此判断今天没有信号。</div>}
    {!data && !query.isError && <div role="status" className="border-y border-border px-3 py-4 text-xs text-muted-foreground">正在读取正式提醒...</div>}
    {data?.refresh_status === "STALE" && <div role="status" className="mb-2 text-xs text-amber-700">当前为缓存快照，非最新提醒记录。</div>}
    {data && <div className="max-h-64 overflow-auto border-y border-border" role="region" aria-label="今日正式买入提醒明细" tabIndex={0}>
      {buys.length === 0 ? <div className="px-3 py-4 text-xs text-muted-foreground">今日尚无通过风控且微信接口已接受的正式买入提醒。</div>
        : <table className="w-full min-w-[590px] text-left text-xs">
          <thead className="sticky top-0 bg-background text-[11px] text-muted-foreground"><tr>
            <th scope="col" className="px-3 py-2 font-medium">股票</th>
            <th scope="col" className="px-3 py-2 font-medium">信号时间 / 参考价</th>
            <th scope="col" className="px-3 py-2 font-medium">信号后股价</th>
            <th scope="col" className="px-3 py-2 font-medium">当前状态</th>
          </tr></thead>
          <tbody className="divide-y divide-border/70">{buys.map(({ item, change }) => <tr key={item.event_id} className="align-top">
            <td className="px-3 py-2"><strong>{item.stock_name || item.stock_code}</strong><div className="text-[11px] text-muted-foreground">{item.stock_code}</div></td>
            <td className="px-3 py-2 tabular-nums">{signalClock(item.signal_time)} / {item.signal_price.toFixed(3)}</td>
            <td className={`px-3 py-2 tabular-nums ${item.same_day.is_stale ? "text-amber-700" : tone(change)}`}>{item.same_day.is_stale ? "行情已中断" : pct(change)}<div className="text-[11px] text-muted-foreground">{item.same_day.observed_through ? `截至 ${signalClock(item.same_day.observed_through)}` : "等待行情"}</div></td>
            <td className="px-3 py-2">{statusText[item.current_status]}<div className="text-[11px] text-muted-foreground">{item.delivered_at ? `接口接受 ${signalClock(item.delivered_at)}` : "无发送回执"}</div></td>
          </tr>)}</tbody>
        </table>}
    </div>}
  </section>;
}
