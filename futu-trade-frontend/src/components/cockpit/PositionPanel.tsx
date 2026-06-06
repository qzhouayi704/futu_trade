// 驾驶舱持仓面板 — 实时盈亏 + Sniper止盈状态

"use client";

import { useState, useEffect, useMemo } from "react";
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

export function PositionPanel({ positions, loading, realtimePrices }: PositionPanelProps) {
  const [trailingStatus, setTrailingStatus] = useState<Record<string, TrailingStatus>>({});

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

              // Sniper状态指示
              let sniperIcon = "⚪";
              let sniperText = "";
              let sniperColor = "text-muted-foreground";

              if (ts) {
                if (ts.mega_sell) {
                  sniperIcon = "🔴";
                  sniperText = "mega_sell→即将止盈";
                  sniperColor = "text-red-500";
                } else if (ts.activated) {
                  sniperIcon = "🟢";
                  const drawdown = ts.peak_price > 0
                    ? ((1 - pos.current_price / ts.peak_price) * 100).toFixed(1)
                    : "0.0";
                  sniperText = `追踪中 峰值${ts.peak_price.toFixed(2)} 回撤${drawdown}%/${ts.stop_pct}%`;
                  if (ts.mega_buy_count >= 2) {
                    sniperText += ` ×${ts.mega_buy_count}`;
                  }
                  sniperColor = "text-emerald-500";
                }
              }

              return (
                <div
                  key={pos.stock_code}
                  className={`px-3 py-2.5 rounded-lg border transition-all hover:shadow-sm ${
                    ts?.mega_sell
                      ? "bg-red-50/60 border-red-200/50 dark:bg-red-950/20 dark:border-red-800/30"
                      : ts?.activated
                        ? "bg-emerald-50/40 border-emerald-200/40 dark:bg-emerald-950/15 dark:border-emerald-800/25"
                        : "bg-card border-border/50"
                  }`}
                >
                  {/* 第一行：名称 + 盈亏 */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="font-bold text-sm text-foreground truncate">
                        {pos.stock_name}
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        {pos.stock_code}
                      </span>
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

                  {/* 第二行：Sniper止盈状态 */}
                  {(ts?.activated || ts?.mega_sell) && (
                    <div className={`flex items-center gap-1.5 mt-1 ${sniperColor}`}>
                      <span className="text-xs">{sniperIcon}</span>
                      <span className="text-[10px] font-medium">
                        {sniperText}
                      </span>
                    </div>
                  )}

                  {/* 无Sniper信号时显示默认止盈 */}
                  {!ts && plPct >= 5 && (
                    <div className="flex items-center gap-1.5 mt-1 text-muted-foreground">
                      <span className="text-xs">⚪</span>
                      <span className="text-[10px]">
                        默认止盈: 涨≥5%已激活, 回撤3%触发
                      </span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Card>
  );
}
