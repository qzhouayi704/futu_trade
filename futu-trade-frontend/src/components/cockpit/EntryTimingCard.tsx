// 入场择时（实验·只读）— 强势股低吸择时绿灯
// 依据 2026-06 生产逐笔回测：强势股买"刚回调"前向收益/胜率最高(+0.30%/56%)，
// 追"刚冲高"最差(命中46%)。纯展示，不参与下单/评分。

"use client";

import { useEntryTiming, type EntryTimingItem } from "@/app/hooks/useEntryTiming";

function LightTag({ light }: { light: EntryTimingItem["light"] }) {
  if (light === "green")
    return <span className="text-[9px] px-1.5 py-px rounded-full bg-emerald-500 text-white font-bold shrink-0">🟢 可低吸</span>;
  if (light === "red")
    return <span className="text-[9px] px-1.5 py-px rounded-full bg-rose-500 text-white font-bold shrink-0">🔴 别追</span>;
  return <span className="text-[9px] px-1.5 py-px rounded-full bg-muted text-muted-foreground font-bold shrink-0">⚪ 观望</span>;
}

export function EntryTimingCard({ onSelectStock }: { onSelectStock?: (code: string) => void }) {
  const { data, isLoading } = useEntryTiming();
  const items = data?.items ?? [];
  const greens = items.filter((i) => i.light === "green");
  const reds = items.filter((i) => i.light === "red");
  // 优先展示 🟢，其次 🔴，最后少量 ⚪；总量克制
  const shown = [...greens, ...reds].slice(0, 10);

  return (
    <div className="rounded-xl border border-sky-200/50 dark:border-sky-500/20 bg-card shadow-sm">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <h3 className="text-sm font-bold text-foreground flex items-center gap-1.5">
          <span className="text-base">🎯</span>
          入场择时
          <span className="text-[10px] font-normal text-sky-600 dark:text-sky-400">当日强势·低吸择时</span>
          <span className="text-[9px] px-1 py-px rounded bg-amber-500/15 text-amber-600 dark:text-amber-400 font-bold">实验·只读</span>
        </h3>
        <span className="text-[10px] text-muted-foreground">
          {data ? `强势股${data.pool_size}只 · ${greens.length}🟢/${reds.length}🔴` : ""}
        </span>
      </div>

      <div className="p-3">
        {isLoading ? (
          <div className="text-center text-sm text-muted-foreground py-4">扫描中...</div>
        ) : !data || data.pool_size === 0 ? (
          <div className="text-center text-[12px] text-muted-foreground py-5 leading-relaxed">
            暂无当日强势股
            <br />
            <span className="text-[10px] text-muted-foreground/60">(休市，或今日暂无明显领涨的活跃股)</span>
          </div>
        ) : !data.market_open ? (
          <div className="text-center text-[12px] text-muted-foreground py-5 leading-relaxed">
            休市中 · 当日强势股 {data.pool_size} 只已就绪
            <br />
            <span className="text-[10px] text-muted-foreground/60">(开盘后实时点亮 🟢可低吸 / 🔴别追)</span>
          </div>
        ) : shown.length === 0 ? (
          <div className="text-center text-[12px] text-muted-foreground py-5 leading-relaxed">
            当前强势股均为 ⚪观望
            <br />
            <span className="text-[10px] text-muted-foreground/60">(无明确"刚回调低吸"或"刚冲高别追"信号)</span>
          </div>
        ) : (
          <div className="space-y-1.5">
            {shown.map((it) => {
              const isGreen = it.light === "green";
              return (
                <div
                  key={it.stock_code}
                  onClick={() => onSelectStock?.(it.stock_code)}
                  className={`px-2.5 py-2 rounded-lg border transition-colors cursor-pointer ${
                    isGreen
                      ? "bg-emerald-500/10 border-emerald-500/30 hover:bg-emerald-500/15"
                      : "bg-rose-500/5 border-rose-500/20 hover:bg-rose-500/10"
                  }`}
                >
                  {/* 第一行：名称 + 近3日涨幅 + 灯 + 现价 */}
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="text-[13px] font-semibold text-foreground truncate">{it.stock_name}</span>
                      <span className="text-[9px] px-1.5 py-px rounded-full bg-orange-500/15 text-orange-600 dark:text-orange-400 font-bold shrink-0">
                        今日+{it.gain_today.toFixed(0)}%
                      </span>
                      <LightTag light={it.light} />
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {it.mom5 != null && (
                        <span className={`text-[10px] tabular-nums ${it.mom5 < 0 ? "text-profit" : "text-loss"}`}>
                          近5分{it.mom5 >= 0 ? "+" : ""}
                          {it.mom5.toFixed(1)}%
                        </span>
                      )}
                      {it.last_price != null && (
                        <span className="text-[13px] font-bold tabular-nums text-foreground">{it.last_price.toFixed(3)}</span>
                      )}
                    </div>
                  </div>
                  {/* 第二行：理由 + 日内价位 */}
                  <div className={`text-[11px] mt-1 flex items-center gap-1 ${isGreen ? "text-emerald-700 dark:text-emerald-400/90" : "text-rose-700 dark:text-rose-400/90"}`}>
                    <span className="truncate">{it.reason}</span>
                    {it.pos_range != null && (
                      <span className="text-[9px] text-muted-foreground shrink-0">· 日内位{Math.round(it.pos_range * 100)}%</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
        {/* 脚注：诚实边界 */}
        <div className="text-[10px] text-muted-foreground mt-2 pt-2 border-t border-border leading-relaxed">
          实验功能·仅展示不下单。基于当日强势股(今日领涨) + 逐笔回测："买刚回调、别追刚冲高"在强势股上前向收益/胜率最高。
          边际薄(~0.1%/命中54%)、样本仅5天平静行情——当<b>择时过滤器</b>用(决定何时点买)，不是选股器，请自行判断。
        </div>
      </div>
    </div>
  );
}
