// 量能可信度摘要组件

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

interface CredibilitySummaryProps {
    dim: DimensionSignal;
}

export function CredibilitySummary({ dim }: CredibilitySummaryProps) {
    const d = dim.details as Record<string, number | string>;
    const volumeRatio = Number(d?.volume_ratio ?? 0);
    const todayTurnover = Number(d?.today_turnover ?? 0);
    const avgTurnover = Number(d?.avg_daily_turnover ?? 0);
    const market = (d?.market ?? "HK") as string;

    const noHistoryData = avgTurnover <= 0;

    if (noHistoryData) {
        return (
            <div className="bg-gray-800/50 rounded p-2">
                <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-gray-400">量能可信度</span>
                    <span className="text-yellow-500 font-medium">数据不足</span>
                </div>
                <p className="text-[10px] text-yellow-500/80 leading-relaxed">
                    该股票暂无K线历史数据，无法计算日均成交额。
                    请在K线管理中下载该股票的历史数据后刷新。
                </p>
            </div>
        );
    }

    const ratioColor =
        volumeRatio >= 1.0
            ? "text-red-400"
            : volumeRatio >= 0.5
                ? "text-yellow-400"
                : "text-green-400";

    return (
        <div className="bg-gray-800/50 rounded p-2">
            <div className="flex items-center justify-between text-xs mb-1">
                <div className="flex items-center gap-1">
                    <span className="text-gray-400">量能可信度</span>
                    <Tooltip
                        content={
                            <div className="space-y-1">
                                <div className="font-medium text-gray-100">量能可信度</div>
                                <div className="text-gray-300">
                                    对比今日成交量与历史平均水平，判断当前行情的可信度。
                                </div>
                                <div className="text-gray-400 text-[10px] space-y-0.5 mt-1">
                                    <div>
                                        • <span className="text-red-400">≥ 1.0倍</span>
                                        ：量能充足，信号可靠
                                    </div>
                                    <div>
                                        • <span className="text-yellow-400">0.5 ~ 1.0倍</span>
                                        ：量能一般，需谨慎
                                    </div>
                                    <div>
                                        • <span className="text-green-400">&lt; 0.5倍</span>
                                        ：量能不足，可能为诱多/诱空
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
                <span className={`font-medium ${ratioColor}`}>
                    {volumeRatio > 0 ? `${volumeRatio.toFixed(1)}倍日均` : "无数据"}
                </span>
            </div>
            <div className="grid grid-cols-3 gap-1 text-[10px]">
                <div className="text-center">
                    <div className="text-gray-500">今日成交额</div>
                    <div className="text-gray-300">{fmtAmt(todayTurnover)}</div>
                </div>
                <div className="text-center">
                    <div className="text-gray-500">
                        {market === "US" ? "美股" : "港股"}日均
                    </div>
                    <div className="text-gray-300">{fmtAmt(avgTurnover)}</div>
                </div>
                <div className="text-center">
                    <div className="text-gray-500">量能评分</div>
                    <div className={ratioColor}>
                        {dim.score > 0 ? "+" : ""}
                        {dim.score.toFixed(0)}
                    </div>
                </div>
            </div>
        </div>
    );
}
