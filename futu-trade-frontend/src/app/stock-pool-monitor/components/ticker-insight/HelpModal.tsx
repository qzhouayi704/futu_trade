// 帮助文档模态框 - 展示逐笔成交分析的详细说明

"use client";

import { useState, useEffect, useCallback } from "react";
import { HelpCircle, X, TrendingUp, BarChart3, Activity, Gauge } from "lucide-react";

interface HelpModalProps {
    trigger?: React.ReactNode;
}

const SECTIONS = [
    {
        icon: TrendingUp,
        title: "主动买卖",
        color: "text-blue-400",
        content: [
            "统计主动买入和主动卖出的成交额，反映市场主动性力量对比。",
            "• 主动买入：以卖方报价成交，表示买方急于买入",
            "• 主动卖出：以买方报价成交，表示卖方急于卖出",
            "• 力量比 > 1 表示买方力量占优，< 1 表示卖方力量占优",
        ],
    },
    {
        icon: BarChart3,
        title: "密集价位",
        color: "text-purple-400",
        content: [
            "分析成交量集中的价位，识别支撑位和阻力位。",
            "• 支撑位（红色）：大量买入成交集中的价位，价格下跌时可能获得支撑",
            "• 阻力位（绿色）：大量卖出成交集中的价位，价格上涨时可能受到阻力",
            "• 买卖占比条分为三段：红色(买入)、灰色(中性)、绿色(卖出)",
            "• 中性成交指无法判定主动方向的成交",
        ],
    },
    {
        icon: Activity,
        title: "成交节奏",
        color: "text-cyan-400",
        content: [
            "分析成交的时间分布和连续性，判断资金进出的节奏。",
            "• 正分表示买方成交节奏强，持续进场",
            "• 负分表示卖方成交节奏强，持续退场",
            "• 节奏越集中，趋势越明确",
        ],
    },
    {
        icon: Gauge,
        title: "量能可信度",
        color: "text-amber-400",
        content: [
            "对比今日成交量与历史平均水平，判断当前行情的可信度。",
            "• ≥ 1.0 倍日均：量能充足，信号可靠",
            "• 0.5 ~ 1.0 倍：量能一般，需谨慎参考",
            "• < 0.5 倍：量能不足，可能为诱多/诱空",
        ],
    },
];

const USAGE_TIPS = [
    "综合信号为各维度加权得分的结果，评分范围 -100 ~ +100",
    "\"强多\"(≥25)、\"偏多\"(10~25)、\"中性\"(-10~10)、\"偏空\"(-25~-10)、\"强空\"(≤-25)",
    "当量能可信度不足时，其他维度的信号可靠性降低",
    "建议结合盘口10档和资金流向综合判断",
];

export function HelpModal({ trigger }: HelpModalProps) {
    const [isOpen, setIsOpen] = useState(false);

    const handleClose = useCallback(() => setIsOpen(false), []);

    // ESC 键关闭
    useEffect(() => {
        if (!isOpen) return;
        const handleKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") handleClose();
        };
        document.addEventListener("keydown", handleKey);
        return () => document.removeEventListener("keydown", handleKey);
    }, [isOpen, handleClose]);

    return (
        <>
            {/* 触发按钮 */}
            <button
                onClick={() => setIsOpen(true)}
                className="text-gray-500 hover:text-gray-300 transition-colors"
                aria-label="帮助说明"
                role="button"
            >
                {trigger ?? <HelpCircle size={14} />}
            </button>

            {/* 模态框 */}
            {isOpen && (
                <div className="fixed inset-0 z-[200] flex items-center justify-center">
                    {/* 遮罩 */}
                    <div
                        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
                        onClick={handleClose}
                    />
                    {/* 内容 */}
                    <div
                        className="relative w-full max-w-lg mx-4 max-h-[80vh] bg-gray-900 border border-gray-700 rounded-xl shadow-2xl overflow-hidden animate-in fade-in-0 zoom-in-95 duration-200"
                        onClick={(e) => e.stopPropagation()}
                        role="dialog"
                        aria-modal="true"
                        aria-label="逐笔成交分析帮助"
                    >
                        {/* 头部 */}
                        <div className="sticky top-0 bg-gray-900/95 backdrop-blur border-b border-gray-700 px-5 py-3 flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                <HelpCircle size={18} className="text-blue-400" />
                                <h3 className="text-base font-semibold text-white">
                                    逐笔成交分析说明
                                </h3>
                            </div>
                            <button
                                onClick={handleClose}
                                className="text-gray-400 hover:text-white transition-colors p-1 rounded hover:bg-gray-700/50"
                                aria-label="关闭"
                            >
                                <X size={18} />
                            </button>
                        </div>

                        {/* 内容区 */}
                        <div className="overflow-y-auto max-h-[calc(80vh-52px)] p-5 space-y-4">
                            {/* 概述 */}
                            <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3">
                                <p className="text-xs text-blue-300 leading-relaxed">
                                    逐笔成交分析从四个维度实时分析逐笔成交数据，
                                    帮助您判断当前价位的多空力量对比、支撑阻力位置、
                                    成交节奏和量能可靠性。
                                </p>
                            </div>

                            {/* 各维度说明 */}
                            {SECTIONS.map((section) => {
                                const Icon = section.icon;
                                return (
                                    <div key={section.title} className="space-y-1.5">
                                        <div className="flex items-center gap-2">
                                            <Icon size={14} className={section.color} />
                                            <h4 className={`text-sm font-medium ${section.color}`}>
                                                {section.title}
                                            </h4>
                                        </div>
                                        <div className="bg-gray-800/50 rounded-lg p-3 space-y-1">
                                            {section.content.map((line, j) => (
                                                <p
                                                    key={j}
                                                    className={`text-xs leading-relaxed ${j === 0 ? "text-gray-300" : "text-gray-400"}`}
                                                >
                                                    {line}
                                                </p>
                                            ))}
                                        </div>
                                    </div>
                                );
                            })}

                            {/* 使用建议 */}
                            <div className="space-y-1.5">
                                <h4 className="text-sm font-medium text-gray-300">
                                    💡 使用建议
                                </h4>
                                <div className="bg-gray-800/50 rounded-lg p-3 space-y-1">
                                    {USAGE_TIPS.map((tip, i) => (
                                        <p key={i} className="text-xs text-gray-400 leading-relaxed">
                                            • {tip}
                                        </p>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}
