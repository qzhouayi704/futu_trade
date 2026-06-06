// 选股台 — 盘前/盘后选股研究（Tab式整合现有页面）

"use client";

import { useState, Suspense, lazy } from "react";

// 懒加载现有页面（直接复用，零改造）
const OvernightScreenCard = lazy(() =>
  import("@/app/components/dashboard/OvernightScreenCard").then(m => ({ default: m.OvernightScreenCard }))
);
const PlatesPage = lazy(() => import("@/app/plates/page"));
const StockPickerPage = lazy(() => import("@/app/stock-picker/page"));
const StockDetailPage = lazy(() => import("@/app/stock-detail/page"));

type TabKey = "overnight" | "plates" | "picker" | "detail";

const TABS: { key: TabKey; label: string; emoji: string }[] = [
  { key: "overnight", label: "盘后优选", emoji: "🌙" },
  { key: "plates", label: "板块热度", emoji: "🔥" },
  { key: "picker", label: "选股工作台", emoji: "🎯" },
  { key: "detail", label: "个股分析", emoji: "🔍" },
];

function TabLoading() {
  return (
    <div className="flex items-center justify-center py-20 text-muted-foreground">
      <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin mr-3" />
      加载中...
    </div>
  );
}

export default function DiscoveryPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("overnight");

  return (
    <div className="container mx-auto px-3 md:px-4 py-4 md:py-6 max-w-[1400px]">
      {/* 标题 */}
      <div className="mb-5">
        <h1 className="text-xl font-bold text-foreground">📡 选股台</h1>
        <p className="text-sm text-muted-foreground mt-1">盘前优选 · 板块轮动 · 个股研究</p>
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
        {activeTab === "overnight" && <OvernightScreenCard />}
        {activeTab === "plates" && <PlatesPage />}
        {activeTab === "picker" && <StockPickerPage />}
        {activeTab === "detail" && <StockDetailPage />}
      </Suspense>
    </div>
  );
}
