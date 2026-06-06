// 复盘中心 — 盘后复盘（Tab式整合现有页面）

"use client";

import { useState, Suspense, lazy } from "react";

// 懒加载现有页面
const SimulatedTradesPage = lazy(() => import("@/app/simulated-trades/page"));
const SniperSignalsPage = lazy(() => import("@/app/sniper-signals/page"));
const NewsPage = lazy(() => import("@/app/news/page"));
const PreCheckPage = lazy(() => import("@/app/pre-check/page"));

type TabKey = "trades" | "signals" | "precheck" | "news";

const TABS: { key: TabKey; label: string; emoji: string }[] = [
  { key: "trades", label: "模拟交易", emoji: "💰" },
  { key: "signals", label: "信号总览", emoji: "🔫" },
  { key: "precheck", label: "交易决策", emoji: "⚡" },
  { key: "news", label: "热点新闻", emoji: "📰" },
];

function TabLoading() {
  return (
    <div className="flex items-center justify-center py-20 text-muted-foreground">
      <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin mr-3" />
      加载中...
    </div>
  );
}

export default function ReviewPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("trades");

  return (
    <div className="container mx-auto px-3 md:px-4 py-4 md:py-6 max-w-[1400px]">
      {/* 标题 */}
      <div className="mb-5">
        <h1 className="text-xl font-bold text-foreground">📊 复盘中心</h1>
        <p className="text-sm text-muted-foreground mt-1">模拟交易 · 信号总览 · 交易决策 · 热点新闻</p>
      </div>

      {/* Tab 导航 */}
      <div className="flex items-center gap-1 mb-5 bg-muted/30 p-1 rounded-xl w-fit">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-4 py-2 text-sm font-medium rounded-lg transition-all ${
              activeTab === tab.key
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab.emoji} {tab.label}
          </button>
        ))}
      </div>

      {/* Tab 内容 */}
      <Suspense fallback={<TabLoading />}>
        {activeTab === "trades" && <SimulatedTradesPage />}
        {activeTab === "signals" && <SniperSignalsPage />}
        {activeTab === "precheck" && <PreCheckPage />}
        {activeTab === "news" && <NewsPage />}
      </Suspense>
    </div>
  );
}
