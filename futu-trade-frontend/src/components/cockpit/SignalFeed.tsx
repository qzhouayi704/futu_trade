// 驾驶舱信号流 — 在原有 UnifiedSignalFeed 基础上增加筛选Tab

"use client";

import { useState } from "react";
import { UnifiedSignalFeed } from "@/app/components/dashboard/UnifiedSignalFeed";

type FilterType = "all" | "sniper" | "alert" | "pipeline";

interface SignalFeedProps {
  positionStockCodes: string[];
}

const FILTERS: { key: FilterType; label: string; emoji: string }[] = [
  { key: "all", label: "全部", emoji: "📡" },
  { key: "sniper", label: "Sniper", emoji: "🔫" },
  { key: "alert", label: "量价", emoji: "⚡" },
  { key: "pipeline", label: "决策", emoji: "✅" },
];

export function SignalFeed({ positionStockCodes }: SignalFeedProps) {
  const [filter, setFilter] = useState<FilterType>("all");

  return (
    <div>
      {/* 筛选Tab */}
      <div className="flex items-center gap-1 mb-3">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${
              filter === f.key
                ? "bg-primary text-primary-foreground shadow-sm"
                : "bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
          >
            {f.emoji} {f.label}
          </button>
        ))}
      </div>

      {/* 信号流（复用现有组件） */}
      <UnifiedSignalFeed
        positionStockCodes={positionStockCodes}
        maxItems={30}
      />
    </div>
  );
}
