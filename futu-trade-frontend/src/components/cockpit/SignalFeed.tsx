// 驾驶舱信号流 — 在原有 UnifiedSignalFeed 基础上增加筛选Tab

"use client";

import { useState } from "react";
import { UnifiedSignalFeed } from "@/app/components/dashboard/UnifiedSignalFeed";

type FilterType = "all" | "v1" | "v2" | "momentum" | "decision";

interface SignalFeedProps {
  positionStockCodes: string[];
  onSelectStock?: (code: string) => void;
}

const FILTERS: { key: FilterType; label: string; emoji: string }[] = [
  { key: "all", label: "全部", emoji: "📡" },
  { key: "v1", label: "V1-Sniper", emoji: "🔫" },
  { key: "v2", label: "V2-StockScorer", emoji: "📈" },
  { key: "momentum", label: "动量引擎", emoji: "⚡" },
  { key: "decision", label: "决策", emoji: "🎯" },
];

export function SignalFeed({ positionStockCodes, onSelectStock }: SignalFeedProps) {
  const [filter, setFilter] = useState<FilterType>("all");

  return (
    <div>
      {/* 筛选Tab */}
      <div className="flex items-center gap-1 mb-3 overflow-x-auto pb-1">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`px-3 py-1.5 text-[10px] font-bold rounded-lg transition-all shrink-0 ${
              filter === f.key
                ? "bg-primary text-primary-foreground shadow-sm"
                : "bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
          >
            {f.emoji} {f.label}
          </button>
        ))}
      </div>

      {/* 信号流（复用并适配新类型后的组件） */}
      <UnifiedSignalFeed
        positionStockCodes={positionStockCodes}
        maxItems={30}
        sourceFilter={filter}
        onSelectStock={onSelectStock}
      />
    </div>
  );
}
