// 全局 WebSocket 信号监听器
// 在任意页面上接收 strategy_signal 事件并弹出 Toast 通知

"use client";

import { useEffect } from "react";
import { useSocket } from "@/lib/socket";
import { useToast } from "@/components/common/Toast";

export function GlobalSignalListener() {
  const { socket } = useSocket();
  const { showToast } = useToast();

  useEffect(() => {
    if (!socket) return;

    const handleSignal = (data: unknown) => {
      const signal = data as Record<string, unknown>;
      if (!signal || !signal.stock_code) return;

      const sigType = String(signal.signal_type).toUpperCase();
      const reason = String(signal.reason || "策略触发");
      const stockInfo = `[${signal.stock_code}] ${signal.stock_name || ""}`;

      // 根据信号类型选择 Toast 样式
      let title: string;
      let type: "error" | "warning" | "info" | "success";

      if (sigType === "SELL") {
        title = "🚨 自动防守触发";
        type = "error";
      } else if (sigType === "ALERT" || sigType === "DANGER") {
        // 吸收预警 / 风险警告
        const isAbsorption = reason.includes("吸收") || reason.includes("压单");
        title = isAbsorption ? "⚠️ 买入吸收预警" : "⚠️ 风险警告";
        type = "warning";
      } else if (sigType === "BUY") {
        // 拉升提醒 / 买入机会
        const isRally = reason.includes("量价齐升") || reason.includes("拉升");
        title = isRally ? "🚀 量价齐升" : "💰 买入机会";
        type = isRally ? "success" : "info";
      } else {
        title = "ℹ️ 交易信号";
        type = "info";
      }

      const msg = `${stockInfo} — ${reason.slice(0, 100)}`;
      showToast(type, title, msg);
    };

    socket.on("strategy_signal", handleSignal);
    return () => {
      socket.off("strategy_signal", handleSignal);
    };
  }, [socket, showToast]);

  return null; // 纯逻辑组件，无UI
}
