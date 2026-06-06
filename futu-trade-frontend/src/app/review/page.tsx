// 复盘中心 — 盘后复盘（Tab式整合）

"use client";

import { useState, Suspense, lazy } from "react";

type TabKey = "trades" | "pipeline" | "performance" | "news";

const TABS: { key: TabKey; label: string; emoji: string }[] = [
  { key: "trades", label: "今日交易", emoji: "💰" },
  { key: "pipeline", label: "信号追踪", emoji: "📊" },
  { key: "performance", label: "绩效分析", emoji: "📈" },
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
        <p className="text-sm text-muted-foreground mt-1">交易记录 · 信号追踪 · 绩效分析</p>
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
        {activeTab === "trades" && (
          <div className="text-center py-20 text-muted-foreground">
            <p className="text-lg mb-2">💰 模拟交易记录</p>
            <p className="text-sm">现有模拟交易页面将整合到此处</p>
          </div>
        )}
        {activeTab === "pipeline" && (
          <div className="text-center py-20 text-muted-foreground">
            <p className="text-lg mb-2">📊 信号→决策→执行 全链路</p>
            <p className="text-sm">现有信号追踪页面将整合到此处</p>
          </div>
        )}
        {activeTab === "performance" && (
          <div className="text-center py-20 text-muted-foreground">
            <p className="text-lg mb-2">📈 绩效分析</p>
            <p className="text-sm">胜率、收益率、Sharpe比率、回撤曲线</p>
          </div>
        )}
        {activeTab === "news" && (
          <div className="text-center py-20 text-muted-foreground">
            <p className="text-lg mb-2">📰 热点新闻</p>
            <p className="text-sm">现有新闻页面将整合到此处</p>
          </div>
        )}
      </Suspense>
    </div>
  );
}
