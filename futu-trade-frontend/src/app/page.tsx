// Dashboard 首页 — "战斗站"布局
// 双列结构：左=信号流 | 右=持仓+资金流
// 下方：推荐操作 + 可折叠市场概览

"use client";

import { useState, useEffect } from "react";
import { useSocket } from "@/lib/socket";
import { systemApi, quoteApi } from "@/lib/api";
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
  PlateAlertsCard,
  SignalPipelineCard,
  SimulatedTradeCard,
  PositionFlowCard,
  OvernightScreenCard,
  UnifiedSignalFeed,
} from "./components/dashboard";
import { AlertsCard } from "./components/dashboard/AlertsCard";
import {
  useSystemStatus,
  useStats,
  usePlateStrength,
  useHotStocks,
  usePositions,
  useHighTurnoverStocks,
  usePositionsCapitalFlow,
} from "./hooks/useDashboard";
import type { QuoteData } from "@/types/socket";

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
  const { data: positionsCapitalFlow = [], isLoading: positionsCapitalFlowLoading, refetch: refetchPositionsCapitalFlow } = usePositionsCapitalFlow();

  // 启动监控 Modal
  const [startModalOpen, setStartModalOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  // 交易信号状态
  const [tradeSignals, setTradeSignals] = useState<any[]>([]);
  const [signalsLoading, setSignalsLoading] = useState(false);

  // 最后更新时间
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  // 市场概览折叠状态
  const [marketOverviewOpen, setMarketOverviewOpen] = useState(false);

  // 持仓股票代码列表（传给 UnifiedSignalFeed 用于优先排序）
  const positionStockCodes = positions.map((p: any) => p.stock_code);

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
    refetchPositionsCapitalFlow();
    loadTradeSignals();
  };

  // 初始加载
  useEffect(() => {
    setLastUpdate(new Date());
    loadTradeSignals();
  }, []);

  // WebSocket 实时更新（优化版）
  useEffect(() => {
    if (!socket) return;

    // 防抖定时器
    let positionsUpdateTimer: NodeJS.Timeout | null = null;

    // 报价更新 - 交易信号（命名函数，供 off 精确移除）
    const handleQuotesUpdate = (data: { quotes: QuoteData[]; trade_actions?: any[] }) => {
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
            risk_notes: a.risk_notes || null,
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
    };

    // 持仓更新（防抖处理，避免频繁请求）
    const handlePositionsUpdate = () => {
      if (positionsUpdateTimer) {
        clearTimeout(positionsUpdateTimer);
      }
      positionsUpdateTimer = setTimeout(() => {
        refetchPositions();
        refetchPositionsCapitalFlow();
      }, 2000);
    };

    // 系统状态变化
    const handleSystemStatus = () => {
      refetchSystemStatus();
    };

    socket.on("quotes_update", handleQuotesUpdate);
    socket.on("positions_update", handlePositionsUpdate);
    socket.on("system_status", handleSystemStatus);

    return () => {
      socket.off("quotes_update", handleQuotesUpdate);
      socket.off("positions_update", handlePositionsUpdate);
      socket.off("system_status", handleSystemStatus);
      // 清理定时器
      if (positionsUpdateTimer) {
        clearTimeout(positionsUpdateTimer);
      }
    };
  }, [socket, refetchPositions, refetchPositionsCapitalFlow, refetchSystemStatus]);


  return (
    <div className="container mx-auto px-3 md:px-4 py-4 md:py-6 max-w-[1600px]">
      {/* 启动监控 Modal */}
      <MonitorStartModal
        isOpen={startModalOpen}
        onClose={() => setStartModalOpen(false)}
        onSuccess={handleStartSuccess}
      />

      {/* ═══ 顶栏：系统状态 + 核心指标 ═══ */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 md:gap-6 mb-4 md:mb-6">
        <SystemStatusCard
          status={systemStatus ?? null}
          isConnected={isConnected}
          onStartMonitor={handleStartMonitor}
          onStopMonitor={handleStopMonitor}
          loading={loading}
        />
        <StatsGrid stats={stats ?? null} positionCount={positions.length} className="lg:col-span-2" />
      </div>

      {/* ═══ 策略面板 ═══ */}
      <div className="mb-4 md:mb-6">
        <StrategyPanel />
      </div>

      {/* ═══ 核心区域：双列布局 ═══ */}
      {/* 左列=信号流 | 右列=持仓+资金流 */}
      <div className="grid grid-cols-1 xl:grid-cols-5 gap-4 md:gap-6 mb-4 md:mb-6">
        {/* 左列：统一信号流 (3/5 宽度) */}
        <div className="xl:col-span-3 space-y-4 md:space-y-6">
          <UnifiedSignalFeed
            positionStockCodes={positionStockCodes}
            maxItems={25}
          />
        </div>

        {/* 右列：持仓 + 资金流 (2/5 宽度) */}
        <div className="xl:col-span-2 space-y-4 md:space-y-6">
          <PositionsCard positions={positions} loading={positionsLoading} />
          <PositionFlowCard data={positionsCapitalFlow} loading={positionsCapitalFlowLoading} />
        </div>
      </div>

      {/* ═══ 推荐操作区：盘后优选 ═══ */}
      <div className="mb-4 md:mb-6">
        <OvernightScreenCard />
      </div>

      {/* ═══ 市场概览（可折叠） ═══ */}
      <div className="mb-4 md:mb-6">
        <button
          onClick={() => setMarketOverviewOpen(!marketOverviewOpen)}
          className="w-full flex items-center justify-between px-4 py-3 bg-card border border-border rounded-xl hover:bg-accent/30 transition-colors"
        >
          <span className="text-sm font-semibold text-foreground flex items-center gap-2">
            📊 市场概览
            <span className="text-xs font-normal text-muted-foreground">
              板块热度 · 热门股 · 活跃个股 · 模拟交易 · 预警
            </span>
          </span>
          <svg
            className={`w-4 h-4 text-muted-foreground transition-transform duration-200 ${marketOverviewOpen ? "rotate-180" : ""}`}
            fill="none" viewBox="0 0 24 24" stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        {marketOverviewOpen && (
          <div className="mt-4 space-y-4 md:space-y-6 animate-in slide-in-from-top-2 duration-200">
            {/* 盘中狙击 + 量价预警（原始详情版） */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-6">
              <AlertsCard />
              <PlateAlertsCard />
            </div>

            {/* 板块热度 + 热门股票 */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-6">
              <PlateHeatCard plates={plates} loading={platesLoading} />
              <HotStocksCard stocks={hotStocks} loading={hotStocksLoading} />
            </div>

            {/* 活跃个股 */}
            <HighTurnoverCard stocks={highTurnoverStocks} loading={highTurnoverLoading} />

            {/* 交易信号追踪 */}
            <SignalPipelineCard />

            {/* 模拟交易记录 */}
            <SimulatedTradeCard />

            {/* 交易信号 */}
            <SignalsCard signals={tradeSignals} loading={signalsLoading} />

            {/* 信号分组 */}
            <SignalTabs />
          </div>
        )}
      </div>
    </div>
  );
}
