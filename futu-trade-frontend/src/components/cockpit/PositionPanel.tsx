// 驾驶舱持仓面板 — 实时盈亏 + Sniper止盈状态 + 日内/波段 影子卖出建议
// [2026-06-18] 新增: 每只持仓一个"日内/波段"开关(localStorage, 默认日内) + 实时"该怎么卖"影子提示。
//   纯展示, 不下任何真单。日内=混合出场口径(+2/+4分批/−5止损); 波段=宽跟踪(回撤≥10%/−8%止损)。
//   注: 波段的"距高点回撤"用本会话峰值近似(刷新会重置); 接后端自动卖时再用真实多日峰值。

"use client";

import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { Card } from "@/components/common";
import { sniperApi } from "@/lib/api/sniper";

interface Position {
  stock_code: string;
  stock_name: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  market_value: number;
  profit_loss: number;
  profit_loss_pct: number;
}

interface TrailingStatus {
  activated: boolean;
  mega_buy_count: number;
  mega_sell: boolean;
  peak_price: number;
  stop_pct: number;
}

interface PositionPanelProps {
  positions: Position[];
  loading: boolean;
  realtimePrices: Record<string, number>;
}

type ExitMode = "intraday" | "swing";

// 影子卖出建议(纯提示, 不下单)
function getAdvice(mode: ExitMode, plPct: number, curPrice: number, peakPrice: number) {
  const dd = peakPrice > 0 ? ((peakPrice - curPrice) / peakPrice) * 100 : 0; // 距高点回撤%
  if (mode === "swing") {
    if (plPct <= -8) return { icon: "🔴", text: "止损:跌破 −8%,建议清仓" };
    if (plPct > 2 && dd >= 10) return { icon: "🟠", text: `距高点回撤 ${dd.toFixed(1)}% ≥10%,趋势转弱,建议了结` };
    return { icon: "🟢", text: `波段持有中(回撤 ${dd.toFixed(1)}%);跌破 −8% 或回撤 ≥10% 再走` };
  }
  // 日内
  if (plPct <= -5) return { icon: "🔴", text: "止损:跌破 −5%,建议清仓" };
  if (plPct >= 4) return { icon: "🟠", text: "已 +4%:二档减仓锁利,余量冲高/收盘了结" };
  if (plPct >= 2) return { icon: "🟠", text: "已 +2%:先减一半锁利" };
  if (plPct >= 0) return { icon: "🟢", text: "持有等冲高;临近收盘没冲高就了结" };
  return { icon: "⚪", text: "持有;跌破 −5% 止损" };
}

const MODE_KEY = "positionExitModes";

export function PositionPanel({ positions, loading, realtimePrices }: PositionPanelProps) {
  const [trailingStatus, setTrailingStatus] = useState<Record<string, TrailingStatus>>({});
  const [modes, setModes] = useState<Record<string, ExitMode>>({});
  const peakRef = useRef<Record<string, number>>({}); // 本会话每股峰值价

  // 读取本地保存的"日内/波段"标记
  useEffect(() => {
    try {
      const saved = localStorage.getItem(MODE_KEY);
      if (saved) setModes(JSON.parse(saved));
    } catch {}
  }, []);

  const toggleMode = useCallback((code: string) => {
    setModes((prev) => {
      const cur: ExitMode = prev[code] === "swing" ? "swing" : "intraday";
      const next = { ...prev, [code]: cur === "swing" ? "intraday" : "swing" } as Record<string, ExitMode>;
      try { localStorage.setItem(MODE_KEY, JSON.stringify(next)); } catch {}
      return next;
    });
  }, []);

  // 加载Sniper止盈状态
  useEffect(() => {
    const load = async () => {
      try {
        const res = await sniperApi.getTrailingStatus();
        if (res?.success && res.data) {
          setTrailingStatus(res.data);
        }
      } catch {}
    };
    load();
    const timer = setInterval(load, 15000); // 15秒刷新
    return () => clearInterval(timer);
  }, []);

  // 合并实时价格
  const livePositions = useMemo(() => {
    return positions.map((p) => {
      const livePrice = realtimePrices[p.stock_code];
      if (!livePrice || livePrice === p.current_price) return p;
      const costTotal = p.avg_price * p.quantity;
      const newMarketValue = livePrice * p.quantity;
      const newPL = newMarketValue - costTotal;
      const newPLPct = costTotal > 0 ? (newPL / costTotal) * 100 : 0;
      return {
        ...p,
        current_price: livePrice,
        market_value: newMarketValue,
        profit_loss: newPL,
        profit_loss_pct: newPLPct,
      };
    });
  }, [positions, realtimePrices]);

  // 总盈亏
  const totalPL = livePositions.reduce((sum, p) => sum + p.profit_loss, 0);
  const totalCost = livePositions.reduce((sum, p) => sum + p.avg_price * p.quantity, 0);
  const totalPLPct = totalCost > 0 ? (totalPL / totalCost) * 100 : 0;

  return (
    <Card className="overflow-hidden">
      <div className="p-4 md:p-5">
        {/* 标题 + 总盈亏 */}
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold text-foreground flex items-center gap-1.5">
            💼 持仓
            <span className="text-xs font-normal text-muted-foreground">
              {livePositions.length}只
            </span>
          </h3>
          {livePositions.length > 0 && (
            <div className={`text-right ${totalPL >= 0 ? "text-red-500" : "text-green-500"}`}>
              <div className="text-sm font-bold tabular-nums">
                {totalPL >= 0 ? "+" : ""}{totalPL.toFixed(0)}
                <span className="text-xs ml-1">HKD</span>
              </div>
              <div className="text-[10px] tabular-nums">
                {totalPLPct >= 0 ? "+" : ""}{totalPLPct.toFixed(2)}%
              </div>
            </div>
          )}
        </div>

        {loading ? (
          <div className="text-center py-6 text-muted-foreground text-sm">
            <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-2" />
            加载中...
          </div>
        ) : livePositions.length === 0 ? (
          <div className="text-center py-6 text-muted-foreground text-sm">
            暂无持仓
          </div>
        ) : (
          <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1
                        [&::-webkit-scrollbar]:w-1 [&::-webkit-scrollbar-thumb]:rounded-full
                        [&::-webkit-scrollbar-thumb]:bg-gray-300 dark:[&::-webkit-scrollbar-thumb]:bg-gray-600">
            {livePositions.map((pos) => {
              const ts = trailingStatus[pos.stock_code];
              const plPct = pos.profit_loss_pct;
              const isProfit = plPct >= 0;

              // 本会话峰值价(波段回撤用)
              const peak = Math.max(peakRef.current[pos.stock_code] ?? pos.current_price, pos.current_price);
              peakRef.current[pos.stock_code] = peak;

              // 日内/波段 + 影子卖出建议
              const mode: ExitMode = modes[pos.stock_code] === "swing" ? "swing" : "intraday";
              const advice = getAdvice(mode, plPct, pos.current_price, peak);

              return (
                <div
                  key={pos.stock_code}
                  className={`px-3 py-2.5 rounded-lg border transition-all hover:shadow-sm ${
                    advice.icon === "🔴"
                      ? "bg-red-50/60 border-red-200/50 dark:bg-red-950/20 dark:border-red-800/30"
                      : mode === "swing"
                        ? "bg-indigo-50/40 border-indigo-200/40 dark:bg-indigo-950/15 dark:border-indigo-800/25"
                        : "bg-card border-border/50"
                  }`}
                >
                  {/* 第一行：名称 + 模式开关 + 盈亏 */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="font-bold text-sm text-foreground truncate">
                        {pos.stock_name}
                      </span>
                      <button
                        onClick={() => toggleMode(pos.stock_code)}
                        title="点击切换 日内/波段(决定卖出建议口径)"
                        className={`text-[9px] px-1.5 py-px rounded-full font-bold shrink-0 transition-colors ${
                          mode === "swing"
                            ? "bg-indigo-500 text-white"
                            : "bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-300"
                        }`}
                      >
                        {mode === "swing" ? "波段" : "日内"}
                      </button>
                    </div>
                    <div className={`text-right ${isProfit ? "text-red-500" : "text-green-500"}`}>
                      <span className="text-sm font-bold tabular-nums">
                        {isProfit ? "+" : ""}{plPct.toFixed(2)}%
                      </span>
                      <span className="text-[10px] ml-1.5 tabular-nums">
                        {pos.current_price.toFixed(2)}
                      </span>
                    </div>
                  </div>

                  {/* 第二行：影子卖出建议(纯提示, 不下单) */}
                  <div className="flex items-center gap-1.5 mt-1">
                    <span className="text-xs">{advice.icon}</span>
                    <span className="text-[10px] text-foreground/75 truncate">{advice.text}</span>
                  </div>

                  {/* Sniper止盈状态(后端追踪, 若有) */}
                  {ts?.activated && ts.peak_price > 0 && (
                    <div className="flex items-center gap-1.5 mt-0.5 text-emerald-500/80">
                      <span className="text-[10px]">
                        Sniper追踪 峰值{ts.peak_price.toFixed(2)} 回撤{((1 - pos.current_price / ts.peak_price) * 100).toFixed(1)}%/{ts.stop_pct}%
                        {ts.mega_buy_count >= 2 ? ` ×${ts.mega_buy_count}` : ""}
                      </span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* 脚注：影子提示说明 */}
        {livePositions.length > 0 && (
          <div className="text-[10px] text-muted-foreground mt-2 pt-2 border-t border-border/40 leading-relaxed">
            💡 卖出建议为<b>影子提示</b>(不自动下单):默认<b>日内</b>(冲高分批+收盘了结);看好的日线机会点徽章切<b>波段</b>(宽跟踪、拿几天)。
          </div>
        )}
      </div>
    </Card>
  );
}
