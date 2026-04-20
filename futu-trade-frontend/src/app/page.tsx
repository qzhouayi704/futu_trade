// Dashboard 首页

"use client";

import { useState, useEffect } from "react";
import { useSocket } from "@/lib/socket";
import { systemApi, quoteApi } from "@/lib/api";
import { alertApi } from "@/lib/api/alert";
import { useToast } from "@/components/common/Toast";
import { MonitorStartModal, StrategyPanel, SignalTabs } from "@/components/monitor";
import {
  SystemStatusCard,
  StatsGrid,
  PlateHeatCard,
  HotStocksCard,
  HighTurnoverCard,
  SignalsCard,
  PositionsCard,
} from "./components/dashboard";
import { AlertsCard } from "./components/dashboard/AlertsCard";
import {
  useSystemStatus,
  useStats,
  usePlateStrength,
  useHotStocks,
  usePositions,
  useHighTurnoverStocks,
} from "./hooks/useDashboard";
import type { QuoteData } from "@/types/socket";
import type { Alert } from "@/types/alert";

/** 预警保留时长（毫秒），超过后自动清理 */
const ALERT_RETENTION_MS = 10 * 60 * 1000; // 10分钟
/** 最多保留的预警条数 */
const MAX_ALERTS = 20;

/**
 * 合并新预警到已有列表：去重 + 过期清理 + 数量限制
 * 去重键: stock_code + type
 * 同一只股票同类型预警只保留最新的
 */
function mergeAlerts(existing: Alert[], incoming: Alert[]): Alert[] {
  const now = Date.now();
  const cutoff = now - ALERT_RETENTION_MS;

  // 用 map 做去重，同 stock_code+type 保留最新
  const alertMap = new Map<string, Alert>();

  // 先放旧的（过滤掉过期的）
  for (const alert of existing) {
    if (new Date(alert.timestamp).getTime() >= cutoff) {
      const key = `${alert.stock_code}:${alert.type}`;
      alertMap.set(key, alert);
    }
  }

  // 再放新的（会覆盖同 key 的旧预警）
  for (const alert of incoming) {
    const key = `${alert.stock_code}:${alert.type}`;
    alertMap.set(key, alert);
  }

  // 按时间倒序，截取最多 MAX_ALERTS 条
  return [...alertMap.values()]
    .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
    .slice(0, MAX_ALERTS);
}

export default function Dashboard() {
  const { socket, isConnected } = useSocket();
  const { showToast } = useToast();

  // 使用 React Query hooks
  const { data: systemStatus, refetch: refetchSystemStatus } = useSystemStatus();
  const { data: stats } = useStats();
  const { data: plates = [], isLoading: platesLoading } = usePlateStrength();
  const { data: hotStocks = [], isLoading: hotStocksLoading, refetch: refetchHotStocks } = useHotStocks(5);
  const { data: highTurnoverStocks = [], isLoading: highTurnoverLoading } = useHighTurnoverStocks(5);
  const { data: positions = [], isLoading: positionsLoading, refetch: refetchPositions } = usePositions();

  // 启动监控 Modal
  const [startModalOpen, setStartModalOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  // 预警信号状态
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [alertsLoading, setAlertsLoading] = useState(false);

  // 交易信号状态
  const [tradeSignals, setTradeSignals] = useState<any[]>([]);
  const [signalsLoading, setSignalsLoading] = useState(false);

  // 最后更新时间
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  // 启动监控
  const handleStartMonitor = () => {
    setStartModalOpen(true);
  };

  // 启动监控成功回调
  const handleStartSuccess = async () => {
    showToast("success", "成功", "监控已启动");
    await refetchSystemStatus();
  };

  // 停止监控
  const handleStopMonitor = async () => {
    setLoading(true);
    try {
      const response = await systemApi.stopMonitor();
      if (response.success) {
        showToast("success", "成功", "监控已停止");
        await refetchSystemStatus();
      } else {
        showToast("error", "错误", response.message || "停止失败");
      }
    } catch (error) {
      showToast("error", "错误", "停止监控失败");
    } finally {
      setLoading(false);
    }
  };

  // 加载交易信号
  const loadTradeSignals = async () => {
    setSignalsLoading(true);
    try {
      const response = await quoteApi.getTradeSignals();
      if (response.success && response.data) {
        setTradeSignals(response.data as any[]);
      }
    } catch (error) {
      console.error("加载交易信号失败:", error);
    } finally {
      setSignalsLoading(false);
    }
  };

  // 刷新所有数据
  const handleRefreshAll = () => {
    setLastUpdate(new Date());
    refetchSystemStatus();
    refetchHotStocks();
    refetchPositions();
    loadAlerts();
    loadTradeSignals();
  };

  // 加载预警数据（合并模式，不覆盖已有预警）
  const loadAlerts = async () => {
    setAlertsLoading(true);
    try {
      const response = await alertApi.getAlerts();
      if (response.success && response.data?.length > 0) {
        setAlerts(prev => mergeAlerts(prev, response.data));
      }
    } catch (error) {
      console.error("加载预警失败:", error);
    } finally {
      setAlertsLoading(false);
    }
  };

  // 初始加载
  useEffect(() => {
    setLastUpdate(new Date());
    loadAlerts();
    loadTradeSignals();
  }, []);

  // WebSocket 实时更新（优化版）
  useEffect(() => {
    if (!socket) return;

    // 防抖定时器
    let positionsUpdateTimer: NodeJS.Timeout | null = null;

    // 报价更新 - 累积预警信息 + 交易信号
    socket.on("quotes_update", (data: { quotes: QuoteData[]; alerts?: Alert[]; trade_actions?: any[] }) => {
      if (data.alerts && Array.isArray(data.alerts) && data.alerts.length > 0) {
        setAlerts(prev => mergeAlerts(prev, data.alerts!));
      }
      // 有新的交易信号时追加
      if (data.trade_actions && Array.isArray(data.trade_actions) && data.trade_actions.length > 0) {
        setTradeSignals(prev => {
          const newSignals = data.trade_actions!.map((a: any, idx: number) => ({
            id: Date.now() + idx,
            stock_code: a.stock_code,
            stock_name: a.stock_name,
            signal_type: a.signal_type,
            signal_price: a.price,
            created_at: a.timestamp,
            is_executed: false,
            reason: a.reason,
          }));
          // 合并并去重（同 stock_code + signal_type 保留最新），最多保留 30 条
          const merged = [...newSignals, ...prev];
          const seen = new Set<string>();
          const deduped = merged.filter(s => {
            const key = `${s.stock_code}:${s.signal_type}`;
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
          });
          return deduped.slice(0, 30);
        });
      }
    });

    // 持仓更新（防抖处理，避免频繁请求）
    socket.on("positions_update", () => {
      // 清除之前的定时器
      if (positionsUpdateTimer) {
        clearTimeout(positionsUpdateTimer);
      }
      // 设置新的定时器，2秒后执行
      positionsUpdateTimer = setTimeout(() => {
        refetchPositions();
      }, 2000);
    });

    // 系统状态变化
    socket.on("system_status", () => {
      refetchSystemStatus();
    });

    return () => {
      socket.off("quotes_update");
      socket.off("positions_update");
      socket.off("system_status");
      // 清理定时器
      if (positionsUpdateTimer) {
        clearTimeout(positionsUpdateTimer);
      }
    };
  }, [socket, refetchPositions, refetchSystemStatus]);

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      {/* 启动监控 Modal */}
      <MonitorStartModal
        isOpen={startModalOpen}
        onClose={() => setStartModalOpen(false)}
        onSuccess={handleStartSuccess}
      />

      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <svg className="w-6 h-6 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
          系统概览
        </h1>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-500">
            最后更新: {lastUpdate ? lastUpdate.toLocaleTimeString("zh-CN") : "--:--:--"}
          </span>
          <button
            onClick={handleRefreshAll}
            className="px-3 py-1 text-sm text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded-lg transition-colors flex items-center gap-1"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            刷新
          </button>
        </div>
      </div>

      {/* 系统状态 + 核心指标 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        <SystemStatusCard
          status={systemStatus ?? null}
          isConnected={isConnected}
          onStartMonitor={handleStartMonitor}
          onStopMonitor={handleStopMonitor}
          loading={loading}
        />
        <StatsGrid stats={stats ?? null} className="lg:col-span-2" />
      </div>

      {/* 策略面板 */}
      <div className="mb-6">
        <StrategyPanel />
      </div>

      {/* 5分钟预警 */}
      <div className="mb-6">
        <AlertsCard alerts={alerts} loading={alertsLoading} />
      </div>

      {/* 板块热度 + 热门股票 + 活跃个股 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <PlateHeatCard plates={plates} loading={platesLoading} />
        <HotStocksCard stocks={hotStocks} loading={hotStocksLoading} />
      </div>

      {/* 活跃个股 */}
      <div className="mb-6">
        <HighTurnoverCard stocks={highTurnoverStocks} loading={highTurnoverLoading} />
      </div>

      {/* 交易信号 */}
      <div className="mb-6">
        <SignalsCard signals={tradeSignals} loading={signalsLoading} />
      </div>

      {/* 信号分组 + 持仓摘要 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SignalTabs />
        <PositionsCard positions={positions} loading={positionsLoading} />
      </div>
    </div>
  );
}
