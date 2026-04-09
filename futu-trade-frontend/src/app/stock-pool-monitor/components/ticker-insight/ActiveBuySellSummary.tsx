// 主动买卖力量摘要组件

"use client";

import { Tooltip } from "@/components/common/Tooltip";
import { HelpCircle } from "lucide-react";
import type { DimensionSignal } from "@/types/enhanced-heat";

/** 格式化金额 */
function fmtAmt(v: number): string {
    const abs = Math.abs(v);
    if (abs >= 1_0000_0000) return (v / 1_0000_0000).toFixed(1) + "亿";
    if (abs >= 1_0000) return (v / 1_0000).toFixed(1) + "万";
    return v.toFixed(0);
}

interface ActiveBuySellSummaryProps {
    dim: DimensionSignal;
}

export function ActiveBuySellSummary({ dim }: ActiveBuySellSummaryProps) {
    const d = dim.details as Record<string, number>;
    const buyTurnover = d?.buy_turnover ?? 0;
    const sellTurnover = d?.sell_turnover ?? 0;
    const netTurnover = d?.net_turnover ?? 0;
    const ratio = d?.buy_sell_ratio ?? 1;

    // 检测异常值：力量比为10但买卖额都为0（数据异常）
    const isAbnormal = ratio === 10 && buyTurnover === 0 && sellTurnover === 0;

    const timeStart = (d.time_range_start as unknown as string) ?? "";
    const timeEnd = (d.time_range_end as unknown as string) ?? "";
    const trendDirection = (d.trend_direction as unknown as string) ?? "";

    return (
        <div className="bg-gray-800/50 rounded p-2">
            <div className="flex items-center justify-between text-xs mb-1">
                <div className="flex items-center gap-1">
                    <span className="text-gray-400">主动买卖</span>
                    <Tooltip
                        content={
                            <div className="space-y-1">
                                <div className="font-medium text-gray-100">主动买卖力量</div>
                                <div className="text-gray-300">
                                    统计主动买入和主动卖出的成交额，反映市场主动性力量对比。
                                </div>
                                <div className="text-gray-400 text-[10px] space-y-0.5 mt-1">
                                    <div>
                                        • <span className="text-red-400">主动买入</span>
                                        ：以卖方报价成交，表示买方急于买入
                                    </div>
                                    <div>
                                        • <span className="text-green-400">主动卖出</span>
                                        ：以买方报价成交，表示卖方急于卖出
                                    </div>
                                    <div>
                                        • <span className="text-gray-300">力量比</span>：买入额 ÷
                                        卖出额，&gt;1 偏多，&lt;1 偏空
                                    </div>
                                </div>
                            </div>
                        }
                        side="right"
                    >
                        <span className="cursor-help text-gray-500 hover:text-gray-300 transition-colors">
                            <HelpCircle size={12} />
                        </span>
                    </Tooltip>
                </div>
                <span
                    className={`font-medium ${netTurnover > 0 ? "text-red-400" : netTurnover < 0 ? "text-green-400" : "text-gray-400"}`}
                >
                    净{netTurnover > 0 ? "买" : "卖"} {fmtAmt(Math.abs(netTurnover))}
                </span>
            </div>
            <div className="grid grid-cols-3 gap-1 text-[10px]">
                <div className="text-center">
                    <div className="text-gray-500">主动买入</div>
                    <div className="text-red-400">{fmtAmt(buyTurnover)}</div>
                </div>
                <div className="text-center">
                    <div className="text-gray-500">主动卖出</div>
                    <div className="text-green-400">{fmtAmt(sellTurnover)}</div>
                </div>
                <div className="text-center">
                    <div className="text-gray-500">力量比</div>
                    <div className={`flex items-center justify-center gap-1 ${ratio >= 1 ? "text-red-400" : "text-green-400"}`}>
                        <span>{ratio.toFixed(2)}</span>
                        {isAbnormal && (
                            <Tooltip content="数据可能异常，请刷新或检查后端日志">
                                <span className="text-yellow-400 text-xs">⚠️</span>
                            </Tooltip>
                        )}
                    </div>
                </div>
            </div>
            {trendDirection && (
                <div className="flex items-center justify-between mt-1.5 pt-1.5 border-t border-gray-700/50">
                    <span
                        className={`text-[10px] px-1 py-0.5 rounded ${trendDirection === "买方增强"
                                ? "bg-red-500/20 text-red-400"
                                : trendDirection === "卖方增强"
                                    ? "bg-green-500/20 text-green-400"
                                    : "bg-gray-500/20 text-gray-400"
                            }`}
                    >
                        {trendDirection}
                    </span>
                    {timeStart && (
                        <span className="text-[10px] text-gray-500">
                            {timeStart} ~ {timeEnd}
                        </span>
                    )}
                </div>
            )}
        </div>
    );
}
