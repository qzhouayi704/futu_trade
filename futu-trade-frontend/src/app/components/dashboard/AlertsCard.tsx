// 量价预警卡片 — 吸收/拉升 + Delta量价背离
// 上部: 吸收/拉升异常检测
// 下部: 5分钟K线量价背离 (跌势量缩/涨势量缩)

"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Card } from "@/components/common";
import apiClient from "@/lib/api/client";

interface VolumePriceAlert {
  detected: boolean;
  alert_type: "absorption" | "rally" | "dump";
  severity: "high" | "medium";
  position?: "high" | "mid" | "low";  // 拉升位置
  position_pct?: number;
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

interface DivergenceAlert {
  stock_code: string;
  stock_name: string;
  start_time: string;
  end_time: string;
  price_change_pct: number;
  vol_ratio: number;
  last_price: number;
  div_type: "bullish" | "bearish";
  label: string;
  hint: string;
  severity: "high" | "medium";
}

export function AlertsCard() {
  const [alerts, setAlerts] = useState<VolumePriceAlert[]>([]);
  const [divAlerts, setDivAlerts] = useState<DivergenceAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const loadAlerts = useCallback(async () => {
    try {
      // 并行加载两种预警
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const [vpRes, divRes]: any[] = await Promise.all([
        apiClient.get("/enhanced-heat/volume-price-alerts"),
        apiClient.get("/enhanced-heat/delta-divergence-alerts"),
      ]);
      if (vpRes.success && Array.isArray(vpRes.data)) setAlerts(vpRes.data);
      if (divRes.success && Array.isArray(divRes.data)) setDivAlerts(divRes.data);
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
  const dumps = alerts.filter((a) => a.alert_type === "dump");
  const bullishDivs = divAlerts.filter((d) => d.div_type === "bullish");
  const bearishDivs = divAlerts.filter((d) => d.div_type === "bearish");

  return (
    <Card>
      <div className="p-4 md:p-5">
        {/* 标题 */}
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-base font-semibold text-gray-900 flex items-center gap-1.5">
            <span className="text-base">📡</span>
            量价预警
            {absorptions.length > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-red-100 text-red-700 font-medium">
                {absorptions.length} 吸收
              </span>
            )}
            {rallies.length > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700 font-medium">
                {rallies.length} 拉升
              </span>
            )}
            {dumps.length > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-purple-100 text-purple-700 font-medium">
                {dumps.length} 放量跌
              </span>
            )}
          </h3>
          <span className="text-[10px] text-gray-400">
            {lastUpdate ? `${lastUpdate.toLocaleTimeString("zh-CN")} 更新` : ""}
          </span>
        </div>

        {loading ? (
          <div className="text-center py-6 text-gray-400 text-sm">扫描中...</div>
        ) : alerts.length === 0 && divAlerts.length === 0 ? (
          <div className="text-center py-6 text-gray-400 text-sm">
            暂无量价异常 — 所有股票走势正常
          </div>
        ) : (
          <div className="space-y-4">
            {/* ===== 吸收/拉升预警 (TOP 5) ===== */}
            {alerts.length > 0 && (
              <div className="space-y-1.5">
                {alerts
                  .sort((a, b) => {
                    if (a.severity !== b.severity) return a.severity === "high" ? -1 : 1;
                    if (a.alert_type !== b.alert_type) return a.alert_type === "absorption" ? -1 : 1;
                    return b.duration_min - a.duration_min;
                  })
                  .slice(0, 5)
                  .map((alert, idx) => {
                    const isAbsorption = alert.alert_type === "absorption";
                    const isDump = alert.alert_type === "dump";
                    const isRally = alert.alert_type === "rally";
                    const isHigh = alert.severity === "high";

                    // 颜色/图标/标签
                    let bgColor: string, textColor: string, icon: string, label: string, severityLabel: string, badgeColor: string;

                    if (isAbsorption) {
                      bgColor = isHigh ? "bg-red-50/80 border-red-200/60" : "bg-orange-50/80 border-orange-200/60";
                      textColor = isHigh ? "text-red-600" : "text-orange-600";
                      badgeColor = isHigh ? "bg-red-200/80 text-red-700" : "bg-orange-200/80 text-orange-700";
                      icon = isHigh ? "🚨" : "⚠️";
                      label = "吸收";
                      severityLabel = isHigh ? "高危" : "注意";
                    } else if (isDump) {
                      bgColor = isHigh ? "bg-purple-50/80 border-purple-200/60" : "bg-pink-50/80 border-pink-200/60";
                      textColor = isHigh ? "text-purple-600" : "text-pink-600";
                      badgeColor = isHigh ? "bg-purple-200/80 text-purple-700" : "bg-pink-200/80 text-pink-700";
                      icon = isHigh ? "💥" : "📉";
                      label = "放量下跌";
                      severityLabel = isHigh ? "高危" : "注意";
                    } else {
                      // rally — 根据位置区分
                      const pos = alert.position;
                      if (pos === "high") {
                        bgColor = "bg-amber-50/80 border-amber-200/60";
                        textColor = "text-amber-600";
                        badgeColor = "bg-amber-200/80 text-amber-700";
                        icon = "⚡";
                        label = "高位拉升";
                        severityLabel = "风险";
                      } else if (pos === "low") {
                        bgColor = isHigh ? "bg-emerald-50/80 border-emerald-200/60" : "bg-teal-50/80 border-teal-200/60";
                        textColor = isHigh ? "text-emerald-600" : "text-teal-600";
                        badgeColor = isHigh ? "bg-emerald-200/80 text-emerald-700" : "bg-teal-200/80 text-teal-700";
                        icon = "🚀";
                        label = "低位拉升";
                        severityLabel = "机会";
                      } else {
                        bgColor = isHigh ? "bg-blue-50/80 border-blue-200/60" : "bg-sky-50/80 border-sky-200/60";
                        textColor = isHigh ? "text-blue-600" : "text-sky-600";
                        badgeColor = isHigh ? "bg-blue-200/80 text-blue-700" : "bg-sky-200/80 text-sky-700";
                        icon = isHigh ? "🚀" : "📈";
                        label = "拉升";
                        severityLabel = isHigh ? "强势" : "关注";
                      }
                    }

                    return (
                      <div
                        key={`${alert.stock_code}-${alert.alert_type}-${idx}`}
                        className={`px-2.5 py-2 rounded-lg border ${bgColor} transition-all hover:shadow-sm`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <span className={`text-xs ${isHigh ? "animate-pulse" : ""}`}>{icon}</span>
                            <span className={`font-bold text-xs ${textColor} truncate`}>
                              {alert.stock_name}
                            </span>
                            <span className="text-[10px] text-gray-400 shrink-0">{alert.stock_code}</span>
                            <span className={`text-[9px] px-1 py-px rounded font-medium shrink-0 ${badgeColor}`}>
                              {label} · {severityLabel}
                            </span>
                          </div>
                          <span className={`text-xs font-bold tabular-nums shrink-0 ml-2 ${
                            alert.price_change_pct >= 0
                              ? (isAbsorption ? "text-gray-500" : "text-red-600")
                              : "text-emerald-600"
                          }`}>
                            {alert.price_change_pct >= 0 ? "+" : ""}{alert.price_change_pct.toFixed(2)}%
                          </span>
                        </div>
                        <div className={`text-[10px] ${textColor} opacity-75 mt-0.5`}>
                          {alert.start_time}~{alert.end_time} 连续{alert.duration_min}分钟
                          {isDump ? "放量卖出" : isAbsorption ? "主买" : "量价齐升"}
                          {" "}{isDump ? `净卖${fmtAmt(Math.abs(alert.cum_net_buy))}` : `净买${fmtAmt(alert.cum_net_buy)}`}
                          {" "}{alert.start_price.toFixed(2)}→{alert.end_price.toFixed(2)}
                          {isRally && alert.position === "high" && (
                            <span className="text-amber-500 ml-1">· 高位警惕出货</span>
                          )}
                          {isRally && alert.position === "low" && (
                            <span className="text-emerald-500 ml-1">· 低位资金进场</span>
                          )}
                          {isDump && (
                            <span className="text-purple-500 ml-1">· 主力出逃，回避</span>
                          )}
                          {isAbsorption && (
                            <span className="text-gray-400 ml-1">· 隐性卖单吸收买盘</span>
                          )}
                        </div>
                      </div>
                    );
                  })}
              </div>
            )}

            {/* ===== 分割线 ===== */}
            {alerts.length > 0 && divAlerts.length > 0 && (
              <div className="border-t border-gray-200/60" />
            )}

            {/* ===== Delta 量价背离 ===== */}
            {divAlerts.length > 0 && (
              <div>
                <div className="flex items-center gap-1.5 mb-2">
                  <span className="text-xs">📊</span>
                  <span className="text-xs font-semibold text-gray-700">Delta量价背离</span>
                  {bullishDivs.length > 0 && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium">
                      {bullishDivs.length} 跌势量缩
                    </span>
                  )}
                  {bearishDivs.length > 0 && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-100 text-violet-700 font-medium">
                      {bearishDivs.length} 涨势量缩
                    </span>
                  )}
                </div>
                <div className="space-y-1.5">
                  {divAlerts.slice(0, 5).map((d, idx) => {
                    const isBullish = d.div_type === "bullish";
                    const isHigh = d.severity === "high";
                    const bgColor = isBullish
                      ? "bg-amber-50/80 border-amber-200/60"
                      : "bg-violet-50/80 border-violet-200/60";
                    const textColor = isBullish ? "text-amber-700" : "text-violet-700";
                    const icon = isBullish ? "📉" : "📈";
                    const volPct = Math.round(d.vol_ratio * 100);

                    return (
                      <div
                        key={`div-${d.stock_code}-${idx}`}
                        className={`px-2.5 py-2 rounded-lg border ${bgColor} transition-all hover:shadow-sm`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <span className="text-xs">{icon}</span>
                            <span className={`font-bold text-xs ${textColor} truncate`}>
                              {d.stock_name}
                            </span>
                            <span className="text-[10px] text-gray-400 shrink-0">{d.stock_code}</span>
                            <span className={`text-[9px] px-1 py-px rounded font-medium shrink-0 ${
                              isBullish
                                ? (isHigh ? "bg-amber-200/80 text-amber-800" : "bg-amber-100 text-amber-600")
                                : (isHigh ? "bg-violet-200/80 text-violet-800" : "bg-violet-100 text-violet-600")
                            }`}>
                              {d.label}{isHigh ? " · 强" : ""}
                            </span>
                            <span className="text-[9px] text-gray-400 shrink-0">
                              量比{volPct}%
                            </span>
                          </div>
                          <span className={`text-xs font-bold tabular-nums shrink-0 ml-2 ${
                            d.price_change_pct >= 0 ? "text-red-600" : "text-emerald-600"
                          }`}>
                            {d.price_change_pct >= 0 ? "+" : ""}{d.price_change_pct.toFixed(2)}%
                          </span>
                        </div>
                        <div className={`text-[10px] ${textColor} opacity-75 mt-0.5`}>
                          {d.start_time}~{d.end_time}
                          <span className="text-gray-400 ml-1">· {d.hint}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* 查看更多 */}
            {(alerts.length > 5 || divAlerts.length > 5) && (
              <Link
                href="/flow-signals"
                className="block text-center py-2 text-xs text-primary hover:text-primary/80 hover:bg-primary/5 rounded-lg transition-colors font-medium"
              >
                查看全部 {alerts.length + divAlerts.length} 条预警 →
              </Link>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
