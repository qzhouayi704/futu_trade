// 三策略评分卡片 — TREND / BREAKOUT / MOMENTUM
"use client";

import { useState } from "react";
import type { TopHotStock } from "@/types";

interface Props {
  stock: TopHotStock | null;
}

interface StrategyDetail {
  name: string;
  score: number;
  max_score: number;
  value?: string | null;
  note?: string | null;
}

interface Strategy {
  mode: string;
  label: string;
  total_score: number;
  passed: boolean;
  details: StrategyDetail[];
}

const STRATEGY_ORDER = ["trend", "breakout", "momentum"];
const STRATEGY_META: Record<string, { emoji: string; color: string; desc: string }> = {
  trend:    { emoji: "📈", color: "blue",   desc: "基于趋势动量的评估" },
  breakout: { emoji: "🔺", color: "purple", desc: "前高突破型机会" },
  momentum: { emoji: "🚀", color: "orange", desc: "前日暴涨股次日低吸" },
};

export default function StrategyScoringCards({ stock }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!stock?.consensus?.strategies) return null;

  const { strategies } = stock.consensus;
  const bestMode = stock.consensus.best_mode?.toLowerCase() || "trend";
  const breakoutTriggered = stock.consensus.breakout_triggered ?? false;
  const momentumTriggered = stock.consensus.momentum_triggered ?? false;

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {STRATEGY_ORDER.map((key) => {
        const strategy = strategies[key] as Strategy | undefined;
        if (!strategy) return null;

        const meta = STRATEGY_META[key] || STRATEGY_META.trend;
        const isBest = key === bestMode;
        const isTriggered = key === "trend" || (key === "breakout" && breakoutTriggered) || (key === "momentum" && momentumTriggered);
        const isExpanded = expanded === key;
        const score = strategy.total_score;

        // 颜色主题
        const scoreColor = score >= 60 ? "green" : score >= 40 ? "amber" : "red";
        const borderClass = isBest
          ? `border-${meta.color}-500/50 shadow-lg shadow-${meta.color}-500/10`
          : "border-border";
        const opacity = isTriggered ? "" : "opacity-40";

        return (
          <div
            key={key}
            className={`relative rounded-xl border-2 bg-card overflow-hidden transition-all ${borderClass} ${opacity}`}
          >
            {/* 最佳策略标记 */}
            {isBest && (
              <div className="absolute top-0 right-0 bg-gradient-to-l from-primary/20 to-transparent px-3 py-0.5 text-[10px] font-bold text-primary rounded-bl-lg">
                最佳
              </div>
            )}

            {/* 卡片头部 */}
            <button
              className="w-full text-left px-4 py-3 flex items-center justify-between hover:bg-accent/30 transition-colors"
              onClick={() => setExpanded(isExpanded ? null : key)}
            >
              <div className="flex items-center gap-2">
                <span className="text-xl">{meta.emoji}</span>
                <div>
                  <div className="text-sm font-semibold text-foreground">{strategy.label}</div>
                  <div className="text-[10px] text-muted-foreground">{meta.desc}</div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className={`text-2xl font-bold tabular-nums text-${scoreColor}-600`}>
                  {score}
                </span>
                <span className="text-xs text-muted-foreground">/100</span>
                {strategy.passed && <span className="text-green-500">✅</span>}
              </div>
            </button>

            {/* 分数条 */}
            <div className="px-4 pb-2">
              <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${
                    score >= 60 ? "bg-green-500" : score >= 40 ? "bg-amber-500" : "bg-red-500"
                  }`}
                  style={{ width: `${Math.min(score, 100)}%` }}
                />
              </div>
            </div>

            {/* 未触发标记 */}
            {!isTriggered && (
              <div className="px-4 pb-3 text-[10px] text-muted-foreground">
                未触发（{key === "breakout" ? "无突破信号" : "前日涨幅未达阈值"}）
              </div>
            )}

            {/* 展开的详细维度 */}
            {isExpanded && (
              <div className="px-4 pb-4 space-y-2 border-t border-border pt-3">
                {strategy.details.map((d, i) => (
                  <div key={i} className="flex items-center gap-3 text-xs">
                    {/* 状态图标 */}
                    <span className="w-4 text-center">
                      {d.score >= d.max_score ? "✅" : d.score > 0 ? "⚡" : "❌"}
                    </span>
                    {/* 名称 */}
                    <span className="w-24 text-muted-foreground truncate">{d.name}</span>
                    {/* 分数条 */}
                    <div className="flex-1 h-3 rounded-full bg-muted overflow-hidden relative">
                      <div
                        className={`h-full rounded-full ${
                          d.score >= d.max_score
                            ? "bg-green-500"
                            : d.score > d.max_score * 0.5
                            ? "bg-blue-500"
                            : d.score > 0
                            ? "bg-amber-500"
                            : "bg-red-500/30"
                        }`}
                        style={{ width: `${d.max_score > 0 ? (d.score / d.max_score) * 100 : 0}%` }}
                      />
                    </div>
                    {/* 分数 */}
                    <span className="w-12 text-right font-mono tabular-nums text-foreground">
                      {d.score}/{d.max_score}
                    </span>
                    {/* 值 */}
                    <span className="w-16 text-right text-muted-foreground truncate">
                      {d.note || (d.value != null ? d.value : "")}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
