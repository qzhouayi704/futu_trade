// 市场扫描页面 - 合并活跃个股与股票池监控，精简为快速看价位的统一视图

"use client";

import { useState, useEffect, useMemo, useCallback, useRef, Fragment } from "react";
import Link from "next/link";
import { Card, Button } from "@/components/common";
import { stockApi } from "@/lib/api";
import { useSocket } from "@/lib/socket";
import { useToast } from "@/components/common/Toast";
import { formatPrice, formatPercent, formatTime } from "@/lib/utils";
import type { TopHotStock, TickerSummary, CapitalFlowSummary } from "@/types";
import { analyzeStock, batchAnalyze, type QuickScanResult, type QuickScanRequest } from "@/lib/api/quick-scan";
import { flowSignalApi, type FlowSignalMap, type TradeSignalMap } from "@/lib/api/flow-signal";
import { StockInsightDrawer } from "@/app/market-scan/components/StockInsightDrawer";
import { IntradayLevelsPanel } from "@/app/market-scan/components/IntradayLevelsPanel";
import { AIAnalysisButton } from "@/app/components/AIAnalysisDialog";
import PoolAnomalyBanner from "@/app/market-scan/components/PoolAnomalyBanner";
import ScoredAnomalyPanel from "@/app/market-scan/components/ScoredAnomalyPanel";
import LiquidityScoreCell from "@/app/high-turnover/components/LiquidityScoreCell";
import TradeDirectionBadge from "@/app/high-turnover/components/TradeDirectionBadge";
import BuyRatioCell from "@/app/high-turnover/components/BuyRatioCell";

// ==================== 类型定义 ====================

/** 合并后的股票展示数据 */
interface MergedStock {
  code: string;
  name: string;
  market: string;
  // 行情数据
  last_price: number;
  change_rate: number;
  turnover_rate: number;
  turnover: number;
  // 日内价位数据
  high_price: number;
  low_price: number;
  open_price: number;
  prev_close_price: number;
  // 分析数据
  ticker_summary: TickerSummary | null;
  capital_flow_summary?: CapitalFlowSummary | null;
  capital_signal?: "bullish" | "bearish" | "neutral";
  // 标注
  is_position: boolean;
  plates: { plate_code: string; plate_name: string }[];
  // 新增指标
  volume_ratio: number;
  amplitude: number;
  // 实时覆盖
  last_price_rt?: number;
  change_rate_rt?: number;
  turnover_rate_rt?: number;
  turnover_rt?: number;
  // 流动性评分
  liquidity_score?: number;
  liquidity_level?: string;
  is_volume_anomaly?: boolean;
  kline_data_missing?: boolean;
  // 股票行为标签
  stock_tag?: { label: string; phase: string; risk_note: string } | null;
  // 多策略共识信号
  consensus?: {
    verdict: string;
    verdict_label: string;
    score: number;
    confidence: number;
    total_score?: number;
    passed?: boolean;
    veto_reason?: string | null;
    votes?: { name: string; score: number; max_score: number; signal: string; details?: { label: string; value: string }[] }[];
  } | null;
}

/** 排序字段 */
type SortField = "turnover_rate" | "change_rate" | "turnover" | "main_inflow" | "big_order_ratio" | "capital_signal" | "volume_ratio" | "amplitude" | "score";
type SortDirection = "asc" | "desc";

// ==================== 工具函数 ====================



/** 格式化主力净流入（万/亿） */
function formatInflowZh(val: number): string {
  if (Math.abs(val) >= 1_0000_0000) return (val / 1_0000_0000).toFixed(1) + "亿";
  if (Math.abs(val) >= 1_0000) return (val / 1_0000).toFixed(0) + "万";
  return val.toFixed(0);
}

/** 格式化成交额（万/亿） */
function formatTurnoverZh(val: number): string {
  if (val >= 1_0000_0000) return (val / 1_0000_0000).toFixed(2) + "亿";
  if (val >= 1_0000) return (val / 1_0000).toFixed(1) + "万";
  return val.toFixed(0);
}

/** 换手率颜色 */
function getTurnoverColor(rate: number): string {
  if (rate >= 10) return "text-red-700 bg-red-100";
  if (rate >= 5) return "text-red-600 bg-red-50";
  if (rate >= 2) return "text-orange-600 bg-orange-50";
  return "text-gray-600 bg-gray-50";
}

// ==================== 页面组件 ====================

export default function MarketScanPanel() {
  const { socket } = useSocket();
  const { showToast } = useToast();

  const [mergedStocks, setMergedStocks] = useState<MergedStock[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refiltering, setRefiltering] = useState(false);
  const refilteringRef = useRef(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);



  // 筛选
  const [searchKeyword, setSearchKeyword] = useState("");
  const [marketFilter, setMarketFilter] = useState("all");
  const [tagFilter, setTagFilter] = useState("all");

  // 排序（默认按换手率降序）
  const [sortField, setSortField] = useState<SortField>("turnover_rate");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

  // 价位分析
  const [analysisResults, setAnalysisResults] = useState<Map<string, QuickScanResult>>(new Map());
  const [analysisLoading, setAnalysisLoading] = useState<string | null>(null);
  const [analysisOpen, setAnalysisOpen] = useState<string | null>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  // 操盘规则信号
  const [flowSignals, setFlowSignals] = useState<FlowSignalMap>({});

  // 日线策略信号（判定列优先级最高）
  const [tradeSignals, setTradeSignals] = useState<TradeSignalMap>({});

  // 深度分析 Drawer
  const [insightDrawerOpen, setInsightDrawerOpen] = useState(false);
  const [insightStock, setInsightStock] = useState<{code: string; name: string} | null>(null);

  // 日内资金支撑/阻力位面板
  const [levelsStock, setLevelsStock] = useState<{code: string; name: string} | null>(null);
  const [brokerAnalysis, setBrokerAnalysis] = useState<Record<string, {is_trap: boolean; trap_confidence: number; reason: string}> | null>(null);

  // ==================== 数据加载 ====================

  const loadData = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);

    try {
      // 并行请求两个 API
      const [hotRes, turnoverRes] = await Promise.all([
        stockApi.getTopHotStocks({ limit: 100 }),
        stockApi.getHighTurnoverStocks({ limit: 100 }),
      ]);

      // 以 TopHot 为主（有日内高低价），合并 ticker_summary
      const tickerMap = new Map<string, TickerSummary>();
      const platesMap = new Map<string, { plate_code: string; plate_name: string }[]>();
      const volumeRatioMap = new Map<string, number>();

      if (turnoverRes.success && turnoverRes.data) {
        for (const s of turnoverRes.data.stocks) {
          if (s.ticker_summary) tickerMap.set(s.code, s.ticker_summary);
          if (s.plates?.length) platesMap.set(s.code, s.plates);
          if (s.volume_ratio > 0) volumeRatioMap.set(s.code, s.volume_ratio);
        }
      }

      // 流动性数据映射（从 high-turnover API 获取）
      const liquidityMap = new Map<string, { score?: number; level?: string; anomaly?: boolean; missing?: boolean }>();
      if (turnoverRes.success && turnoverRes.data) {
        for (const s of turnoverRes.data.stocks) {
          if (s.liquidity_score !== undefined) {
            liquidityMap.set(s.code, {
              score: s.liquidity_score,
              level: s.liquidity_level,
              anomaly: s.is_volume_anomaly,
              missing: s.kline_data_missing,
            });
          }
        }
      }

      if (hotRes.success && hotRes.data) {
        const merged = hotRes.data.stocks.map((s: TopHotStock): MergedStock => ({
          code: s.code,
          name: s.name,
          market: s.market,
          last_price: s.last_price || s.cur_price,
          change_rate: s.change_rate,
          turnover_rate: s.turnover_rate,
          turnover: s.turnover,
          high_price: s.high_price,
          low_price: s.low_price,
          open_price: s.open_price,
          prev_close_price: s.prev_close_price,
          ticker_summary: tickerMap.get(s.code) || null,
          capital_flow_summary: s.capital_flow_summary,
          capital_signal: s.capital_signal,
          is_position: s.is_position,
          plates: s.plates?.length ? s.plates : (platesMap.get(s.code) || []),
          volume_ratio: ((s.volume_ratio ?? 0) > 0 ? (s.volume_ratio ?? 0) : (volumeRatioMap.get(s.code) ?? 0)),
          amplitude: s.amplitude || 0,
          liquidity_score: liquidityMap.get(s.code)?.score,
          liquidity_level: liquidityMap.get(s.code)?.level,
          is_volume_anomaly: liquidityMap.get(s.code)?.anomaly,
          kline_data_missing: liquidityMap.get(s.code)?.missing,
          stock_tag: s.stock_tag || null,
          consensus: s.consensus || null,
        }));

        // 防护：刷新时如果新数据量骤降（报价缓存过期），保留旧数据
        if (isRefresh && mergedStocks.length > 10 && merged.length < mergedStocks.length * 0.2) {
          console.warn(`[market-scan] 刷新数据异常: ${merged.length}只 < 原${mergedStocks.length}只的20%, 跳过更新`);
        } else {
          setMergedStocks(merged);
          setLastUpdate(new Date());
        }
      } else {
        showToast("warning", "提示", "暂无数据");
      }
    } catch (err: unknown) {
      // 重新筛选期间后端繁忙，静默跳过错误
      if (!refilteringRef.current) {
        const msg = err instanceof Error ? err.message : "加载数据失败";
        showToast("error", "错误", msg);
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [showToast]);

  useEffect(() => { loadData(); }, [loadData]);

  // 加载操盘规则信号 + 策略信号（初始 + 每60秒刷新）
  useEffect(() => {
    flowSignalApi.getTodayBatch().then(setFlowSignals);
    flowSignalApi.getTradeSignalsBatch().then(setTradeSignals);
    const timer = setInterval(() => {
      flowSignalApi.getTodayBatch().then(setFlowSignals);
      flowSignalApi.getTradeSignalsBatch().then(setTradeSignals);
    }, 60000);
    return () => clearInterval(timer);
  }, []);

  // 自动刷新（30秒），筛选期间暂停
  useEffect(() => {
    if (loading || refiltering) return;
    const timer = setInterval(() => { loadData(true); }, 30000);
    return () => clearInterval(timer);
  }, [loading, refiltering, loadData]);

  // WebSocket 实时报价覆盖
  useEffect(() => {
    if (!socket) return;
    const handleQuotes = (data: unknown) => {
      const d = data as { quotes?: Record<string, unknown>[] };
      if (!d.quotes) return;
      const qMap = new Map(
        d.quotes
          .filter((q) => (q as Record<string, unknown>)?.code)
          .map((q) => {
            const quote = q as Record<string, unknown>;
            return [quote.code as string, quote];
          })
      );
      setMergedStocks((prev) =>
        prev.map((s) => {
          const q = qMap.get(s.code);
          if (!q) return s;
          return {
            ...s,
            last_price_rt: (q.last_price as number) || (q.cur_price as number),
            change_rate_rt: (q.change_rate as number) || (q.change_percent as number),
            turnover_rate_rt: q.turnover_rate as number | undefined,
            turnover_rt: (q.turnover as number) || (q.amount as number),
          };
        })
      );
      setLastUpdate(new Date());
    };
    socket.on("quotes_update", handleQuotes);

    // 筛选完成后自动刷新数据
    const handleRefilterComplete = (data: unknown) => {
      const d = data as { message?: string; active?: number };
      showToast("success", "筛选完成", d.message || `活跃股筛选已完成，共${d.active || 0}只活跃股`);
      setRefiltering(false);
      refilteringRef.current = false;
      loadData(true);
    };
    socket.on("refilter_complete", handleRefilterComplete);

    // 监听自动卖出、经纪商陷阱、交易信号等
    const handleStrategySignal = (data: unknown) => {
      const signal = data as Record<string, unknown>;
      if (!signal || !signal.stock_code) return;
      
      const sigType = String(signal.signal_type).toUpperCase();
      const reason = String(signal.reason || '策略触发');
      const isBrokerTrap = reason.includes('机构出货陷阱') || reason.includes('禁止建仓');
      
      let title: string;
      let type: 'error' | 'warning' | 'info' | 'success';
      
      if (sigType === 'SELL') {
        title = '🚨 自动防守触发';
        type = 'error';
      } else if (sigType === 'ALERT' || sigType === 'DANGER') {
        title = isBrokerTrap ? '⛔ 经纪商陷阱识别' : '⚠️ 风险警告';
        type = 'warning';
      } else if (sigType === 'BUY') {
        title = '💰 买入机会';
        type = 'info';
      } else {
        title = 'ℹ️ 交易信号';
        type = 'info';
      }
      
      const msg = `[${signal.stock_code}] ${signal.stock_name || ''} — ${reason.slice(0, 80)}`;
      showToast(type, title, msg);
    };
    socket.on("strategy_signal", handleStrategySignal);

    return () => {
      socket.off("quotes_update", handleQuotes);
      socket.off("refilter_complete", handleRefilterComplete);
      socket.off("strategy_signal", handleStrategySignal);
    };
  }, [socket, loadData, showToast]);

  // ==================== 展示价格（优先实时） ====================

  const getPrice = (s: MergedStock) => s.last_price_rt ?? s.last_price;
  const getChangeRate = (s: MergedStock) => s.change_rate_rt ?? s.change_rate;
  const getTurnoverRate = (s: MergedStock) => s.turnover_rate_rt ?? s.turnover_rate;
  const getTurnover = (s: MergedStock) => s.turnover_rt ?? s.turnover;

  // ==================== 筛选 + 排序 ====================

  const displayStocks = useMemo(() => {
    let list = mergedStocks;

    if (marketFilter !== "all") {
      list = list.filter((s) => s.market === marketFilter);
    }
    if (searchKeyword.trim()) {
      const kw = searchKeyword.trim().toLowerCase();
      list = list.filter((s) => s.code.toLowerCase().includes(kw) || s.name.toLowerCase().includes(kw));
    }
    if (tagFilter !== "all") {
      list = list.filter((s) => (s.stock_tag?.label || "正常") === tagFilter);
    }

    const sorted = [...list].sort((a, b) => {
      let aVal: number, bVal: number;
      switch (sortField) {
        case "turnover_rate":
          aVal = getTurnoverRate(a); bVal = getTurnoverRate(b); break;
        case "change_rate":
          aVal = getChangeRate(a); bVal = getChangeRate(b); break;
        case "turnover":
          aVal = getTurnover(a); bVal = getTurnover(b); break;

        case "main_inflow":
          aVal = a.capital_flow_summary?.main_net_inflow || 0;
          bVal = b.capital_flow_summary?.main_net_inflow || 0;
          break;
        case "big_order_ratio":
          aVal = a.capital_flow_summary?.big_order_buy_ratio || 0;
          bVal = b.capital_flow_summary?.big_order_buy_ratio || 0;
          break;
        case "capital_signal": {
          const order: Record<string, number> = { bullish: 2, neutral: 1, bearish: 0 };
          aVal = order[a.capital_signal || "neutral"] ?? 1;
          bVal = order[b.capital_signal || "neutral"] ?? 1;
          break;
        }
        case "volume_ratio":
          aVal = a.volume_ratio; bVal = b.volume_ratio; break;
        case "amplitude":
          aVal = a.amplitude; bVal = b.amplitude; break;
        case "score":
          aVal = a.consensus?.total_score ?? 0;
          bVal = b.consensus?.total_score ?? 0;
          break;
        default:
          aVal = 0; bVal = 0;
      }
      return sortDirection === "asc" ? aVal - bVal : bVal - aVal;
    });

    return sorted;
  }, [mergedStocks, marketFilter, searchKeyword, sortField, sortDirection]);

  // ==================== 排序切换 ====================

  const handleSort = (field: SortField) => {
    if (field === sortField) {
      setSortDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDirection("desc");
    }
  };

  const SortIcon = ({ field }: { field: SortField }) => {
    if (field !== sortField) return <i className="fas fa-sort text-gray-300 ml-1" />;
    return sortDirection === "asc"
      ? <i className="fas fa-sort-up text-blue-600 ml-1" />
      : <i className="fas fa-sort-down text-blue-600 ml-1" />;
  };

  // ==================== 行点击 ====================

  const handleRowClick = useCallback((stock: MergedStock) => {
    // 切换日内支撑/阻力位面板（同一只收起，不同只切换）
    setLevelsStock((prev) =>
      prev?.code === stock.code ? null : { code: stock.code, name: stock.name }
    );
  }, []);

  // ==================== 价位分析 ====================

  const handleAnalyze = useCallback(async (stock: MergedStock, e: React.MouseEvent) => {
    e.stopPropagation();
    if (analysisOpen === stock.code) {
      setAnalysisOpen(null);
      return;
    }
    setAnalysisLoading(stock.code);
    setAnalysisOpen(stock.code);
    try {
      const params: QuickScanRequest = {
        stock_code: stock.code,
        last_price: getPrice(stock),
        open_price: stock.open_price || 0,
        prev_close_price: stock.prev_close_price || 0,
        high_price: stock.high_price || 0,
        low_price: stock.low_price || 0,
        change_rate: getChangeRate(stock),
        turnover_rate: getTurnoverRate(stock),
        volume_ratio: stock.volume_ratio || 0,
        amplitude: stock.amplitude || 0,
        capital_score: stock.capital_flow_summary?.capital_score ?? 50,
        big_order_buy_ratio: stock.capital_flow_summary?.big_order_buy_ratio ?? 0.5,
        main_net_inflow: stock.capital_flow_summary?.main_net_inflow ?? 0,
        ticker_score: stock.ticker_summary?.score ?? 0,
        ticker_buy_sell_ratio: stock.ticker_summary?.buy_sell_ratio ?? 1.0,
        is_position: stock.is_position,
      };
      const result = await analyzeStock(params);
      setAnalysisResults(prev => new Map(prev).set(stock.code, result));
    } catch (err) {
      console.error("分析失败:", err);
    } finally {
      setAnalysisLoading(null);
    }
  }, [analysisOpen]);

  // 点击外部关闭弹窗
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setAnalysisOpen(null);
      }
    };
    if (analysisOpen) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [analysisOpen]);

  // ==================== 自动批量分析 ====================

  const batchAnalyzeAll = useCallback(async (stocks: MergedStock[]) => {
    if (stocks.length === 0) return;
    const BATCH_SIZE = 30;
    for (let i = 0; i < stocks.length; i += BATCH_SIZE) {
      const batch = stocks.slice(i, i + BATCH_SIZE);
      const params: QuickScanRequest[] = batch.map((stock) => ({
        stock_code: stock.code,
        last_price: getPrice(stock),
        open_price: stock.open_price || 0,
        prev_close_price: stock.prev_close_price || 0,
        high_price: stock.high_price || 0,
        low_price: stock.low_price || 0,
        change_rate: getChangeRate(stock),
        turnover_rate: getTurnoverRate(stock),
        volume_ratio: stock.volume_ratio || 0,
        amplitude: stock.amplitude || 0,
        capital_score: stock.capital_flow_summary?.capital_score ?? 50,
        big_order_buy_ratio: stock.capital_flow_summary?.big_order_buy_ratio ?? 0.5,
        main_net_inflow: stock.capital_flow_summary?.main_net_inflow ?? 0,
        ticker_score: stock.ticker_summary?.score ?? 0,
        ticker_buy_sell_ratio: stock.ticker_summary?.buy_sell_ratio ?? 1.0,
        is_position: stock.is_position,
      }));
      try {
        const results = await batchAnalyze(params);
        setAnalysisResults((prev) => {
          const next = new Map(prev);
          results.forEach((r) => { if (r.stock_code) next.set(r.stock_code, r); });
          return next;
        });
      } catch (err) {
        console.error(`批量分析第${Math.floor(i / BATCH_SIZE) + 1}批失败:`, err);
      }
    }
  }, []);

  // 数据加载后自动触发分析
  useEffect(() => {
    if (mergedStocks.length > 0) {
      batchAnalyzeAll(mergedStocks);
    }
  }, [mergedStocks, batchAnalyzeAll]);

  // 每60秒自动刷新分析
  useEffect(() => {
    if (mergedStocks.length === 0) return;
    const timer = setInterval(() => { batchAnalyzeAll(mergedStocks); }, 60000);
    return () => clearInterval(timer);
  }, [mergedStocks, batchAnalyzeAll]);

  // ==================== 统计 ====================

  const bullishCount = useMemo(() =>
    mergedStocks.filter((s) => s.capital_signal === "bullish").length
  , [mergedStocks]);

  const bearishCount = useMemo(() =>
    mergedStocks.filter((s) => s.capital_signal === "bearish").length
  , [mergedStocks]);

  // ==================== 渲染 ====================

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <i className="fas fa-spinner fa-spin text-3xl text-blue-600 mb-4" />
          <p className="text-gray-500">加载市场数据中...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      {/* 标题栏 */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <i className="fas fa-radar text-blue-600" />
            目标股票
            {bullishCount > 0 && (
              <span className="text-sm font-medium text-red-600 bg-red-50 px-2 py-0.5 rounded">
                偏多 {bullishCount}
              </span>
            )}
            {bearishCount > 0 && (
              <span className="text-sm font-medium text-green-600 bg-green-50 px-2 py-0.5 rounded">
                偏空 {bearishCount}
              </span>
            )}
          </h1>
          <p className="text-gray-600 mt-1 text-sm">
            监控池活跃股票，快速定位价位状态
            {lastUpdate && (
              <span className="ml-2 text-xs text-gray-400">
                更新于 {formatTime(lastUpdate)}
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            loading={refiltering}
            onClick={async () => {
              setRefiltering(true);
              refilteringRef.current = true;
              try {
                const res = await stockApi.refilterActivity();
                if (res.success) {
                  showToast("success", "筛选已启动", res.message || "正在后台重新筛选活跃股，完成后将自动刷新");
                  // 安全超时：5分钟后无论如何恢复状态（防止 WS 断连时卡死）
                  setTimeout(() => {
                    setRefiltering(false);
                    refilteringRef.current = false;
                  }, 5 * 60 * 1000);
                } else {
                  showToast("warning", "提示", res.message || "筛选启动失败");
                  setRefiltering(false);
                  refilteringRef.current = false;
                }
              } catch (err: unknown) {
                const msg = err instanceof Error ? err.message : "筛选请求失败";
                showToast("error", "错误", msg);
                setRefiltering(false);
                refilteringRef.current = false;
              }
            }}
            className="flex items-center gap-1"
          >
            <i className="fas fa-filter" />
            重新筛选活跃股
          </Button>
          <Button
            size="sm"
            variant="secondary"
            loading={refreshing}
            onClick={() => loadData(true)}
            className="flex items-center gap-1"
          >
            <i className="fas fa-sync-alt" />
            刷新
          </Button>
        </div>
      </div>

      {/* 全池异动提醒 */}
      <PoolAnomalyBanner />
      <ScoredAnomalyPanel />

      {/* 筛选栏 */}
      <Card className="mb-6">
        <div className="flex flex-wrap items-center gap-3 p-4">
          <input
            type="text"
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
            placeholder="搜索代码或名称..."
            className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 w-60"
          />
          <div className="flex gap-1">
            {["all", "HK", "US"].map((m) => (
              <button
                key={m}
                onClick={() => setMarketFilter(m)}
                className={`px-3 py-2 text-sm rounded-md transition-colors ${
                  marketFilter === m
                    ? "bg-blue-600 text-white"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}
              >
                {m === "all" ? "全部" : m === "HK" ? "港股" : "美股"}
              </button>
            ))}
          </div>
          <div className="flex gap-1">
            {[
              { key: "all", label: "全部", color: "bg-blue-600" },
              { key: "锁仓控盘", label: "🔒控盘", color: "bg-red-600" },
              { key: "暴量拉升", label: "🚀暴量", color: "bg-orange-600" },
              { key: "仙股炒作", label: "💀仙股", color: "bg-purple-600" },
              { key: "明星高波动", label: "⭐明星", color: "bg-sky-600" },
              { key: "正常", label: "✅正常", color: "bg-gray-600" },
            ].map((t) => (
              <button
                key={t.key}
                onClick={() => setTagFilter(t.key)}
                className={`px-2.5 py-1.5 text-xs rounded-md transition-colors ${
                  tagFilter === t.key
                    ? `${t.color} text-white`
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="ml-auto text-sm text-gray-500">
            共 {displayStocks.length} 只
          </div>
        </div>
      </Card>

      {/* 主表格 */}
      <Card>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-3 text-xs font-medium text-gray-500 text-center w-12">#</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500 text-left">股票</th>
                <th className="px-3 py-3 text-xs font-medium text-gray-500 text-center" title="综合成交量、换手率、历史稳定性的流动性评分">流动性</th>
                <th className="px-3 py-3 text-xs font-medium text-gray-500 text-center" title="股票行为标签（控盘检测）">标签</th>
                <th className="px-3 py-3 text-xs font-medium text-gray-500 text-right">现价</th>
                <th className="px-3 py-3 text-xs font-medium text-gray-500 text-right cursor-pointer hover:bg-gray-100 select-none" onClick={() => handleSort("change_rate")}>
                  <span className="inline-flex items-center">涨跌幅<SortIcon field="change_rate" /></span>
                </th>
                <th className="px-3 py-3 text-xs font-medium text-gray-500 text-right cursor-pointer hover:bg-gray-100 select-none" onClick={() => handleSort("turnover_rate")}>
                  <span className="inline-flex items-center">换手率<SortIcon field="turnover_rate" /></span>
                </th>
                <th className="px-3 py-3 text-xs font-medium text-gray-500 text-right cursor-pointer hover:bg-gray-100 select-none" onClick={() => handleSort("turnover")}>
                  <span className="inline-flex items-center">成交额<SortIcon field="turnover" /></span>
                </th>

                <th className="px-2 py-3 text-xs font-medium text-gray-500 text-center" title="根据逐笔成交分析，判断主动买卖力量">方向</th>
                <th className="px-2 py-3 text-xs font-medium text-gray-500 text-right" title="主动买入金额 / 主动卖出金额">力量比</th>
                <th className="px-3 py-3 text-xs font-medium text-gray-500 text-right cursor-pointer hover:bg-gray-100 select-none" onClick={() => handleSort("main_inflow")} title="主力资金净流入金额（含实时增减趋势）">
                  <span className="inline-flex items-center">主力净流入<SortIcon field="main_inflow" /></span>
                </th>
                <th className="px-3 py-3 text-xs font-medium text-gray-500 text-center cursor-pointer hover:bg-gray-100 select-none" onClick={() => handleSort("score")}>
                  <span className="inline-flex items-center">评分<SortIcon field="score" /></span>
                </th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500 text-left">板块</th>
                <th className="px-2 py-3 text-xs font-medium text-gray-500 text-center w-16">操作</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {displayStocks.length === 0 ? (
                <tr>
                  <td colSpan={13} className="text-center py-12 text-gray-500">
                    <i className="fas fa-inbox text-4xl mb-4 block" />
                    暂无数据
                  </td>
                </tr>
              ) : (
                displayStocks.map((stock, idx) => {
                  const price = getPrice(stock);
                  const changeRate = getChangeRate(stock);
                  const turnoverRate = getTurnoverRate(stock);
                  const turnover = getTurnover(stock);
                  const capitalFlow = stock.capital_flow_summary;

                  const changeColor = changeRate >= 0 ? "text-red-600" : "text-green-600";
                  const changePrefix = changeRate >= 0 ? "+" : "";

                  return (
                    <Fragment key={stock.code}>
                      <tr
                        className={`hover:bg-blue-50/50 cursor-pointer transition-colors ${levelsStock?.code === stock.code ? "bg-blue-50/30" : ""}`}
                        onClick={() => handleRowClick(stock)}
                      >
                      {/* 排名 */}
                      <td className="px-3 py-3 text-sm text-center text-gray-400 font-medium">
                        {idx + 1}
                      </td>

                      {/* 股票名称/代码 */}
                      <td className="px-4 py-3 text-sm">
                        <div className="font-medium text-gray-900 flex items-center gap-1">
                          {stock.name}
                          {stock.is_position && (
                            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-100 text-purple-700">
                              持仓
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-gray-400">{stock.code}</div>
                      </td>

                      {/* 流动性评分 */}
                      <td className="px-3 py-3 text-sm text-center">
                        <LiquidityScoreCell
                          score={stock.liquidity_score}
                          level={stock.liquidity_level}
                          isAnomaly={stock.is_volume_anomaly}
                          klineDataMissing={stock.kline_data_missing}
                        />
                      </td>

                      {/* 股票标签 */}
                      <td className="px-3 py-3 text-sm text-center">
                        {(() => {
                          const tag = stock.stock_tag;
                          if (!tag || tag.label === "正常") return <span className="text-gray-300 text-xs">-</span>;
                          const styles: Record<string, string> = {
                            "锁仓控盘": "bg-red-100 text-red-700",
                            "暴量拉升": "bg-orange-100 text-orange-700",
                            "仙股炒作": "bg-purple-100 text-purple-700",
                            "明星高波动": "bg-sky-100 text-sky-700",
                          };
                          const icons: Record<string, string> = {
                            "锁仓控盘": "🔒", "暴量拉升": "🚀", "仙股炒作": "💀", "明星高波动": "⭐",
                          };
                          return (
                            <span
                              className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium cursor-help ${styles[tag.label] || "bg-gray-100 text-gray-600"}`}
                              title={`${tag.risk_note}${tag.phase ? ` · ${tag.phase}` : ""}`}
                            >
                              {icons[tag.label] || ""}{tag.label.slice(0, 2)}
                              {tag.phase && <span className="text-[9px] opacity-70">·{tag.phase.slice(0, 2)}</span>}
                            </span>
                          );
                        })()}
                      </td>

                      {/* 现价 */}
                      <td className="px-3 py-3 text-sm text-right">
                        <span className={`font-medium ${changeColor}`}>
                          {formatPrice(price)}
                        </span>
                      </td>

                      {/* 涨跌幅 */}
                      <td className="px-3 py-3 text-sm text-right">
                        <span className={`font-medium ${changeColor}`}>
                          {changePrefix}{formatPercent(changeRate)}
                        </span>
                      </td>

                      {/* 换手率 */}
                      <td className="px-3 py-3 text-sm text-right">
                        <span className={`inline-block px-2 py-0.5 rounded font-semibold text-xs ${getTurnoverColor(turnoverRate)}`}>
                          {formatPercent(turnoverRate)}
                        </span>
                      </td>

                      {/* 成交额 */}
                      <td className="px-3 py-3 text-sm text-right text-gray-700">
                        {formatTurnoverZh(turnover)}
                      </td>

                      {/* 成交方向 (from ticker analysis) */}
                      <td className="px-2 py-3 text-sm text-center">
                        <TradeDirectionBadge summary={stock.ticker_summary} />
                      </td>

                      {/* 力量比 */}
                      <td className="px-2 py-3 text-sm text-right">
                        <BuyRatioCell summary={stock.ticker_summary} />
                      </td>

                      {/* 主力净流入 + 实时趋势 */}
                      <td className="px-3 py-3 text-sm text-right">
                        {capitalFlow ? (() => {
                          const val = capitalFlow.main_net_inflow;
                          const delta = (capitalFlow as unknown as Record<string, unknown>).inflow_change as number || 0;
                          const color = val > 0 ? "text-red-600" : val < 0 ? "text-green-600" : "text-gray-500";
                          // 变化超过1万才显示趋势箭头
                          const showTrend = Math.abs(delta) > 10000;
                          return (
                            <span className={`inline-flex items-center gap-1 font-medium ${color}`}>
                              {val > 0 ? "+" : ""}{formatInflowZh(val)}
                              {showTrend && delta > 0 && (
                                <span className="text-[10px] text-red-500 animate-pulse" title={`较上次增加 ${formatInflowZh(Math.abs(delta))}`}>▲</span>
                              )}
                              {showTrend && delta < 0 && (
                                <span className="text-[10px] text-green-500" title={`较上次减少 ${formatInflowZh(Math.abs(delta))}`}>▼</span>
                              )}
                            </span>
                          );
                        })() : <span className="text-gray-300">-</span>}
                      </td>

                      {/* 交易评分 */}
                      <td className="px-3 py-3 text-sm text-center">
                        {(() => {
                          const c = stock.consensus;
                          if (!c) return <span className="text-gray-300 text-xs">-</span>;
                          const score = c.total_score ?? 0;
                          const color = score >= 60 ? 'text-red-600' : score >= 40 ? 'text-yellow-600' : 'text-green-600';
                          return (
                            <span className={`inline-flex items-center gap-0.5 font-bold text-sm ${color}`} title={`${c.passed ? '✓通过' : '✗未通过'} | ${c.veto_reason || '无否决'}`}>
                              {score}
                              {c.passed && <span className="text-[8px] text-emerald-500">✓</span>}
                            </span>
                          );
                        })()}
                      </td>

                      {/* 板块 */}
                      <td className="px-4 py-3 text-sm">
                        <div className="flex flex-wrap gap-1 max-w-[180px]">
                          {stock.plates.length > 0 ? (
                            stock.plates.slice(0, 2).map((p) => (
                              <Link
                                key={p.plate_code}
                                href={`/plate/${p.plate_code}`}
                                className="inline-block px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded text-[10px] hover:bg-blue-100 transition-colors"
                                onClick={(e) => e.stopPropagation()}
                              >
                                {p.plate_name}
                              </Link>
                            ))
                          ) : (
                            <span className="text-gray-300 text-xs">-</span>
                          )}
                          {stock.plates.length > 2 && (
                            <span className="text-gray-400 text-[10px]">+{stock.plates.length - 2}</span>
                          )}
                        </div>
                      </td>

                      {/* 操作：深度分析 + 信号指示 */}
                      <td className="px-2 py-3 text-sm text-center relative">
                        <div className="inline-flex items-center gap-1">
                          {/* 策略信号指示点 */}
                          {(() => {
                            const ts = tradeSignals[stock.code];
                            const cr = stock.change_rate || 0;
                            const valid = ts?.filter((s) => {
                              if (s.signal_type === "BUY" && cr < -5) return false;
                              if (s.signal_type === "SELL" && cr > 5) return false;
                              return true;
                            });
                            if (valid && valid.length > 0) {
                              const main = valid[0];
                              const isBuy = main.signal_type === "BUY";
                              return (
                                <span
                                  className={`w-2 h-2 rounded-full flex-shrink-0 ${isBuy ? "bg-emerald-500 animate-pulse" : "bg-red-500 animate-pulse"}`}
                                  title={`${isBuy ? "买入" : "卖出"}信号: ${main.condition_text || main.strategy_name}`}
                                />
                              );
                            }
                            return null;
                          })()}
                          {/* AI 分析按钮 */}
                          <AIAnalysisButton stockCode={stock.code} stockName={stock.name} />
                          {/* 深度分析按钮 */}
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setInsightStock({ code: stock.code, name: stock.name });
                              setInsightDrawerOpen(true);
                            }}
                            className="inline-flex items-center justify-center w-7 h-7 rounded-md text-xs transition-all bg-gray-50 text-gray-500 hover:bg-blue-50 hover:text-blue-600"
                            title="深度分析"
                          >
                            <i className="fas fa-chart-line text-xs" />
                          </button>
                        </div>
                      </td>
                    </tr>
                    
                    {/* 折叠行：日内资金支撑/阻力位面板 */}
                    {levelsStock?.code === stock.code && (
                      <tr className="bg-gray-50 border-b border-gray-100 shadow-inner">
                        <td colSpan={11} className="p-4">
                          {/* 实时大单动能面板 */}
                          <div className="mb-4 bg-white rounded-lg border border-gray-200 p-4 flex items-center justify-between shadow-sm relative overflow-hidden">
                            {/* 动能背景光晕 */}
                            <div className={`absolute top-0 right-0 w-64 h-64 rounded-full blur-3xl opacity-10 -mr-10 -mt-20 pointer-events-none ${
                              stock.capital_signal === "bullish" ? "bg-red-500" :
                              stock.capital_signal === "bearish" ? "bg-green-500" : "bg-gray-400"
                            }`}></div>
                            
                            <div className="flex items-center gap-8 relative z-10">
                              <div>
                                <div className="text-xs text-gray-500 mb-1">今日主力大单净流入</div>
                                <div className={`text-xl font-bold ${stock.capital_flow_summary && stock.capital_flow_summary.main_net_inflow > 0 ? "text-red-600" : stock.capital_flow_summary && stock.capital_flow_summary.main_net_inflow < 0 ? "text-green-600" : "text-gray-900"}`}>
                                  {stock.capital_flow_summary ? formatInflowZh(stock.capital_flow_summary.main_net_inflow) : "-"}
                                </div>
                              </div>
                              <div className="h-10 w-px bg-gray-200"></div>
                              <div>
                                <div className="text-xs text-gray-500 mb-1">大单买入占比</div>
                                <div className="text-xl font-bold text-gray-900">
                                  {stock.capital_flow_summary ? (stock.capital_flow_summary.big_order_buy_ratio * 100).toFixed(1) + "%" : "-"}
                                </div>
                              </div>
                              <div className="h-10 w-px bg-gray-200"></div>
                              <div>
                                <div className="text-xs text-gray-500 mb-1">当前动能走势预测</div>
                                <div className="text-lg font-bold">
                                  {stock.capital_signal === "bullish" ? (
                                    <span className="text-red-600 flex items-center gap-2"><i className="fas fa-rocket animate-pulse"></i> 主力资金持续流入</span>
                                  ) : stock.capital_signal === "bearish" ? (
                                    <span className="text-green-600 flex items-center gap-2"><i className="fas fa-arrow-down animate-bounce"></i> 主力资金持续流出</span>
                                  ) : (
                                    <span className="text-gray-500 flex items-center gap-2"><i className="fas fa-minus"></i> 主力资金观望</span>
                                  )}
                                </div>
                              </div>
                            </div>
                            
                            <div className="text-xs text-gray-400 max-w-xs text-right relative z-10 bg-white/80 p-2 rounded">
                              <i className="fas fa-info-circle mr-1"></i>
                              上方为<b>全天大单累计数据</b>，下方图表为<b>近期阻力价位搏杀情况</b>。若全天大单呈净流入，回踩支撑位时即为黄金买点。
                            </div>
                          </div>


                          {/* 多策略投票总览 — StockScorer 6维评分 */}
                          {stock.consensus && (
                            <div className="mb-4 bg-white rounded-lg border border-gray-200 p-4 shadow-sm">
                              <div className="flex items-center justify-between mb-3">
                                <div className="flex items-center gap-2">
                                  <span className="text-sm font-semibold text-gray-800">📊 交易评分</span>
                                  {(() => {
                                    const c = stock.consensus!;
                                    const verdictStyles: Record<string, string> = {
                                      strong_buy: 'bg-red-100 text-red-700 border-red-200',
                                      buy: 'bg-blue-100 text-blue-700 border-blue-200',
                                      watch: 'bg-gray-100 text-gray-600 border-gray-200',
                                      sell: 'bg-yellow-100 text-yellow-700 border-yellow-200',
                                      strong_sell: 'bg-green-100 text-green-700 border-green-200',
                                      conflicting: 'bg-amber-100 text-amber-700 border-amber-200',
                                    };
                                    const label = (c.verdict_label || '').replace(/[🟢🔵⚪🟡🔴⚠️]/g, '').trim();
                                    return (
                                      <span className={`inline-flex items-center px-2 py-0.5 rounded border text-xs font-bold ${verdictStyles[c.verdict] || verdictStyles.watch}`}>
                                        {label}
                                      </span>
                                    );
                                  })()}
                                  {stock.consensus.veto_reason && (
                                    <span className="inline-flex items-center px-2 py-0.5 rounded bg-red-50 border border-red-200 text-red-700 text-[10px] font-bold">
                                      ⛔ {stock.consensus.veto_reason}
                                    </span>
                                  )}
                                </div>
                                <div className="text-xs text-gray-400 flex items-center gap-3">
                                  <span>
                                    总分 <span className={`font-bold text-base ${
                                      (stock.consensus.total_score ?? 0) >= 60 ? 'text-red-600' :
                                      (stock.consensus.total_score ?? 0) >= 40 ? 'text-yellow-600' : 'text-green-600'
                                    }`}>{stock.consensus.total_score ?? '-'}</span>
                                    <span className="text-gray-300">/100</span>
                                  </span>
                                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                    stock.consensus.passed ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-500'
                                  }`}>
                                    {stock.consensus.passed ? '✓ 通过' : '未通过'}
                                  </span>
                                </div>
                              </div>
                              {/* 6维评分明细 (StockScorer) */}
                              <div className="space-y-1.5">
                                {(stock.consensus.votes || []).filter(v => v.max_score <= 30).map((vote) => {
                                  const pct = vote.max_score > 0 ? Math.round(vote.score / vote.max_score * 100) : 0;
                                  const barColor = vote.signal === 'bullish' ? 'bg-red-500' : vote.signal === 'bearish' ? 'bg-green-500' : 'bg-gray-400';
                                  const signalIcon = vote.signal === 'bullish' ? '✓' : vote.signal === 'bearish' ? '✗' : '—';
                                  const iconColor = vote.signal === 'bullish' ? 'text-red-500' : vote.signal === 'bearish' ? 'text-green-500' : 'text-gray-400';
                                  return (
                                    <div key={vote.name} className="flex items-center gap-2">
                                      <span className={`text-xs w-4 text-center font-bold ${iconColor}`}>{signalIcon}</span>
                                      <span className="text-xs text-gray-600 w-14 flex-shrink-0">{vote.name}</span>
                                      <div className="flex-1 bg-gray-100 rounded-full h-1.5 overflow-hidden">
                                        <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${pct}%` }} />
                                      </div>
                                      <span className="text-xs font-mono text-gray-600 w-12 text-right">{vote.score}/{vote.max_score}</span>
                                      {vote.details && vote.details.length > 0 && (
                                        <span className="text-[10px] text-gray-400 w-20 text-right truncate" title={vote.details.map(d => `${d.label}: ${d.value}`).join(' | ')}>
                                          {vote.details[0].value}
                                        </span>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>
                              {/* 策略引擎评估 */}
                              {(stock.consensus.votes || []).filter(v => v.max_score > 30).length > 0 && (
                                <>
                                  <div className="flex items-center gap-2 mt-3 mb-2">
                                    <div className="flex-1 border-t border-gray-200" />
                                    <span className="text-[10px] text-gray-400 font-medium">策略引擎</span>
                                    <div className="flex-1 border-t border-gray-200" />
                                  </div>
                                  <div className="space-y-1.5">
                                    {(stock.consensus.votes || []).filter(v => v.max_score > 30).map((vote) => {
                                      const pct = Math.round(vote.score);
                                      const barColor = vote.signal === 'bullish' ? 'bg-red-500' : vote.signal === 'bearish' ? 'bg-green-500' : 'bg-gray-400';
                                      const signalIcon = vote.signal === 'bullish' ? '✓' : vote.signal === 'bearish' ? '✗' : '—';
                                      const iconColor = vote.signal === 'bullish' ? 'text-red-500' : vote.signal === 'bearish' ? 'text-green-500' : 'text-gray-400';
                                      return (
                                        <div key={vote.name} className="space-y-0.5">
                                          <div className="flex items-center gap-2">
                                            <span className={`text-xs w-4 text-center font-bold ${iconColor}`}>{signalIcon}</span>
                                            <span className="text-xs text-gray-600 w-14 flex-shrink-0">{vote.name}</span>
                                            <div className="flex-1 bg-gray-100 rounded-full h-1.5 overflow-hidden">
                                              <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${pct}%` }} />
                                            </div>
                                            <span className="text-xs font-mono text-gray-600 w-10 text-right">{vote.score}</span>
                                          </div>
                                          {vote.details && vote.details.length > 0 && (
                                            <div className="ml-[24px] flex flex-wrap gap-x-3">
                                              {vote.details.map((d) => (
                                                <span key={d.label} className="text-[10px] text-gray-400">
                                                  {d.label}: <span className="text-gray-600 font-medium">{d.value}</span>
                                                </span>
                                              ))}
                                            </div>
                                          )}
                                        </div>
                                      );
                                    })}
                                  </div>
                                </>
                              )}
                            </div>
                          )}

                          <IntradayLevelsPanel
                            stockCode={levelsStock.code}
                            stockName={levelsStock.name}
                            onClose={() => setLevelsStock(null)}
                            onBrokerAnalysis={(analysis) => {
                              setBrokerAnalysis(prev => ({
                                ...prev,
                                [levelsStock.code]: analysis ?? undefined,
                              }) as typeof prev);
                            }}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {/* 个股深度分析 Drawer */}
      {insightStock && (
        <StockInsightDrawer
          isOpen={insightDrawerOpen}
          onClose={() => setInsightDrawerOpen(false)}
          stockCode={insightStock.code}
          stockName={insightStock.name}
          quickScanResult={analysisResults.get(insightStock.code) as unknown as Record<string, unknown>}
          flowSignals={flowSignals[insightStock.code]?.map(s => s as unknown as Record<string, unknown>)}
        />
      )}
    </div>
  );
}
