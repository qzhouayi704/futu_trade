// 量价预警卡片 — 替代原 5 分钟预警
// 展示吸收/拉升异常检测结果

"use client";

import { useState, useEffect, useCallback } from "react";
import { Card } from "@/components/common";
import apiClient from "@/lib/api/client";

interface VolumePriceAlert {
  detected: boolean;
  alert_type: "absorption" | "rally";
  severity: "high" | "medium";
  stock_code: string;
  stock_name: string;
  start_time: string;
  end_time: string;
  duration_min: number;
  price_change_pct: number;
  cum_net_buy: number;
  start_price: number;
  end_price: number;
  message: string;
}

export function AlertsCard() {
  const [alerts, setAlerts] = useState<VolumePriceAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const loadAlerts = useCallback(async () => {
    try {
      const res = await apiClient.get("/enhanced-heat/volume-price-alerts");
      if (res.success && Array.isArray(res.data)) {
        setAlerts(res.data);
      }
      setLastUpdate(new Date());
    } catch (e) {
      console.error("加载量价预警失败:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  // 初始加载 + 60秒轮询
  useEffect(() => {
    loadAlerts();
    const timer = setInterval(loadAlerts, 60000);
    return () => clearInterval(timer);
  }, [loadAlerts]);

  const fmtAmt = (v: number) => {
    const abs = Math.abs(v);
    if (abs >= 10000) return `${(v / 10000).toFixed(1)}亿`;
    return `${v.toFixed(0)}万`;
  };

  // 分类
  const absorptions = alerts.filter((a) => a.alert_type === "absorption");
  const rallies = alerts.filter((a) => a.alert_type === "rally");
  const total = alerts.length;

  return (
    <Card>
      <div className="p-4 md:p-6">
        {/* 标题 */}
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <span className="text-lg">📡</span>
            量价预警
            {absorptions.length > 0 && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700 font-medium">
                {absorptions.length} 吸收
              </span>
            )}
            {rallies.length > 0 && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 font-medium">
                {rallies.length} 拉升
              </span>
            )}
          </h3>
          <span className="text-xs text-gray-400">
            {lastUpdate ? `${lastUpdate.toLocaleTimeString("zh-CN")} 更新` : ""}
          </span>
        </div>

        {loading ? (
          <div className="text-center py-8 text-gray-400 text-sm">扫描中...</div>
        ) : total === 0 ? (
          <div className="text-center py-8 text-gray-400 text-sm">
            暂无量价异常 — 所有股票走势正常
          </div>
        ) : (
          <div className="space-y-2">
            {alerts
              .sort((a, b) => {
                // 高危优先，然后吸收优先
                if (a.severity !== b.severity) return a.severity === "high" ? -1 : 1;
                if (a.alert_type !== b.alert_type) return a.alert_type === "absorption" ? -1 : 1;
                return b.duration_min - a.duration_min;
              })
              .map((alert, idx) => {
                const isAbsorption = alert.alert_type === "absorption";
                const isHigh = alert.severity === "high";

                const bgColor = isAbsorption
                  ? isHigh ? "bg-red-50 border-red-200" : "bg-orange-50 border-orange-200"
                  : isHigh ? "bg-emerald-50 border-emerald-200" : "bg-blue-50 border-blue-200";

                const textColor = isAbsorption
                  ? isHigh ? "text-red-700" : "text-orange-700"
                  : isHigh ? "text-emerald-700" : "text-blue-700";

                const icon = isAbsorption
                  ? (isHigh ? "🚨" : "⚠️")
                  : (isHigh ? "🚀" : "📈");

                const label = isAbsorption ? "吸收" : "拉升";

                return (
                  <div
                    key={`${alert.stock_code}-${alert.alert_type}-${idx}`}
                    className={`p-3 rounded-lg border ${bgColor} transition-all hover:shadow-md`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <span className={isHigh ? "animate-pulse" : ""}>{icon}</span>
                        <span className={`font-bold text-sm ${textColor}`}>
                          {alert.stock_name}
                        </span>
                        <span className="text-xs text-gray-400">{alert.stock_code}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                          isAbsorption
                            ? (isHigh ? "bg-red-200 text-red-700" : "bg-orange-200 text-orange-700")
                            : (isHigh ? "bg-emerald-200 text-emerald-700" : "bg-blue-200 text-blue-700")
                        }`}>
                          {label} · {isHigh ? "高危" : "注意"}
                        </span>
                      </div>
                      <span className={`text-sm font-bold ${
                        alert.price_change_pct >= 0
                          ? (isAbsorption ? "text-gray-500" : "text-red-600")
                          : "text-emerald-600"
                      }`}>
                        {alert.price_change_pct >= 0 ? "+" : ""}{alert.price_change_pct.toFixed(2)}%
                      </span>
                    </div>
                    <div className={`text-[11px] ${textColor} opacity-80`}>
                      {alert.start_time}~{alert.end_time}
                      {" "}连续{alert.duration_min}分钟
                      {isAbsorption ? "主买" : "量价齐升"}
                      {" "}净买{fmtAmt(alert.cum_net_buy)}
                      {" "}{alert.start_price.toFixed(2)}→{alert.end_price.toFixed(2)}
                    </div>
                    {isAbsorption && (
                      <div className="text-[10px] text-gray-400 mt-0.5">
                        💡 隐性卖单正在吸收买盘，价格被压制
                      </div>
                    )}
                    {!isAbsorption && (
                      <div className="text-[10px] text-gray-400 mt-0.5">
                        💡 资金推动真实上涨，量价配合良好
                      </div>
                    )}
                  </div>
                );
              })}
          </div>
        )}
      </div>
    </Card>
  );
}
