// 持仓健康度仪表盘

"use client";

import type { PositionHealth, HealthLevel } from "@/types/advisor";

const HEALTH_COLORS: Record<HealthLevel, { bg: string; text: string; ring: string }> = {
  STRONG: { bg: "bg-green-50", text: "text-green-700", ring: "text-green-500" },
  NEUTRAL: { bg: "bg-blue-50", text: "text-blue-700", ring: "text-blue-500" },
  WEAK: { bg: "bg-yellow-50", text: "text-yellow-700", ring: "text-yellow-500" },
  DANGER: { bg: "bg-red-50", text: "text-red-700", ring: "text-red-500" },
};

const HEALTH_LABELS: Record<HealthLevel, string> = {
  STRONG: "强势",
  NEUTRAL: "中性",
  WEAK: "弱势",
  DANGER: "危险",
};

const TREND_ICONS: Record<string, { icon: string; color: string }> = {
  UP: { icon: "↑", color: "text-red-500" },
  DOWN: { icon: "↓", color: "text-green-500" },
  SIDEWAYS: { icon: "→", color: "text-gray-500" },
};

interface HealthDashboardProps {
  healthList: PositionHealth[];
}

export function HealthDashboard({ healthList }: HealthDashboardProps) {
  if (healthList.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
        暂无持仓数据
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {healthList.map((h) => (
        <HealthCard key={h.stock_code} health={h} />
      ))}
    </div>
  );
}

function HealthCard({ health }: { health: PositionHealth }) {
  const colors = HEALTH_COLORS[health.health_level];
  const trend = TREND_ICONS[health.trend] || TREND_ICONS.SIDEWAYS;

  // 环形进度条参数
  const radius = 28;
  const circumference = 2 * Math.PI * radius;
  const progress = (health.score / 100) * circumference;

  return (
    <div className={`p-3 rounded-lg border ${colors.bg} border-gray-200`}>
      <div className="flex items-center gap-3">
        {/* 健康度环形图 */}
        <div className="relative w-16 h-16 shrink-0">
          <svg className="w-16 h-16 -rotate-90" viewBox="0 0 64 64">
            <circle cx="32" cy="32" r={radius} fill="none"
              stroke="currentColor" strokeWidth="4"
              className="text-gray-200" />
            <circle cx="32" cy="32" r={radius} fill="none"
              stroke="currentColor" strokeWidth="4"
              strokeDasharray={circumference}
              strokeDashoffset={circumference - progress}
              strokeLinecap="round"
              className={colors.ring} />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className={`text-sm font-bold ${colors.text}`}>
              {Math.round(health.score)}
            </span>
          </div>
        </div>

        {/* 股票信息 */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="font-medium text-sm truncate">{health.stock_name}</span>
            <span className={`text-sm font-bold ${trend.color}`}>{trend.icon}</span>
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className={`text-xs px-1.5 py-0.5 rounded ${colors.bg} ${colors.text} font-medium`}>
              {HEALTH_LABELS[health.health_level]}
            </span>
            <span className={`text-xs ${health.profit_pct >= 0 ? "text-red-500" : "text-green-500"}`}>
              {health.profit_pct >= 0 ? "+" : ""}{health.profit_pct.toFixed(1)}%
            </span>
          </div>
          <div className="flex gap-3 mt-1 text-xs text-gray-500">
            <span>换手 {health.turnover_rate.toFixed(1)}%</span>
            <span>量比 {health.volume_ratio.toFixed(1)}</span>
          </div>
        </div>
      </div>

      {/* 评估理由 */}
      {health.reasons.length > 0 && (
        <div className="mt-2 pt-2 border-t border-gray-200/50">
          <p className="text-xs text-gray-500 line-clamp-2">
            {health.reasons.join("；")}
          </p>
        </div>
      )}
    </div>
  );
}
