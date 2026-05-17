// 个股深度 — 统一3大分析功能为Tab页面

"use client";

import { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";

const EnhancedHeatPanel = dynamic(() => import("./components/EnhancedHeatPanel"), { ssr: false });
const PriceAnalysisPanel = dynamic(() => import("./components/PriceAnalysisPanel"), { ssr: false });
const KlinePanel = dynamic(() => import("./components/KlinePanel"), { ssr: false });

interface Tab {
  id: string;
  label: string;
  emoji: string;
}

const TABS: Tab[] = [
  { id: "analysis", label: "综合分析", emoji: "📊" },
  { id: "price", label: "价格位置", emoji: "📉" },
  { id: "kline", label: "K线图表", emoji: "📈" },
];

export default function StockDetailPage() {
  const searchParams = useSearchParams();
  const [activeTab, setActiveTab] = useState("analysis");
  const [initialCode, setInitialCode] = useState<string | null>(null);

  useEffect(() => {
    const tab = searchParams.get("tab");
    if (tab && TABS.some((t) => t.id === tab)) {
      setActiveTab(tab);
    }
    const code = searchParams.get("code");
    if (code) {
      setInitialCode(code);
    }
  }, [searchParams]);

  return (
    <div className="min-h-screen">
      {/* Tab 栏 */}
      <div className="sticky top-0 z-10 bg-card/80 glass border-b border-border">
        <div className="flex items-center px-5">
          <h1 className="text-base font-semibold text-foreground mr-6 py-3 tracking-tight">个股深度</h1>
          <div className="flex space-x-1">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-3 text-sm font-medium transition-all border-b-2 ${
                  activeTab === tab.id
                    ? "border-primary text-primary bg-primary/10"
                    : "border-transparent text-muted-foreground hover:text-foreground hover:bg-accent/50"
                }`}
              >
                <span>{tab.emoji}</span>
                <span>{tab.label}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Tab 内容 */}
      <div>
        <div className={activeTab === "analysis" ? "" : "hidden"}>
          <EnhancedHeatPanel initialCode={initialCode} />
        </div>
        <div className={activeTab === "price" ? "" : "hidden"}>
          <PriceAnalysisPanel />
        </div>
        <div className={activeTab === "kline" ? "" : "hidden"}>
          <KlinePanel />
        </div>
      </div>
    </div>
  );
}
