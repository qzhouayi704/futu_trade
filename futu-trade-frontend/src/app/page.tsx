// 驾驶舱 — 盘中单屏作战视图
// 左列=信号流 | 右列=持仓+Sniper止盈 | 底部=决策日志

"use client";

import { useState, useEffect, useMemo } from "react";
import { useSocket } from "@/lib/socket";
import { systemApi } from "@/lib/api";
import { useToast } from "@/components/common/Toast";
import { MonitorStartModal, StrategyPanel } from "@/components/monitor";
import { StatusBar, SignalFeed, PositionPanel, DecisionLog, SignalRankingPanel, DailyPickCard, EntryTimingCard, MultiSignalDashboard } from "@/components/cockpit";
import { CapitalBoardCard } from "@/app/components/dashboard/CapitalBoardCard";
import { usePositions } from "./hooks/useDashboard";
import { useSignalPipeline } from "@/lib/hooks/useSignalPipeline";
import { useSocketQuerySync } from "@/lib/hooks/useSocketQuerySync";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from "@/components/ui/accordion";
import type { QuoteData } from "@/types/socket";

const EVIDENCE_TAB_KEY = "cockpitEvidenceTab";

export default function CockpitPage() {
  const { socket, isConnected } = useSocket();
  const { showToast } = useToast();

  // WS 推送 → React Query 共享缓存（sniper_signal 等），各卡统一更新
  useSocketQuerySync();

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

  // 证据区当前 tab（记住上次选择）
  const [evidenceTab, setEvidenceTab] = useState("feed");
  useEffect(() => {
    try {
      const saved = localStorage.getItem(EVIDENCE_TAB_KEY);
      if (saved) setEvidenceTab(saved);
    } catch {}
  }, []);
  const handleEvidenceTab = (v: string) => {
    setEvidenceTab(v);
    try { localStorage.setItem(EVIDENCE_TAB_KEY, v); } catch {}
  };

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

      {/* ═══ A 区「现在该做什么」：今日可买精选 + 持仓教练 ═══ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-5 mb-4 md:mb-5">
        <DailyPickCard onSelectStock={setSelectedStockCode} />
        <PositionPanel
          positions={positions}
          loading={positionsLoading}
          realtimePrices={realtimePrices}
        />
      </div>

      {/* ═══ 入场择时（实验·只读）：强势股低吸择时绿灯，纯展示不下单 ═══ */}
      <div className="mb-4 md:mb-5">
        <EntryTimingCard onSelectStock={setSelectedStockCode} />
      </div>

      {/* ═══ 主力资金看板：全监控池按资金强度排名(只留真大单) + 行内 Sniper 共振 ═══ */}
      <div className="mb-4 md:mb-5">
        <CapitalBoardCard onSelectStock={setSelectedStockCode} />
      </div>

      {/* ═══ 策略 / 监控概览（折叠，非即时） ═══ */}
      <div className="mb-4 md:mb-5 rounded-xl border border-border/60 bg-card px-4">
        <Accordion type="single" collapsible>
          <AccordionItem value="strategy" className="border-b-0">
            <AccordionTrigger>📊 策略 / 监控概览</AccordionTrigger>
            <AccordionContent>
              <StrategyPanel />
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>

      {/* ═══ B 区「证据 / 信号流」：标签收纳，减少长滚动 ═══ */}
      <Tabs value={evidenceTab} onValueChange={handleEvidenceTab} className="mb-4 md:mb-5">
        <TabsList className="overflow-x-auto no-scrollbar max-w-full">
          <TabsTrigger value="feed">📡 信号流</TabsTrigger>
          <TabsTrigger value="ranking">🏆 强度排名</TabsTrigger>
          <TabsTrigger value="decision">📋 决策日志</TabsTrigger>
        </TabsList>
        <TabsContent value="feed">
          <SignalFeed
            positionStockCodes={positionStockCodes}
            pipelineRecords={pipelineRecords}
            onSelectStock={setSelectedStockCode}
          />
        </TabsContent>
        <TabsContent value="ranking">
          <SignalRankingPanel />
        </TabsContent>
        <TabsContent value="decision">
          <DecisionLog records={pipelineRecords} />
        </TabsContent>
      </Tabs>

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
