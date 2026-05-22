// 策略面板组件 - 展示 TREND / BREAKOUT / MOMENTUM 策略概览

"use client";

import { useState } from "react";
import { Card } from "@/components/common";
import Link from "next/link";

/* ── 策略定义（与 /strategies 页面同步） ── */
interface StrategyInfo {
  id: string;
  name: string;
  label: string;
  icon: string;
  status: "active" | "archived";
  description: string;
  avgReturn: string;
  winRate: string;
  profitFactor: string;
  trades: number;
  bestCombo?: string;
}

const STRATEGIES: StrategyInfo[] = [
  {
    id: "trend",
    name: "TREND",
    label: "趋势策略",
    icon: "📈",
    status: "active",
    description: "捕获放量强势启动，量价配合+逐笔买卖力量判断趋势方向",
    avgReturn: "+1.14%",
    winRate: "48.9%",
    profitFactor: "1.50",
    trades: 1689,
    bestCombo: "75-85分段：+2.16%，55.9%胜率，PF=2.02",
  },
  {
    id: "breakout",
    name: "BREAKOUT",
    label: "蓄势突破",
    icon: "🔺",
    status: "active",
    description: "识别突破前期阻力位，资金流入+量能确认信号有效性",
    avgReturn: "-0.08%",
    winRate: "43.3%",
    profitFactor: "0.97",
    trades: 208,
    bestCombo: "85-100分段：+1.55%，60%胜率，PF=1.65",
  },
  {
    id: "momentum",
    name: "MOMENTUM",
    label: "动量接力",
    icon: "⚡",
    status: "active",
    description: "前日暴涨股次日低吸，量比确认+反包力度评估",
    avgReturn: "+0.82%",
    winRate: "45.1%",
    profitFactor: "1.22",
    trades: 142,
  },
];

function StrategyMiniCard({ s }: { s: StrategyInfo }) {
  const [expanded, setExpanded] = useState(false);
  const returnNum = parseFloat(s.avgReturn);
  const pfNum = parseFloat(s.profitFactor);

  return (
    <div
      className={`rounded-xl border-2 transition-all overflow-hidden ${
        s.status === "active"
          ? "border-indigo-200 dark:border-indigo-800/50 bg-white dark:bg-gray-900"
          : "border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 opacity-70"
      }`}
    >
      {/* 紧凑头部 */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 p-3 md:p-4 text-left group"
      >
        <span className="text-xl md:text-2xl flex-shrink-0">{s.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-bold text-sm text-gray-900 dark:text-gray-100">
              {s.label}
            </span>
            <span className="text-[10px] font-mono text-gray-400 dark:text-gray-500">
              {s.name}
            </span>
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5">
            {s.description}
          </p>
        </div>

        {/* 核心指标 */}
        <div className="hidden sm:flex items-center gap-3 flex-shrink-0">
          <div className="text-center">
            <div
              className={`text-sm font-bold tabular-nums ${
                returnNum >= 0 ? "text-red-600" : "text-green-600"
              }`}
            >
              {s.avgReturn}
            </div>
            <div className="text-[10px] text-gray-400">收益</div>
          </div>
          <div className="text-center">
            <div className="text-sm font-bold text-gray-700 dark:text-gray-300 tabular-nums">
              {s.winRate}
            </div>
            <div className="text-[10px] text-gray-400">胜率</div>
          </div>
          <div className="text-center">
            <div
              className={`text-sm font-bold tabular-nums ${
                pfNum >= 1.0 ? "text-indigo-600" : "text-gray-400"
              }`}
            >
              {s.profitFactor}
            </div>
            <div className="text-[10px] text-gray-400">PF</div>
          </div>
        </div>

        <svg
          className={`w-4 h-4 text-gray-400 transition-transform duration-200 flex-shrink-0 ${
            expanded ? "rotate-180" : ""
          }`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* 展开详情（移动端也显示指标 + bestCombo） */}
      {expanded && (
        <div className="border-t border-gray-100 dark:border-gray-800 px-3 md:px-4 py-3 space-y-2">
          {/* 移动端显示核心指标 */}
          <div className="sm:hidden grid grid-cols-3 gap-2">
            <div className="text-center bg-gray-50 dark:bg-gray-800 rounded-lg py-2">
              <div
                className={`text-base font-bold tabular-nums ${
                  returnNum >= 0 ? "text-red-600" : "text-green-600"
                }`}
              >
                {s.avgReturn}
              </div>
              <div className="text-[10px] text-gray-400">笔均收益</div>
            </div>
            <div className="text-center bg-gray-50 dark:bg-gray-800 rounded-lg py-2">
              <div className="text-base font-bold text-gray-700 dark:text-gray-300 tabular-nums">
                {s.winRate}
              </div>
              <div className="text-[10px] text-gray-400">胜率</div>
            </div>
            <div className="text-center bg-gray-50 dark:bg-gray-800 rounded-lg py-2">
              <div
                className={`text-base font-bold tabular-nums ${
                  pfNum >= 1.0 ? "text-indigo-600" : "text-gray-400"
                }`}
              >
                {s.profitFactor}
              </div>
              <div className="text-[10px] text-gray-400">盈亏比(PF)</div>
            </div>
          </div>

          <div className="flex items-center justify-between text-xs text-gray-500">
            <span>回测样本 {s.trades} 笔</span>
            <span>2026年4-5月</span>
          </div>

          {s.bestCombo && (
            <div className="flex items-center gap-1.5 p-2 rounded-lg bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-100 dark:border-indigo-800/50">
              <span className="text-indigo-500">⭐</span>
              <span className="text-xs text-indigo-700 dark:text-indigo-400 font-medium">
                {s.bestCombo}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function StrategyPanel() {
  const activeCount = STRATEGIES.filter((s) => s.status === "active").length;

  return (
    <Card>
      <div className="p-4 md:p-6">
        <div className="flex items-center justify-between mb-3 md:mb-4">
          <h3 className="text-base md:text-lg font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-2">
            <svg className="w-5 h-5 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
            </svg>
            策略面板
          </h3>
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {activeCount} 个运行中
            </span>
            <Link
              href="/strategies"
              className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              详情 →
            </Link>
          </div>
        </div>

        <div className="space-y-3">
          {STRATEGIES.map((s) => (
            <StrategyMiniCard key={s.id} s={s} />
          ))}
        </div>
      </div>
    </Card>
  );
}
