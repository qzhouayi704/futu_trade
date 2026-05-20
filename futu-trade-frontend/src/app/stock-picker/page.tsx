// 选股工作台 — 统一选股功能为Tab页面

"use client";

import { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";

const MarketScanPanel = dynamic(() => import("./components/MarketScanPanel"), { ssr: false });
const OvernightPanel = dynamic(() => import("./components/OvernightPanel"), { ssr: false });
const FlowMomentumScanPanel = dynamic(() => import("./components/FlowMomentumScanPanel"), { ssr: false });

const TABS = [
  { id: "scan", label: "目标股票", emoji: "🎯" },
  { id: "flow", label: "资金异动", emoji: "💥" },
  { id: "overnight", label: "盘后优选", emoji: "🌙" },
];

export default function StockPickerPage() {
  const searchParams = useSearchParams();
  const [activeTab, setActiveTab] = useState("scan");

  useEffect(() => {
    const tab = searchParams.get("tab");
    if (tab && TABS.some((t) => t.id === tab)) setActiveTab(tab);
  }, [searchParams]);

  const handleSelectStock = (code: string) => {
    window.open(`/stock-detail?code=${code}`, '_blank');
  };

  return (
    <div className="min-h-screen">
      <div className="sticky top-0 z-10 bg-card/80 glass border-b border-border">
        <div className="flex items-center px-5">
          <h1 className="text-base font-semibold text-foreground mr-6 py-3 tracking-tight">选股工作台</h1>
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
      <div>
        <div className={activeTab === "scan" ? "" : "hidden"}><MarketScanPanel /></div>
        <div className={activeTab === "flow" ? "" : "hidden"}><FlowMomentumScanPanel onSelectStock={handleSelectStock} /></div>
        <div className={activeTab === "overnight" ? "" : "hidden"}><OvernightPanel /></div>
      </div>
    </div>
  );
}
