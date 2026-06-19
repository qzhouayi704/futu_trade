// 今日可买精选 — 为手动交易做的"一眼可买"清单
// 只挑「持续抢筹·可持有」(被反复大买、且未追高)的 mega_buy,按抢筹次数排好,
// 每只直接给出"现价 / 当日已涨 / 怎么卖"。数据来自共享 RQ 钩子(与信号流去重)+ WS 缓存同步。

"use client";

import { useMemo } from "react";
import { useSniperSignals, useSniperTapeVerdicts } from "@/app/hooks/useSniper";
import { Chip } from "@/components/ui/chip";
import type { SniperSignal } from "@/types/trade";

export function DailyPickCard({ onSelectStock }: { onSelectStock?: (code: string) => void }) {
  // 共享 ["sniperSignals"] 缓存：与 UnifiedSignalFeed 去重为一次请求；WS 推送由 useSocketQuerySync 写缓存
  const { data: signals = [], isLoading: loading, dataUpdatedAt } = useSniperSignals();
  const lastUpdate = dataUpdatedAt ? new Date(dataUpdatedAt) : null;

  // 只取「持续抢筹·可持有」(tier=opportunity) 的 mega_buy;每只股票保留抢筹次数最高的一条
  const picks = useMemo(() => {
    const byStock = new Map<string, SniperSignal>();
    for (const s of signals) {
      if (s.signal_type !== "mega_buy" || s.tier !== "opportunity") continue;
      const cur = byStock.get(s.stock_code);
      const bc = s.buy_count ?? 0;
      const cbc = cur?.buy_count ?? 0;
      if (!cur || bc > cbc || (bc === cbc && s.time > cur.time)) {
        byStock.set(s.stock_code, s);
      }
    }
    return Array.from(byStock.values())
      .sort((a, b) => (b.buy_count ?? 0) - (a.buy_count ?? 0) || b.time.localeCompare(a.time))
      .slice(0, 8);
  }, [signals]);

  // 精选股的实时盘口判定(追高/洗盘)，给每只打标
  const pickCodes = picks.map((p) => p.stock_code).join(",");
  const tapeQuery = useSniperTapeVerdicts(pickCodes);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tapeMap: Record<string, any> = (tapeQuery.data as Record<string, any>) ?? {};

  return (
    <div className="rounded-xl border border-emerald-200/50 dark:border-emerald-500/20 bg-card shadow-sm">
      {/* 标题 */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <h3 className="text-sm font-bold text-foreground flex items-center gap-1.5">
          <span className="text-base">🎯</span>
          今日可买精选
          <span className="text-[10px] font-normal text-emerald-600 dark:text-emerald-400">持续抢筹·可持有</span>
        </h3>
        <span className="text-[10px] text-muted-foreground">
          {lastUpdate ? `${lastUpdate.toLocaleTimeString("zh-CN")} 更新` : ""}
        </span>
      </div>

      <div className="p-3">
        {loading ? (
          <div className="text-center text-sm text-muted-foreground py-4">扫描中...</div>
        ) : picks.length === 0 ? (
          <div className="text-center text-[12px] text-muted-foreground py-5 leading-relaxed">
            今日暂无精选<br />
            <span className="text-[10px] text-muted-foreground/60">(等"被反复大买、且还没涨高"的票出现)</span>
          </div>
        ) : (
          <div className="space-y-1.5">
            {picks.map((s, idx) => {
              const gain = s.intraday_gain ?? 0;
              return (
                <div
                  key={s.stock_code}
                  onClick={() => onSelectStock?.(s.stock_code)}
                  className={`px-2.5 py-2 rounded-lg border transition-colors cursor-pointer ${
                    idx === 0
                      ? "bg-emerald-500/10 border-emerald-500/30"
                      : "bg-emerald-500/5 border-emerald-500/15 hover:bg-emerald-500/10"
                  }`}
                >
                  {/* 第一行：名称 + 抢筹徽章 + 已涨 + 现价 */}
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="text-[9px] font-bold w-4 h-4 flex items-center justify-center rounded-full bg-emerald-500 text-white shrink-0">
                        {idx + 1}
                      </span>
                      <span className="text-[13px] font-semibold text-foreground truncate">
                        {s.stock_name}
                      </span>
                      <span className="text-[9px] px-1.5 py-px rounded-full bg-emerald-500 text-white font-bold shrink-0">
                        持续抢筹×{s.buy_count ?? "?"}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-[10px] text-muted-foreground tabular-nums">
                        已涨{gain >= 0 ? "+" : ""}{gain.toFixed(1)}%
                      </span>
                      <span className="text-[13px] font-bold tabular-nums text-foreground">
                        {s.price.toFixed(3)}
                      </span>
                    </div>
                  </div>
                  {/* 第二行：怎么卖 */}
                  <div className="text-[11px] text-emerald-700 dark:text-emerald-400/90 mt-1 flex items-center gap-1">
                    <span>📍</span>
                    <span className="truncate">{s.posture || "可持有到收盘(分批锁利+宽跟踪)"}</span>
                  </div>

                  {/* 盘口判定标：现已冲高别追 / 追高风险 / 回踩可低吸 */}
                  {(() => {
                    const tape = tapeMap[s.stock_code];
                    if (!tape?.available) return null;
                    const chase = tape.chase;
                    const soV = tape.selloff?.verdict;
                    if (chase !== "high" && chase !== "caution" && soV !== "shakeout") return null;
                    return (
                      <div className="mt-1 flex items-center flex-wrap gap-1">
                        {chase === "high" && (
                          <span className="text-[9px] px-1.5 py-px rounded-full bg-red-500 text-white font-bold">
                            ⚠️ 现已冲高·别追
                          </span>
                        )}
                        {chase === "caution" && (
                          <Chip variant="watch">🟡 追高风险</Chip>
                        )}
                        {soV === "shakeout" && (
                          <Chip variant="buy">🟢 回踩有承接·可低吸</Chip>
                        )}
                      </div>
                    );
                  })()}
                </div>
              );
            })}
          </div>
        )}
        {/* 脚注：诚实提醒 */}
        <div className="text-[10px] text-muted-foreground mt-2 pt-2 border-t border-border leading-relaxed">
          只列"被大资金反复买、且当日还没涨高"的票;急涨/追高的已自动剔除。仅供手动参考,样本有限需自行判断。
        </div>
      </div>
    </div>
  );
}
