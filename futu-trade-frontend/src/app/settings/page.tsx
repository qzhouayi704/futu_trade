// 系统管理 — 统一4大管理功能为Tab页面

"use client";

import { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";

const StockPoolPanel = dynamic(() => import("./components/StockPoolPanel"), { ssr: false });
const UnsubscribedPanel = dynamic(() => import("./components/UnsubscribedPanel"), { ssr: false });
const AdvisorPanel = dynamic(() => import("./components/AdvisorPanel"), { ssr: false });
const ConfigPanel = dynamic(() => import("./components/ConfigPanel"), { ssr: false });

const TABS = [
  { id: "pool", label: "股票池", emoji: "📦" },
  { id: "unsub", label: "未订阅股票", emoji: "👁️" },
  { id: "advisor", label: "决策助理", emoji: "🤖" },
  { id: "config", label: "系统配置", emoji: "⚙️" },
];

export default function SettingsPage() {
  const searchParams = useSearchParams();
  const [activeTab, setActiveTab] = useState("pool");

  useEffect(() => {
    const tab = searchParams.get("tab");
    if (tab && TABS.some((t) => t.id === tab)) setActiveTab(tab);
  }, [searchParams]);

  return (
    <div className="min-h-screen">
      <div className="sticky top-0 z-10 bg-card/80 glass border-b border-border">
        <div className="flex items-center px-5">
          <h1 className="text-base font-semibold text-foreground mr-6 py-3 tracking-tight">系统管理</h1>
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
        <div className={activeTab === "pool" ? "" : "hidden"}><StockPoolPanel /></div>
        <div className={activeTab === "unsub" ? "" : "hidden"}><UnsubscribedPanel /></div>
        <div className={activeTab === "advisor" ? "" : "hidden"}><AdvisorPanel /></div>
        <div className={activeTab === "config" ? "" : "hidden"}><ConfigPanel /></div>
      </div>
    </div>
  );
}
