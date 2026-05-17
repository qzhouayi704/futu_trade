// 交易驾驶舱 — 统一4大交易功能为Tab页面

"use client";

import { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";

// 动态导入各Tab面板（按需加载）
const TradePanel = dynamic(() => import("./components/TradePanel"), { ssr: false });
const ConditionsPanel = dynamic(() => import("./components/ConditionsPanel"), { ssr: false });
const OptimizerPanel = dynamic(() => import("./components/OptimizerPanel"), { ssr: false });
const FlowSignalsPanel = dynamic(() => import("./components/FlowSignalsPanel"), { ssr: false });

// 持仓面板复用现有页面
const PositionsPanel = dynamic(() => import("./positions/page"), { ssr: false });

interface Tab {
  id: string;
  label: string;
  emoji: string;
  description: string;
}

const TABS: Tab[] = [
  { id: "trade", label: "交易总览", emoji: "🏠", description: "信号·持仓·下单" },
  { id: "positions", label: "持仓管理", emoji: "📋", description: "分仓·止盈·订单" },
  { id: "conditions", label: "交易条件", emoji: "📊", description: "策略条件·K线额度" },
  { id: "optimizer", label: "风控管控", emoji: "🛡️", description: "评分·阶段·频率" },
  { id: "rules", label: "交易规则", emoji: "📜", description: "资金信号·风控·策略" },
];

export default function TradingCockpit() {
  const searchParams = useSearchParams();
  const [activeTab, setActiveTab] = useState("trade");

  // 从URL参数读取初始Tab
  useEffect(() => {
    const tab = searchParams.get("tab");
    if (tab && TABS.some((t) => t.id === tab)) {
      setActiveTab(tab);
    }
  }, [searchParams]);

  return (
    <div className="min-h-screen">
      {/* Tab 栏 */}
      <div className="sticky top-0 z-10 bg-card/80 glass border-b border-border">
        <div className="flex items-center px-5">
          <h1 className="text-base font-semibold text-foreground mr-6 py-3 tracking-tight">交易驾驶舱</h1>
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
                <span className="hidden lg:inline text-xs text-muted-foreground ml-1">
                  {tab.description}
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Tab 内容 */}
      <div className="p-0">
        <div className={activeTab === "trade" ? "" : "hidden"}>
          <TradePanel />
        </div>
        <div className={activeTab === "positions" ? "" : "hidden"}>
          <PositionsPanel />
        </div>
        <div className={activeTab === "conditions" ? "" : "hidden"}>
          <ConditionsPanel />
        </div>
        <div className={activeTab === "optimizer" ? "" : "hidden"}>
          <OptimizerPanel />
        </div>
        <div className={activeTab === "rules" ? "" : "hidden"}>
          <FlowSignalsPanel />
        </div>
      </div>
    </div>
  );
}
