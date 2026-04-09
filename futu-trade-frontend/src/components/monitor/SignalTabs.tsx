// 信号分组 Tab 展示组件

"use client";

import { useState, useEffect, useCallback } from "react";
import { Card } from "@/components/common";
import { multiStrategyApi } from "@/lib/api";
import { useMonitorStore } from "@/lib/stores";
import { useSocket } from "@/lib/socket";
import type { EnabledStrategy, StrategySignalItem, SignalsByStrategy } from "@/types";

export function SignalTabs() {
  const { socket } = useSocket();
  const { enabledStrategies, signalsByStrategy, setSignalsByStrategy } =
    useMonitorStore();

  const [activeTab, setActiveTab] = useState<string>("all");

  // 加载分组信号
  const loadSignals = useCallback(async () => {
    try {
      const res = await multiStrategyApi.getSignalsByStrategy();
      if (res.success && res.data) {
        setSignalsByStrategy(res.data);
      }
    } catch (err) {
      console.error("加载分组信号失败:", err);
    }
  }, [setSignalsByStrategy]);

  useEffect(() => {
    loadSignals();
  }, [loadSignals]);

  // 监听 WebSocket 信号更新
  useEffect(() => {
    if (!socket) return;

    const handleSignalsUpdate = (data: any) => {
      if (data.signals_by_strategy) {
        setSignalsByStrategy(data.signals_by_strategy);
      } else {
        // 兼容旧格式，重新拉取
        loadSignals();
      }
    };

    socket.on("signals_update", handleSignalsUpdate);
    socket.on("strategy_signal", () => loadSignals());

    return () => {
      socket.off("signals_update", handleSignalsUpdate);
      socket.off("strategy_signal");
    };
  }, [socket, loadSignals, setSignalsByStrategy]);

  // 计算各 Tab 的信号
  const allSignals = Object.values(signalsByStrategy).flat();
  const getTabSignals = (tabId: string): StrategySignalItem[] => {
    if (tabId === "all") return allSignals;
    return signalsByStrategy[tabId] || [];
  };

  const currentSignals = getTabSignals(activeTab);

  // Tab 列表
  const tabs: { id: string; label: string; count: number }[] = [
    { id: "all", label: "全部", count: allSignals.length },
    ...enabledStrategies.map((s) => ({
      id: s.strategy_id,
      label: s.strategy_name,
      count: (signalsByStrategy[s.strategy_id] || []).length,
    })),
  ];

  return (
    <Card>
      <div className="p-6">
        <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2 mb-4">
          <svg className="w-5 h-5 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
          </svg>
          实时信号
        </h3>

        {/* Tab 栏 */}
        <div className="flex gap-1 mb-4 border-b border-gray-200 overflow-x-auto">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-2 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
                activeTab === tab.id
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab.label}
              {tab.count > 0 && (
                <span
                  className={`ml-1.5 px-1.5 py-0.5 rounded-full text-xs ${
                    activeTab === tab.id
                      ? "bg-blue-100 text-blue-700"
                      : "bg-gray-100 text-gray-600"
                  }`}
                >
                  {tab.count}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* 信号列表 */}
        {currentSignals.length === 0 ? (
          <div className="text-center py-8 text-gray-500">暂无信号</div>
        ) : (
          <div className="space-y-3 max-h-96 overflow-y-auto">
            {currentSignals.map((signal, idx) => (
              <SignalItem
                key={`${signal.stock_code}-${signal.timestamp}-${idx}`}
                signal={signal}
                showStrategy={activeTab === "all"}
              />
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

// 单条信号展示
function SignalItem({
  signal,
  showStrategy,
}: {
  signal: StrategySignalItem;
  showStrategy: boolean;
}) {
  const isBuy = signal.signal_type === "BUY";

  return (
    <div className="p-3 rounded-lg border border-gray-200 hover:border-blue-300 hover:bg-blue-50/30 transition-colors">
      <div className="flex items-start justify-between mb-1.5">
        <div className="flex items-center gap-2">
          <span
            className={`px-2 py-0.5 rounded text-xs font-medium ${
              isBuy ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"
            }`}
          >
            {isBuy ? "买入" : "卖出"}
          </span>
          <span className="font-medium text-gray-900">{signal.stock_name}</span>
          <span className="text-xs text-gray-500">{signal.stock_code}</span>
        </div>
        <span className="font-medium text-gray-900">
          ¥{signal.price.toFixed(2)}
        </span>
      </div>

      {showStrategy && (
        <div className="text-xs text-blue-600 mb-1">
          {signal.strategy_name} · {signal.preset_name}
        </div>
      )}

      {signal.reason && (
        <p className="text-xs text-gray-500 line-clamp-2">{signal.reason}</p>
      )}

      <div className="text-xs text-gray-400 mt-1">
        {new Date(signal.timestamp).toLocaleTimeString("zh-CN", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })}
      </div>
    </div>
  );
}
