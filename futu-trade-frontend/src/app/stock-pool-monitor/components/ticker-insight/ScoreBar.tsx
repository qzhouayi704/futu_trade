// 评分条组件 - 展示各维度的多空评分（-100 ~ 100）

"use client";

import { Tooltip } from "@/components/common/Tooltip";
import { HelpCircle } from "lucide-react";

const SIGNAL_COLORS: Record<string, string> = {
    bullish: "text-red-400",
    slightly_bullish: "text-red-300",
    neutral: "text-gray-400",
    slightly_bearish: "text-green-300",
    bearish: "text-green-400",
};

/** 维度说明映射 */
const DIMENSION_DESCRIPTIONS: Record<string, string> = {
    主动买卖:
        "统计主动买入和主动卖出的成交额，反映市场主动性力量对比。评分>0偏多，<0偏空。|25|以上为强信号。",
    密集价位:
        "分析成交量集中的价位，识别支撑位和阻力位。正分表示当前价位有支撑，负分表示面临阻力。",
    成交节奏:
        "分析成交的时间分布和连续性，判断资金进出的节奏。正分表示买方节奏强，负分表示卖方节奏强。",
    量能可信度:
        "对比今日成交量与历史平均水平，判断当前行情的可信度。量能越充足，信号越可靠。",
};

interface ScoreBarProps {
    score: number;
    label: string;
}

export function ScoreBar({ score, label }: ScoreBarProps) {
    const color =
        score > 10 ? "bg-red-500" : score < -10 ? "bg-green-500" : "bg-gray-500";
    const signal =
        score >= 25
            ? "bullish"
            : score >= 10
                ? "slightly_bullish"
                : score > -10
                    ? "neutral"
                    : score > -25
                        ? "slightly_bearish"
                        : "bearish";
    const textColor = SIGNAL_COLORS[signal];
    const description = DIMENSION_DESCRIPTIONS[label];

    return (
        <div className="bg-gray-800/50 rounded p-2">
            <div className="flex items-center justify-between text-xs mb-1">
                <div className="flex items-center gap-1">
                    <span className="text-gray-400">{label}</span>
                    {description && (
                        <Tooltip
                            content={
                                <div className="space-y-1">
                                    <div className="font-medium text-gray-100">{label}</div>
                                    <div className="text-gray-300">{description}</div>
                                    <div className="text-gray-500 text-[10px] mt-1">
                                        评分范围：-100 ~ +100
                                    </div>
                                </div>
                            }
                            side="right"
                        >
                            <span className="cursor-help text-gray-500 hover:text-gray-300 transition-colors">
                                <HelpCircle size={12} />
                            </span>
                        </Tooltip>
                    )}
                </div>
                <span className={`font-medium ${textColor}`}>
                    {score > 0 ? "+" : ""}
                    {score.toFixed(0)}
                </span>
            </div>
            <div className="relative h-2 bg-gray-700 rounded-full overflow-hidden">
                <div className="absolute left-1/2 top-0 w-px h-full bg-gray-500 z-10" />
                {score >= 0 ? (
                    <div
                        className={`absolute left-1/2 h-full ${color} rounded-r-full transition-all duration-500`}
                        style={{ width: `${(score / 100) * 50}%` }}
                    />
                ) : (
                    <div
                        className={`absolute right-1/2 h-full ${color} rounded-l-full transition-all duration-500`}
                        style={{ width: `${(Math.abs(score) / 100) * 50}%` }}
                    />
                )}
            </div>
        </div>
    );
}
