// 日内资金支撑/阻力位面板 - 实时展示在 market-scan 主页
// 融合成交量聚集 + 大单追踪 + 盘口挂单三维数据

"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  getIntradayLevels,
  getCapitalFlowTimeline,
  getCCASHoldings,
  type IntradayLevelsData,
  type IntradayPriceLevel,
  type BrokerAnalysis,
  type CapitalFlowTimelinePoint,
  type FlowSummary,
  type CCASHoldingsData,
} from "@/lib/api/enhanced-heat";
import dynamic from "next/dynamic";

// 动态加载图表组件，禁用 SSR
const CapitalFlowChartDyn = dynamic(() => import("./CapitalFlowChart").then(mod => mod.CapitalFlowChart), {
  ssr: false,
  loading: () => (
    <div className="w-full h-full min-h-[300px] flex items-center justify-center bg-gray-50/50">
      <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
    </div>
  )
});

// ==================== 工具函数 ====================

function formatVolume(v: number): string {
  if (v >= 100_000_000) return `${(v / 100_000_000).toFixed(2)}亿`;
  if (v >= 10_000) return `${(v / 10_000).toFixed(1)}万`;
  if (v >= 1000) return v.toLocaleString();
  return String(v);
}

function formatPrice(price: number): string {
  return price.toFixed(price >= 100 ? 2 : 3);
}

// 类型 → 图标映射
const TYPE_ICONS: Record<string, string> = {
  volume_poc: "📊",
  big_order_buy: "💰",
  big_order_sell: "💰",
  order_book_bid: "🧱",
  order_book_ask: "🧱",
};

// ==================== 子组件 ====================

/** 单个价位行 */
function LevelRow({
  level,
  side,
}: {
  level: IntradayPriceLevel;
  side: "support" | "resistance";
}) {
  const isSupport = side === "support";
  const isUnreliable = level.reliability === 'order_book_only';
  const barColor = isSupport
    ? "bg-emerald-500"
    : "bg-red-500";
  const textColor = isSupport
    ? "text-emerald-600"
    : "text-red-600";
  const bgHover = isSupport
    ? "hover:bg-emerald-50"
    : "hover:bg-red-50";

  return (
    <div
      className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${bgHover} ${isUnreliable ? 'opacity-60' : ''}`}
    >
      {/* 图标 */}
      <span className="text-sm shrink-0">
        {TYPE_ICONS[level.type] || "📍"}
      </span>

      {/* 价格 */}
      <span className={`font-mono font-bold text-sm w-20 ${textColor}`}>
        {formatPrice(level.price)}
      </span>

      {/* 强度条 */}
      <div className="flex-1 flex items-center gap-2">
        <div className={`flex-1 h-2.5 bg-gray-100 rounded-full overflow-hidden ${isUnreliable ? 'border border-dashed border-gray-300' : ''}`}>
          <div
            className={`h-full rounded-full transition-all duration-500 ${barColor} ${isUnreliable ? 'opacity-40' : ''}`}
            style={{ width: `${level.strength}%`, opacity: isUnreliable ? 0.4 : 0.7 + level.strength * 0.003 }}
          />
        </div>
        <span className="text-xs text-gray-500 w-7 text-right font-medium">
          {level.strength}
        </span>
      </div>

      {/* 标签 + 量 + 可信度 */}
      <div className="text-right shrink-0">
        <div className="text-[11px] text-gray-500 flex items-center justify-end gap-1">
          {level.label}
          {isUnreliable && (
            <span className="text-[9px] bg-amber-100 text-amber-700 px-1 rounded font-medium" title="挂单可随时撤销，不可作为止损依据">
              ⚠可撤
            </span>
          )}
        </div>
        {level.volume > 0 && (
          <div className="text-[10px] text-gray-400 font-mono">
            {formatVolume(level.volume)}
          </div>
        )}
      </div>
    </div>
  );
}

/** 当前价 / VWAP 分隔线 */
function PriceDivider({
  currentPrice,
  vwap,
}: {
  currentPrice: number;
  vwap: IntradayLevelsData["vwap"];
}) {
  return (
    <div className="flex items-center gap-3 py-2 px-3">
      <div className="flex-1 border-t-2 border-dashed border-blue-300" />
      <div className="flex items-center gap-3 shrink-0">
        <span className="text-xs font-bold text-blue-600">
          当前 {formatPrice(currentPrice)}
        </span>
        {vwap && (
          <span className="text-[11px] text-gray-400">
            VWAP {formatPrice(vwap.price)}
            <span
              className={`ml-1 ${
                vwap.deviation_pct >= 0 ? "text-red-400" : "text-emerald-400"
              }`}
            >
              ({vwap.deviation_pct >= 0 ? "+" : ""}
              {vwap.deviation_pct.toFixed(2)}%)
            </span>
          </span>
        )}
      </div>
      <div className="flex-1 border-t-2 border-dashed border-blue-300" />
    </div>
  );
}
// ==================== CCASS 持仓变化组件 ====================

function CCASSection({ stockCode }: { stockCode: string }) {
  const [ccasData, setCcasData] = useState<CCASHoldingsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getCCASHoldings(stockCode)
      .then(res => {
        if (!cancelled && res.success && res.data) {
          setCcasData(res.data);
        }
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [stockCode]);

  if (loading) return (
    <div className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2.5 flex items-center gap-2">
      <div className="w-3 h-3 border border-blue-400 border-t-transparent rounded-full animate-spin" />
      <span className="text-[10px] text-gray-400">CCASS 机构持仓数据爬取中（首次约30秒）...</span>
    </div>
  );
  if (!ccasData || (!ccasData.top_increases.length && !ccasData.top_decreases.length)) return null;

  const formatShares = (n: number) => {
    const abs = Math.abs(n);
    if (abs >= 10000) return `${(n / 10000).toFixed(1)}万`;
    return n.toLocaleString();
  };

  // 汇总计算
  const totalIncrease = ccasData.top_increases.reduce((s, i) => s + i.change, 0);
  const totalDecrease = ccasData.top_decreases.reduce((s, i) => s + i.change, 0);
  const netChange = totalIncrease + totalDecrease;  // decrease is negative

  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2.5">
      <div
        className="flex items-center justify-between cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2 text-[11px]">
          <span className="text-sm">🏛️</span>
          <span className="font-medium text-gray-700">CCASS 机构持仓变化</span>
          <span className="text-[9px] text-gray-400">
            ({ccasData.latest_date} vs {ccasData.compare_date} · T+1)
          </span>
        </div>
        <div className="flex items-center gap-2">
          {/* 折叠状态也显示净变化 */}
          <span className={`text-[10px] font-bold ${netChange >= 0 ? 'text-red-600' : 'text-emerald-600'}`}>
            净{netChange >= 0 ? '增' : '减'} {formatShares(Math.abs(netChange))}
          </span>
          <span className="text-gray-400 text-xs">{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {expanded && (
        <div className="mt-2">
          <div className="grid grid-cols-2 gap-3 text-[10px]">
            {/* 增持 */}
            <div>
              <div className="text-red-500 font-medium mb-1">📈 增持 TOP</div>
              {ccasData.top_increases.slice(0, 5).map((item, i) => (
                <div key={i} className="flex items-center justify-between py-0.5 border-b border-gray-100">
                  <span className="text-gray-600 truncate flex-1">{item.name.substring(0, 25)}</span>
                  <span className="text-red-600 font-mono shrink-0 ml-1">+{formatShares(item.change)}</span>
                </div>
              ))}
            </div>
            {/* 减持 */}
            <div>
              <div className="text-emerald-600 font-medium mb-1">📉 减持 TOP</div>
              {ccasData.top_decreases.slice(0, 5).map((item, i) => (
                <div key={i} className="flex items-center justify-between py-0.5 border-b border-gray-100">
                  <span className="text-gray-600 truncate flex-1">{item.name.substring(0, 25)}</span>
                  <span className="text-emerald-600 font-mono shrink-0 ml-1">{formatShares(item.change)}</span>
                </div>
              ))}
            </div>
          </div>
          {/* 汇总行 */}
          <div className="mt-2 pt-2 border-t border-gray-200 flex items-center justify-between text-[10px]">
            <div className="flex gap-4">
              <span>增持合计: <b className="text-red-600">+{formatShares(totalIncrease)}</b></span>
              <span>减持合计: <b className="text-emerald-600">{formatShares(totalDecrease)}</b></span>
            </div>
            <span className={`font-bold text-xs ${netChange >= 0 ? 'text-red-600' : 'text-emerald-600'}`}>
              净变化: {netChange >= 0 ? '+' : ''}{formatShares(netChange)}
            </span>
          </div>
        </div>
      )}

      {!expanded && (
        <div className="mt-1 text-[9px] text-gray-400 flex gap-3">
          {ccasData.top_increases.length > 0 && (
            <span>增持最多: <b className="text-red-500">{ccasData.top_increases[0].name.substring(0, 15)}</b> +{formatShares(ccasData.top_increases[0].change)}</span>
          )}
          {ccasData.top_decreases.length > 0 && (
            <span>减持最多: <b className="text-emerald-600">{ccasData.top_decreases[0].name.substring(0, 15)}</b> {formatShares(ccasData.top_decreases[0].change)}</span>
          )}
        </div>
      )}
    </div>
  );
}

// ==================== 资金动能信号条 ====================

const SIGNAL_STYLES: Record<string, { bg: string; text: string; icon: string; border: string }> = {
  bullish:  { bg: 'bg-red-50',    text: 'text-red-700',     icon: '🔴', border: 'border-red-200' },
  warning:  { bg: 'bg-amber-50',  text: 'text-amber-700',   icon: '🟡', border: 'border-amber-200' },
  bearish:  { bg: 'bg-emerald-50', text: 'text-emerald-700', icon: '🟢', border: 'border-emerald-200' },
  neutral:  { bg: 'bg-gray-50',   text: 'text-gray-600',    icon: '⚪', border: 'border-gray-200' },
};

function FlowMomentumBadge({ summary }: { summary: FlowSummary | null }) {
  if (!summary) return null;

  const s = SIGNAL_STYLES[summary.signal] || SIGNAL_STYLES.neutral;
  const fmtAmt = (v: number) => {
    const abs = Math.abs(v);
    if (abs >= 10000) return `${(v / 10000).toFixed(1)}亿`;
    return `${v.toFixed(0)}万`;
  };
  const mcSign = summary.momentum_change >= 0 ? '+' : '';

  return (
    <div className={`flex items-center justify-between px-3 py-2 rounded-lg border ${s.bg} ${s.border} transition-all`}>
      {/* 左侧：动能标签 */}
      <div className="flex items-center gap-2">
        <span className="text-sm">{s.icon}</span>
        <span className={`text-sm font-bold ${s.text}`}>
          {summary.momentum_label}
        </span>
        <span className="text-[10px] text-gray-400">
          后半段{mcSign}{summary.momentum_change}%
        </span>
      </div>

      {/* 右侧：关键指标 */}
      <div className="flex items-center gap-3 text-[11px]">
        <span className={summary.cum_net >= 0 ? 'text-red-600' : 'text-emerald-600'}>
          累计 {summary.cum_net >= 0 ? '+' : ''}{fmtAmt(summary.cum_net)}
        </span>
        <span className="text-gray-400">|</span>
        <span className={summary.buy_sell_ratio >= 1 ? 'text-red-500' : 'text-emerald-500'}>
          买卖比 {summary.buy_sell_ratio.toFixed(2)}
        </span>
        <span className="text-gray-400">|</span>
        <span className={summary.recent_net >= 0 ? 'text-red-500' : 'text-emerald-500'}>
          近5分 {summary.recent_net >= 0 ? '+' : ''}{fmtAmt(summary.recent_net)}
        </span>
      </div>
    </div>
  );
}

// ==================== 主组件 ====================

interface IntradayLevelsPanelProps {
  stockCode: string;
  stockName: string;
  onClose: () => void;
  onBrokerAnalysis?: (analysis: BrokerAnalysis | null) => void;
  showClose?: boolean;
}

export function IntradayLevelsPanel({
  stockCode,
  stockName,
  onClose,
  onBrokerAnalysis,
  showClose = true,
}: IntradayLevelsPanelProps) {
  const [data, setData] = useState<IntradayLevelsData | null>(null);
  const [flowData, setFlowData] = useState<CapitalFlowTimelinePoint[]>([]);
  const [flowSummary, setFlowSummary] = useState<FlowSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [levelsRes, flowRes] = await Promise.all([
        getIntradayLevels(stockCode),
        getCapitalFlowTimeline(stockCode)
      ]);

      if (levelsRes.success && levelsRes.data) {
        setData(levelsRes.data);
        setError(null);
        onBrokerAnalysis?.(levelsRes.data.broker_analysis ?? null);
      } else {
        setError(levelsRes.message || "暂无数据");
      }

      if (flowRes.success && flowRes.data) {
        setFlowData(flowRes.data.timeline || []);
        setFlowSummary(flowRes.data.summary || null);
      }
    } catch (err) {
      console.error("获取日内支撑/阻力位失败:", err);
      setError("获取数据失败");
    } finally {
      setLoading(false);
    }
  }, [stockCode]);

  // 初始加载 + 30秒轮询
  useEffect(() => {
    setLoading(true);
    setData(null);
    setError(null);
    fetchData();

    timerRef.current = setInterval(fetchData, 30_000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [stockCode, fetchData]);

  const hasData =
    data &&
    (data.support_levels.length > 0 || data.resistance_levels.length > 0);

  return (
    <div className="mt-4 bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden animate-in slide-in-from-top-2">
      {/* 头部 */}
      <div className="flex items-center justify-between px-4 py-3 bg-gradient-to-r from-blue-50 to-indigo-50 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <span className="text-lg">📊</span>
          <h3 className="text-sm font-bold text-gray-800">
            {stockName}
            <span className="ml-1.5 text-xs font-normal text-gray-400">
              {stockCode}
            </span>
          </h3>
          <span className="text-xs text-gray-400">— 日内资金支撑/阻力位</span>
        </div>
        <div className="flex items-center gap-2">
          {data && (
            <span className="text-[10px] text-gray-400">
              更新于{" "}
              {new Date(data.updated_at).toLocaleTimeString("zh-CN", {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              })}
            </span>
          )}
          {showClose && (
            <button
              onClick={onClose}
              className="w-6 h-6 rounded-full bg-gray-200 hover:bg-gray-300 flex items-center justify-center text-gray-500 hover:text-gray-700 transition-colors text-xs"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* 内容 */}
      <div className="px-4 py-3">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            <span className="ml-3 text-sm text-gray-400">分析中...</span>
          </div>
        ) : error ? (
          <div className="text-center py-6 text-sm text-gray-400">{error}</div>
        ) : !hasData ? (
          <div className="text-center py-6 text-sm text-gray-400">
            暂无足够逐笔成交数据，无法计算支撑/阻力位
          </div>
        ) : (
          <div className="space-y-3">
            {/* 动能信号条 */}
            <FlowMomentumBadge summary={flowSummary} />

            {/* 上部：主力 vs 散户资金流走势图（全宽） */}
            <div className="bg-gray-50/50 rounded-lg border border-gray-100">
              <CapitalFlowChartDyn data={flowData} height={340} />
            </div>




            {/* 下部：支撑/阻力位（左右两栏） */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {/* 阻力位 */}
              <div className="space-y-1">
                {data!.resistance_levels.length > 0 && (
                  <>
                    <div className="text-[10px] text-red-400 font-medium px-3 uppercase tracking-wider">
                      ── 阻力位 ──
                    </div>
                    {[...data!.resistance_levels]
                      .sort((a, b) => b.price - a.price)
                      .map((level, i) => (
                        <LevelRow key={`r-${i}`} level={level} side="resistance" />
                      ))}
                  </>
                )}
              </div>

              {/* 支撑位 + 当前价 + POC */}
              <div className="space-y-1">
                {data!.current_price > 0 && (
                  <PriceDivider currentPrice={data!.current_price} vwap={data!.vwap} />
                )}
                {data!.poc && (
                  <div className="flex items-center gap-2 px-3 py-1 bg-amber-50 rounded-lg">
                    <span className="text-xs">⭐</span>
                    <span className="text-[11px] text-amber-700 font-medium">
                      POC {formatPrice(data!.poc.price)}
                    </span>
                    <span className="text-[10px] text-amber-500">
                      成交量聚集点 · {formatVolume(data!.poc.volume)}
                    </span>
                  </div>
                )}
                {data!.support_levels.length > 0 && (
                  <>
                    <div className="text-[10px] text-emerald-500 font-medium px-3 mt-1 uppercase tracking-wider">
                      ── 支撑位 ──
                    </div>
                    {[...data!.support_levels]
                      .sort((a, b) => b.price - a.price)
                      .map((level, i) => (
                        <LevelRow key={`s-${i}`} level={level} side="support" />
                      ))}
                  </>
                )}
              </div>
            </div>

            {/* CCASS 机构持仓变化（T+1） */}
            <CCASSection stockCode={stockCode} />
          </div>
        )}
      </div>

      {/* 底部提示 */}
      <div className="px-4 py-2 bg-gray-50 border-t border-gray-100 flex items-center justify-between text-[10px] text-gray-400">
        <span>数据来源: 逐笔成交 + 盘口10档 · 30秒自动刷新</span>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-emerald-400 inline-block" />
            支撑
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-red-400 inline-block" />
            阻力
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-amber-400 inline-block" />
            POC
          </span>
        </div>
      </div>
    </div>
  );
}
