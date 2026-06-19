// 驾驶舱顶部状态条 — 系统连接状态 + 核心指标

"use client";

import { useEffect, useState } from "react";
import { useSocket } from "@/lib/socket";
import { systemApi } from "@/lib/api";

interface StatusBarProps {
  onStartMonitor: () => void;
  onStopMonitor: () => void;
}

export function StatusBar({ onStartMonitor }: StatusBarProps) {
  const { isConnected } = useSocket();
  const [status, setStatus] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const [sRes, hRes] = await Promise.all([
          systemApi.getStatus(),
          systemApi.getMonitorHealth(),
        ]);
        if (sRes?.success) setStatus(sRes.data);
        if (hRes?.success && hRes.data) {
          setStats({
            subscribed_count: hRes.data.subscription?.subscribed_count ?? 0,
            stock_pool_count: hRes.data.stock_pool?.total_count ?? 0,
          });
        }
      } catch {}
    };
    load();
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, []);

  // 后端字段为 is_running / monitor_status（之前误读 is_monitoring 导致永远显示"未启动"）
  const isRunning = status?.is_running ?? status?.monitor_status === "running";
  const uptime = status?.uptime_seconds
    ? `${Math.floor(status.uptime_seconds / 3600)}h${Math.floor((status.uptime_seconds % 3600) / 60)}m`
    : "--";

  return (
    <div className="flex items-center justify-between px-4 py-2.5 bg-card/80 backdrop-blur-sm border border-border rounded-xl">
      {/* 左侧：连接 + 监控状态 */}
      <div className="flex items-center gap-4">
        {/* WebSocket */}
        <div className="flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full ${isConnected ? "bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.6)]" : "bg-red-500"}`} />
          <span className="text-xs text-muted-foreground">
            {isConnected ? "已连接" : "断开"}
          </span>
        </div>

        {/* 监控状态 */}
        <div className="flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full ${isRunning ? "bg-emerald-500 animate-pulse" : "bg-zinc-500"}`} />
          <span className="text-xs text-muted-foreground">
            {isRunning ? `监控中 ${uptime}` : "未启动"}
          </span>
        </div>

        {/* 监控由后端每次启动自动开启；仅在确实停止时显示"启动"作为恢复入口 */}
        {!isRunning && (
          <button
            onClick={onStartMonitor}
            className="px-3 py-1 text-xs font-medium rounded-lg transition-all bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 border border-emerald-500/20"
          >
            启动
          </button>
        )}
      </div>

      {/* 右侧：核心数据指标 */}
      <div className="flex items-center gap-5">
        {stats && (
          <>
            <Metric label="订阅" value={stats.subscribed_count ?? 0} />
            <Metric label="股票池" value={stats.stock_pool_count ?? 0} />
          </>
        )}
        <span className="text-[10px] text-muted-foreground/50">
          {new Date().toLocaleDateString("zh-CN", { weekday: "short" })}
        </span>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="text-center">
      <div className="text-sm font-semibold text-foreground tabular-nums">{value}</div>
      <div className="text-[10px] text-muted-foreground">{label}</div>
    </div>
  );
}
