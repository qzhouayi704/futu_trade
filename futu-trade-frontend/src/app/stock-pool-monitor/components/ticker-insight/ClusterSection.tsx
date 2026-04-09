// 成交密集价位组件 - 展示支撑/阻力位和买卖占比

"use client";

import { Tooltip } from "@/components/common/Tooltip";
import { HelpCircle, ShieldCheck, ShieldAlert, Crosshair } from "lucide-react";
import type { DimensionSignal } from "@/types/enhanced-heat";

/** 格式化金额 */
function fmtAmt(v: number): string {
    const abs = Math.abs(v);
    if (abs >= 1_0000_0000) return (v / 1_0000_0000).toFixed(1) + "亿";
    if (abs >= 1_0000) return (v / 1_0000).toFixed(1) + "万";
    return v.toFixed(0);
}

interface ClusterItem {
    price: number;
    volume: number;
    turnover: number;
    buy_pct: number;
    sell_pct: number;
    type: string;
}

const TYPE_CONFIG = {
    support: {
        label: "支撑",
        color: "text-red-400",
        bg: "border-red-500/30",
        icon: ShieldCheck,
        iconColor: "text-red-400",
    },
    resistance: {
        label: "阻力",
        color: "text-green-400",
        bg: "border-green-500/30",
        icon: ShieldAlert,
        iconColor: "text-green-400",
    },
    current: {
        label: "当前",
        color: "text-yellow-400",
        bg: "border-yellow-500/30",
        icon: Crosshair,
        iconColor: "text-yellow-400",
    },
} as const;

interface ClusterSectionProps {
    dim: DimensionSignal;
}

export function ClusterSection({ dim }: ClusterSectionProps) {
    const clusters = (dim.details?.clusters ?? []) as unknown as ClusterItem[];

    if (clusters.length === 0) {
        return (
            <div className="text-center text-gray-500 text-xs py-3 bg-gray-800/30 rounded">
                暂无密集价位数据
            </div>
        );
    }

    return (
        <div className="space-y-1">
            {clusters.map((c, i) => {
                const cfg =
                    TYPE_CONFIG[c.type as keyof typeof TYPE_CONFIG] ?? TYPE_CONFIG.current;
                const Icon = cfg.icon;
                const buyW = Math.round(c.buy_pct * 100);
                const sellW = Math.round(c.sell_pct * 100);
                const neutralW = 100 - buyW - sellW;

                return (
                    <div
                        key={i}
                        className={`bg-gray-800/50 rounded p-2 border-l-2 ${cfg.bg} transition-colors hover:bg-gray-800/70`}
                    >
                        <div className="flex items-center justify-between text-xs mb-1">
                            <div className="flex items-center gap-1.5">
                                <Icon size={12} className={cfg.iconColor} />
                                <span className={`font-medium ${cfg.color}`}>{cfg.label}</span>
                                <span className="text-gray-300 font-mono">
                                    {c.price.toFixed(3)}
                                </span>
                            </div>
                            <span className="text-gray-500">{fmtAmt(c.turnover)}</span>
                        </div>
                        {/* 买卖占比三段条 */}
                        <Tooltip
                            content={
                                <div className="space-y-1.5">
                                    <div className="font-medium text-gray-100">买卖占比分布</div>
                                    <div className="text-gray-300">
                                        该价位的成交量按方向分为三段：
                                    </div>
                                    <div className="flex items-center gap-2 text-[11px]">
                                        <span className="w-2 h-2 rounded-full bg-red-500 inline-block" />
                                        <span className="text-red-400">买入 {buyW}%</span>
                                        <span className="w-2 h-2 rounded-full bg-gray-500 inline-block ml-1" />
                                        <span className="text-gray-400">中性 {neutralW}%</span>
                                        <span className="w-2 h-2 rounded-full bg-green-500 inline-block ml-1" />
                                        <span className="text-green-400">卖出 {sellW}%</span>
                                    </div>
                                    <div className="text-gray-500 text-[10px]">
                                        中性成交指无法判定主动方向的成交
                                    </div>
                                </div>
                            }
                            side="bottom"
                        >
                            <div className="cursor-help">
                                <div className="flex h-2 rounded-full overflow-hidden bg-gray-700">
                                    <div
                                        className="bg-red-500/70 transition-all duration-500"
                                        style={{ width: `${buyW}%` }}
                                    />
                                    <div
                                        className="bg-gray-600 transition-all duration-500"
                                        style={{ width: `${neutralW}%` }}
                                    />
                                    <div
                                        className="bg-green-500/70 transition-all duration-500"
                                        style={{ width: `${sellW}%` }}
                                    />
                                </div>
                            </div>
                        </Tooltip>
                        <div className="flex justify-between text-[10px] text-gray-500 mt-0.5">
                            <span>买 {buyW}%</span>
                            <span className="text-gray-600">中 {neutralW}%</span>
                            <span>卖 {sellW}%</span>
                        </div>
                    </div>
                );
            })}
        </div>
    );
}
