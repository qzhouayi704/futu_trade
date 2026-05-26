// 板块预警卡片 — 板块大涨/大跌/齐涨齐跌/热度背离

"use client";

import { useState, useEffect, useCallback } from "react";
import { Card } from "@/components/common";
import Link from "next/link";
import apiClient from "@/lib/api/client";

interface PlateAlert {
  plate_code: string;
  plate_name: string;
  alert_type: "surge" | "plunge" | "concentration" | "divergence";
  severity: "high" | "medium";
  avg_change_pct: number;
  up_ratio: number;
  heat_score: number;
  stock_count: number;
  hot_stock_count: number;
  leader: string;
  message: string;
  direction?: "up" | "down";
  concentration_pct?: number;
  top_stock_name?: string;
  top_stock_change?: number;
  bot_stock_name?: string;
  bot_stock_change?: number;
}

export function PlateAlertsCard() {
  const [alerts, setAlerts] = useState<PlateAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const loadAlerts = useCallback(async () => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await apiClient.get("/enhanced-heat/plate-alerts");
      if (res.success && Array.isArray(res.data)) {
        setAlerts(res.data);
      }
      setLastUpdate(new Date());
    } catch (e) {
      console.error("加载板块预警失败:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAlerts();
    const timer = setInterval(loadAlerts, 120000); // 2分钟刷新
    return () => clearInterval(timer);
  }, [loadAlerts]);

  // 分类统计
  const surgeCount = alerts.filter((a) => a.alert_type === "surge").length;
  const plungeCount = alerts.filter((a) => a.alert_type === "plunge").length;
  const concCount = alerts.filter((a) => a.alert_type === "concentration").length;
  const divCount = alerts.filter((a) => a.alert_type === "divergence").length;

  return (
    <Card>
      <div className="p-4 md:p-5">
        {/* 标题 */}
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold text-gray-900 flex items-center gap-1.5 flex-wrap">
            <span className="text-base">🏷️</span>
            板块预警
            {surgeCount > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-red-100 text-red-700 font-medium">
                {surgeCount} 大涨
              </span>
            )}
            {plungeCount > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700 font-medium">
                {plungeCount} 大跌
              </span>
            )}
            {concCount > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-700 font-medium">
                {concCount} 集中
              </span>
            )}
            {divCount > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium">
                {divCount} 异动
              </span>
            )}
          </h3>
          <span className="text-[10px] text-gray-400 shrink-0">
            {lastUpdate ? `${lastUpdate.toLocaleTimeString("zh-CN")} 更新` : ""}
          </span>
        </div>

        {loading ? (
          <div className="text-center py-6 text-gray-400 text-sm">扫描板块中...</div>
        ) : alerts.length === 0 ? (
          <div className="text-center py-6 text-gray-400 text-sm">
            暂无板块异动 — 各板块表现平稳
          </div>
        ) : (
          <div className="space-y-1.5">
            {alerts.map((alert, idx) => {
              const isSurge = alert.alert_type === "surge";
              const isPlunge = alert.alert_type === "plunge";
              const isConc = alert.alert_type === "concentration";
              const isDiv = alert.alert_type === "divergence";
              const isHigh = alert.severity === "high";

              // 颜色/图标
              let bgColor: string, textColor: string, icon: string, label: string, badgeColor: string;

              if (isSurge) {
                bgColor = isHigh ? "bg-red-50/80 border-red-200/60" : "bg-orange-50/80 border-orange-200/60";
                textColor = isHigh ? "text-red-600" : "text-orange-600";
                badgeColor = isHigh ? "bg-red-200/80 text-red-700" : "bg-orange-200/80 text-orange-700";
                icon = isHigh ? "🔥" : "📈";
                label = isHigh ? "板块暴涨" : "板块大涨";
              } else if (isPlunge) {
                bgColor = isHigh ? "bg-emerald-50/80 border-emerald-200/60" : "bg-teal-50/80 border-teal-200/60";
                textColor = isHigh ? "text-emerald-700" : "text-teal-600";
                badgeColor = isHigh ? "bg-emerald-200/80 text-emerald-700" : "bg-teal-200/80 text-teal-700";
                icon = isHigh ? "💥" : "📉";
                label = isHigh ? "板块暴跌" : "板块大跌";
              } else if (isConc) {
                const isUp = alert.direction === "up";
                bgColor = isUp ? "bg-blue-50/80 border-blue-200/60" : "bg-violet-50/80 border-violet-200/60";
                textColor = isUp ? "text-blue-600" : "text-violet-600";
                badgeColor = isUp ? "bg-blue-200/80 text-blue-700" : "bg-violet-200/80 text-violet-700";
                icon = isUp ? "⬆️" : "⬇️";
                label = isUp ? "齐涨" : "齐跌";
              } else {
                bgColor = "bg-amber-50/80 border-amber-200/60";
                textColor = "text-amber-600";
                badgeColor = "bg-amber-200/80 text-amber-700";
                icon = "⚡";
                label = "热度背离";
              }

              return (
                <Link
                  key={`${alert.plate_code}-${alert.alert_type}-${idx}`}
                  href={`/plate/${alert.plate_code}`}
                  className={`block px-2.5 py-2 rounded-lg border ${bgColor} transition-all hover:shadow-sm`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className={`text-xs ${isHigh ? "animate-pulse" : ""}`}>{icon}</span>
                      <span className={`font-bold text-xs ${textColor} truncate`}>
                        {alert.plate_name}
                      </span>
                      <span className={`text-[9px] px-1 py-px rounded font-medium shrink-0 ${badgeColor}`}>
                        {label}
                      </span>
                      <span className="text-[9px] text-gray-400 shrink-0">
                        {alert.stock_count}只
                      </span>
                    </div>
                    <span className={`text-xs font-bold tabular-nums shrink-0 ml-2 ${
                      alert.avg_change_pct >= 0 ? "text-red-600" : "text-emerald-600"
                    }`}>
                      {alert.avg_change_pct >= 0 ? "+" : ""}{alert.avg_change_pct.toFixed(2)}%
                    </span>
                  </div>
                  <div className={`text-[10px] ${textColor} opacity-75 mt-0.5`}>
                    {alert.message}
                    {isSurge && alert.heat_score > 0 && (
                      <span className="text-gray-400 ml-1">· 热度{alert.heat_score.toFixed(0)}</span>
                    )}
                    {isDiv && (
                      <span className="text-amber-500 ml-1">· 警惕板块轮动</span>
                    )}
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </Card>
  );
}
