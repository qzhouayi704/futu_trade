// 全池异动提醒组件 — 展示盘中快照扫描发现的异动股

"use client";

import { useState, useEffect, useCallback } from "react";
import { useSocket } from "@/lib/socket";

interface AnomalyStock {
  code: string;
  name: string;
  change_rate: number;
  volume_ratio: number;
  turnover_rate: number;
  price: number;
  anomaly_type: "breakout_surge" | "extreme_volume" | "limit_up";
  has_shrinkage: boolean;
  detected_at: string;
  detail: string;
}

const ANOMALY_LABELS: Record<string, { text: string; color: string; icon: string }> = {
  breakout_surge: { text: "放量突破", color: "bg-orange-100 text-orange-700 border-orange-200", icon: "🔥" },
  extreme_volume: { text: "极端放量", color: "bg-red-100 text-red-700 border-red-200", icon: "💥" },
  limit_up: { text: "涨停级", color: "bg-rose-100 text-rose-700 border-rose-200", icon: "🚀" },
};

export default function PoolAnomalyBanner() {
  const { socket } = useSocket();
  const [anomalies, setAnomalies] = useState<AnomalyStock[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const [lastScanTime, setLastScanTime] = useState("");

  // 初始加载
  const fetchAnomalies = useCallback(async () => {
    try {
      const res = await fetch("/api/quick-scan/pool-anomalies");
      const data = await res.json();
      if (data.success && data.data?.length) {
        setAnomalies(data.data);
      }
    } catch {
      // 静默失败
    }
  }, []);

  useEffect(() => {
    fetchAnomalies();
  }, [fetchAnomalies]);

  // WebSocket 实时推送
  useEffect(() => {
    if (!socket) return;

    const handler = (data: { anomalies: AnomalyStock[]; scan_time: string }) => {
      if (data.anomalies?.length) {
        setAnomalies(data.anomalies);
        setLastScanTime(data.scan_time);
        setCollapsed(false); // 有新异动时展开
      }
    };

    socket.on("pool_anomaly", handler);
    return () => { socket.off("pool_anomaly", handler); };
  }, [socket]);

  if (!anomalies.length) return null;

  return (
    <div className="mb-4 rounded-xl border border-orange-200 bg-gradient-to-r from-orange-50 to-amber-50 overflow-hidden shadow-sm">
      {/* 标题栏 */}
      <div
        className="flex items-center justify-between px-4 py-2.5 cursor-pointer hover:bg-orange-100/50 transition-colors"
        onClick={() => setCollapsed(!collapsed)}
      >
        <div className="flex items-center gap-2">
          <span className="text-lg">🔥</span>
          <span className="text-sm font-semibold text-orange-800">
            盘中异动
          </span>
          <span className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-orange-500 text-white text-xs font-bold">
            {anomalies.length}
          </span>
          {lastScanTime && (
            <span className="text-xs text-orange-500">
              {lastScanTime} 更新
            </span>
          )}
        </div>
        <i className={`fas fa-chevron-${collapsed ? "down" : "up"} text-orange-400 text-xs`} />
      </div>

      {/* 异动股列表 */}
      {!collapsed && (
        <div className="px-4 pb-3 flex flex-wrap gap-2">
          {anomalies.map((a) => {
            const label = ANOMALY_LABELS[a.anomaly_type] || ANOMALY_LABELS.breakout_surge;
            return (
              <div
                key={a.code}
                className={`flex items-center gap-2 px-3 py-2 rounded-lg border ${label.color} transition-all hover:scale-[1.02] cursor-pointer`}
                title={a.detail}
              >
                <span className="text-base">{label.icon}</span>
                <div className="flex flex-col">
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm font-semibold">{a.name}</span>
                    <span className="text-xs opacity-70">{a.code.replace("HK.", "")}</span>
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    <span className="font-bold">
                      {a.change_rate >= 0 ? "+" : ""}{a.change_rate.toFixed(1)}%
                    </span>
                    <span>量比 {a.volume_ratio.toFixed(1)}</span>
                    {a.has_shrinkage && (
                      <span className="inline-flex items-center px-1 py-0.5 rounded bg-green-100 text-green-700 text-[10px] font-medium">
                        缩量蓄势✓
                      </span>
                    )}
                  </div>
                </div>
                <span className="text-[10px] px-1.5 py-0.5 rounded border bg-white/50">
                  {label.text}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
