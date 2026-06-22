// 入场择时 · 全部信号历史（实验·只读）
// 某日全部 🟢可低吸 / 🔴别追 触发 + 每条事后走势，供复盘与自查真实命中率。
// 注意：事后涨跌是相对触发价的"原始"口径（未做市场相对），仅作粗略自查，非严格回测。

"use client";

import { useState } from "react";
import Link from "next/link";
import {
  useEntryTimingHistory,
  type EntryTimingHistoryItem,
} from "@/app/hooks/useEntryTiming";

function pct(v: number | null | undefined, digits = 2): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

// 触发后是否"对"：🟢可低吸→低吸后涨(+30min>0)为对；🔴别追→没追(+30min<=0)为对。
// 粗口径(未市场相对)，仅自查参考。
function judge(it: EntryTimingHistoryItem): "hit" | "miss" | "na" {
  if (it.ret_30m == null) return "na";
  if (it.light === "green") return it.ret_30m > 0 ? "hit" : "miss";
  return it.ret_30m <= 0 ? "hit" : "miss";
}

function retClass(v: number | null | undefined): string {
  if (v == null) return "text-muted-foreground";
  return v >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
}

export default function EntryTimingHistoryPage() {
  const [date, setDate] = useState<string>(""); // 空=今日
  const { data, isLoading } = useEntryTimingHistory(date || undefined);
  const items = data?.items ?? [];

  const judged = items.map((it) => ({ it, j: judge(it) }));
  const hit = judged.filter((x) => x.j === "hit").length;
  const evaluable = judged.filter((x) => x.j !== "na").length;
  const hitRate = evaluable > 0 ? Math.round((hit / evaluable) * 100) : null;

  return (
    <div className="max-w-5xl mx-auto p-4 sm:p-6">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
        <h1 className="text-lg font-bold flex items-center gap-2">
          <span>🎯</span> 入场择时 · 全部信号历史
          <span className="text-[10px] px-1.5 py-px rounded bg-amber-500/15 text-amber-600 dark:text-amber-400 font-bold">
            实验·只读
          </span>
        </h1>
        <Link href="/" className="text-xs text-sky-600 dark:text-sky-400 hover:underline">
          ← 返回驾驶舱
        </Link>
      </div>

      <div className="flex items-center gap-3 flex-wrap mb-3 text-sm">
        <label className="flex items-center gap-1.5 text-muted-foreground">
          日期
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="border border-border rounded px-2 py-1 bg-background text-foreground text-xs"
          />
          {date && (
            <button onClick={() => setDate("")} className="text-xs text-sky-600 hover:underline">
              今日
            </button>
          )}
        </label>
        {data && (
          <span className="text-muted-foreground text-xs">
            {data.trade_date} · 共 <b>{data.count}</b> 条（{data.green_count}🟢 / {data.red_count}🔴）
            {hitRate != null && (
              <>
                {" "}
                · 粗口径命中 <b>{hitRate}%</b>（{hit}/{evaluable}，+30min，未市场相对）
              </>
            )}
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="text-center text-muted-foreground py-10">加载中...</div>
      ) : items.length === 0 ? (
        <div className="text-center text-muted-foreground py-10 text-sm leading-relaxed">
          该日暂无落库的入场择时信号
          <br />
          <span className="text-xs text-muted-foreground/60">
            （后端每 30s 在交易时段录制 🟢/🔴；非交易日或刚上线的日期可能为空）
          </span>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-xs">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr className="[&>th]:px-2 [&>th]:py-2 [&>th]:text-left [&>th]:font-medium whitespace-nowrap">
                <th>时间</th>
                <th>股票</th>
                <th>灯</th>
                <th className="text-right">触发价</th>
                <th className="text-right">今日涨</th>
                <th className="text-right">+30min</th>
                <th className="text-right">至今/收盘</th>
                <th className="text-right">最高/最低</th>
                <th>判定</th>
                <th>理由</th>
              </tr>
            </thead>
            <tbody className="[&>tr]:border-t [&>tr]:border-border">
              {judged.map(({ it, j }, i) => (
                <tr key={`${it.stock_code}-${it.time}-${i}`} className="[&>td]:px-2 [&>td]:py-1.5 whitespace-nowrap">
                  <td className="tabular-nums text-muted-foreground">{it.time}</td>
                  <td className="font-medium">{it.stock_name}</td>
                  <td>
                    {it.light === "green" ? (
                      <span className="text-emerald-600 dark:text-emerald-400">🟢可低吸</span>
                    ) : (
                      <span className="text-rose-600 dark:text-rose-400">🔴别追</span>
                    )}
                  </td>
                  <td className="text-right tabular-nums">{it.trigger_price != null ? it.trigger_price.toFixed(3) : "—"}</td>
                  <td className="text-right tabular-nums text-orange-600 dark:text-orange-400">
                    {it.gain_today != null ? `+${it.gain_today.toFixed(1)}%` : "—"}
                  </td>
                  <td className={`text-right tabular-nums ${retClass(it.ret_30m)}`}>{pct(it.ret_30m)}</td>
                  <td className={`text-right tabular-nums ${retClass(it.ret_last)}`}>{pct(it.ret_last)}</td>
                  <td className="text-right tabular-nums text-muted-foreground">
                    <span className="text-emerald-600 dark:text-emerald-400">{pct(it.max_up, 1)}</span>
                    {" / "}
                    <span className="text-rose-600 dark:text-rose-400">{pct(it.max_dn, 1)}</span>
                  </td>
                  <td>
                    {j === "hit" ? (
                      <span className="text-emerald-600 dark:text-emerald-400 font-bold">✓</span>
                    ) : j === "miss" ? (
                      <span className="text-rose-600 dark:text-rose-400 font-bold">✗</span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="text-muted-foreground max-w-[260px] truncate" title={it.reason}>
                    {it.reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[11px] text-muted-foreground mt-3 leading-relaxed">
        实验功能·仅展示不下单。事后涨跌为相对触发价的<b>原始</b>口径（未做市场相对），<b>仅作粗略自查</b>，
        不等于严格回测命中率。判定：🟢低吸后 +30min 上涨记✓，🔴别追后 +30min 未涨记✓。
      </p>
    </div>
  );
}
