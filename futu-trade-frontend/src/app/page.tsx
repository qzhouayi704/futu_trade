// 驾驶舱 — 盘中单屏作战视图
// 左列=信号流 | 右列=持仓+Sniper止盈 | 底部=决策日志

"use client";

import { useState, useEffect, useMemo } from "react";
import { useSocket } from "@/lib/socket";
import { systemApi } from "@/lib/api";
import { useToast } from "@/components/common/Toast";
import { MonitorStartModal, StrategyPanel } from "@/components/monitor";
import { StatusBar, SignalFeed, PositionPanel, DecisionLog, SignalRankingPanel, DailyPickCard, MultiSignalDashboard } from "@/components/cockpit";
import { usePositions } from "./hooks/useDashboard";
import { useSignalPipeline } from "@/lib/hooks/useSignalPipeline";
import type { QuoteData } from "@/types/socket";

export default function CockpitPage() {
  const { socket, isConnected } = useSocket();
  const { showToast } = useToast();

  // 持仓数据
  const { data: positions = [], isLoading: positionsLoading, refetch: refetchPositions } = usePositions();
  const { records: pipelineRecords } = useSignalPipeline({
    limit: 50,
    includeRejected: true,
    pollMs: 30000,
  });

  // 实时价格
  const [realtimePrices, setRealtimePrices] = useState<Record<string, number>>({});

  // 启动监控 Modal
  const [startModalOpen, setStartModalOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [selectedStockCode, setSelectedStockCode] = useState<string | null>(null);

  // 持仓股票代码
  const positionStockCodes = useMemo(
    () => positions.map((p: any) => p.stock_code),
    [positions]
  );

  // 启动监控
  const handleStartMonitor = () => setStartModalOpen(true);
  const handleStartSuccess = async () => {
    showToast("success", "成功", "监控已启动");
  };

  // 停止监控
  const handleStopMonitor = async () => {
    setLoading(true);
    try {
      const response = await systemApi.stopMonitor();
      if (response.success) {
        showToast("success", "成功", "监控已停止");
      } else {
        showToast("error", "错误", response.message || "停止失败");
      }
    } catch {
      showToast("error", "错误", "停止监控失败");
    } finally {
      setLoading(false);
    }
  };

  // WebSocket 实时价格 + 持仓刷新
  useEffect(() => {
    if (!socket) return;

    let posTimer: NodeJS.Timeout | null = null;

    const handleQuotes = (data: { quotes: QuoteData[] }) => {
      if (data.quotes?.length > 0) {
        setRealtimePrices((prev) => {
          const next = { ...prev };
          let changed = false;
          for (const q of data.quotes) {
            const code = q.stock_code || q.code;
            const price = q.current_price || q.last_price;
            if (code && price && price > 0 && prev[code] !== price) {
              next[code] = price;
              changed = true;
            }
          }
          return changed ? next : prev;
        });
      }
    };

    const handlePositionsUpdate = () => {
      if (posTimer) clearTimeout(posTimer);
      posTimer = setTimeout(() => refetchPositions(), 2000);
    };

    socket.on("quotes_update", handleQuotes);
    socket.on("positions_update", handlePositionsUpdate);

    return () => {
      socket.off("quotes_update", handleQuotes);
      socket.off("positions_update", handlePositionsUpdate);
      if (posTimer) clearTimeout(posTimer);
    };
  }, [socket, refetchPositions]);

  return (
    <div className="container mx-auto px-3 md:px-4 py-4 md:py-6 max-w-[1600px]">
      {/* 启动监控 Modal */}
      <MonitorStartModal
        isOpen={startModalOpen}
        onClose={() => setStartModalOpen(false)}
        onSuccess={handleStartSuccess}
      />

      {/* ═══ 顶部状态条 ═══ */}
      <div className="mb-4 md:mb-5">
        <StatusBar
          onStartMonitor={handleStartMonitor}
          onStopMonitor={handleStopMonitor}
        />
      </div>

      {/* ═══ 策略面板 ═══ */}
      <div className="mb-4 md:mb-5">
        <StrategyPanel />
      </div>

      {/* ═══ 信号强度 TOP 5 排名 ═══ */}
      <div className="mb-4 md:mb-5">
        <SignalRankingPanel />
      </div>

      {/* ═══ 今日可买精选(手动交易用) ═══ */}
      <div className="mb-4 md:mb-5">
        <DailyPickCard onSelectStock={setSelectedStockCode} />
      </div>

      {/* ═══ 核心区域：双列布局 ═══ */}
      <div className="grid grid-cols-1 xl:grid-cols-5 gap-4 md:gap-5 mb-4 md:mb-5">
        {/* 左列：信号流 (3/5 宽度) */}
        <div className="xl:col-span-3">
          <SignalFeed
            positionStockCodes={positionStockCodes}
            pipelineRecords={pipelineRecords}
            onSelectStock={setSelectedStockCode}
          />
        </div>

        {/* 右列：持仓 + Sniper止盈状态 (2/5 宽度) */}
        <div className="xl:col-span-2">
          <PositionPanel
            positions={positions}
            loading={positionsLoading}
            realtimePrices={realtimePrices}
          />
        </div>
      </div>

      {/* ═══ 底部：决策日志 ═══ */}
      <DecisionLog records={pipelineRecords} />

      {/* ═══ 多维信号驾驶舱 Modal ═══ */}
      {selectedStockCode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200">
          <div className="relative w-full max-w-lg shadow-2xl rounded-xl overflow-hidden">
            <MultiSignalDashboard
              stockCode={selectedStockCode}
              onClose={() => setSelectedStockCode(null)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
