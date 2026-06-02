// 买入前快速检查页面 — 实时推荐 + 单股检查
"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Search, TrendingUp, TrendingDown, RefreshCw, Sparkles, BarChart3, ShieldCheck, Activity } from "lucide-react";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { AIAnalysisButton, AIAnalysisDialog } from "@/app/components/AIAnalysisDialog";

// ==================== 类型定义 ====================

interface CheckItem {
  name: string;
  status: "GOOD" | "DANGER" | "WARNING" | "NEUTRAL";
  detail: string;
  impact: string;
}

interface FlowSignal {
  rule_id: string;
  rule_name: string;
  signal_type: string;
  price: number;
  reason: string;
  confidence: number;
  priority: string;
  created_at: string;
}

interface BigOrderSummary {
  big_buy_count: number;
  big_sell_count: number;
  big_buy_amount: number;
  big_sell_amount: number;
  buy_sell_ratio: number;
  order_strength: number;
  snapshot_time: string;
}

interface HoldingStrategy {
  type: string;
  label: string;
  icon: string;
  color: string;
  reason: string;
  detail: string;
}

interface CheckResult {
  stock_code: string;
  stock_name: string;
  verdict: "GO" | "CAUTION" | "STOP" | "UNKNOWN";
  verdict_reason: string;
  score: number;
  checks: CheckItem[];
  capital_flow_signals: FlowSignal[];
  big_order_summary: BigOrderSummary | null;
  trade_signals: Array<{
    signal_type: string;
    price: number;
    strategy: string;
    condition: string;
    time: string;
  }>;
  warnings: string[];
  holding_strategy: HoldingStrategy | null;
}

interface Recommendation {
  stock_code: string;
  stock_name: string;
  score: number;
  action: string;
  reasons: string[];
  holding_type: string;
  big_order: { buy_sell_ratio: number; order_strength: number } | null;
  latest_signal_time: string;
}

interface RecommendationsData {
  buy_recommendations: Recommendation[];
  sell_recommendations: Recommendation[];
  total_signals: number;
  generated_at: string;
}

interface PatternSummary {
  stock_code: string;
  stock_name: string;
  buy_price: number;
  buy_time: string;
  pattern_type: string;
  drop_from_peak: number;
  kline_position: number;
  volume_ratio: number;
  post_buy_rise?: {
    max_rise_3d: number;
    day1_change: number;
  };
}

interface SimilarStock {
  stock_code: string;
  stock_name: string;
  similarity_score: number;
  score?: number;
  stage: string;
  pattern_id?: string;
  pattern_name?: string;
  pattern_color?: string;
  reasons?: string[];
  matched_patterns: string[];
  current_metrics: {
    name?: string;
    kline_position?: number;
    drop_from_peak?: number;
    last_price?: number;
    today_change?: number;
    change_5d?: number;
    capital_score?: number;
    net_inflow_ratio?: number;
  };
}

interface PatternData {
  trade_patterns: PatternSummary[];
  similar_stocks: SimilarStock[];
  pattern_summary?: Record<string, number>;
  analyzed_at: string;
  message?: string;
}

const PATTERN_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  A: { bg: "bg-red-50 dark:bg-red-500/10", border: "border-red-200 dark:border-red-500/40", text: "text-red-600" },
  B: { bg: "bg-blue-50 dark:bg-blue-500/10", border: "border-blue-200 dark:border-blue-500/40", text: "text-blue-600" },
  C: { bg: "bg-emerald-50 dark:bg-emerald-500/10", border: "border-emerald-200 dark:border-emerald-500/40", text: "text-emerald-600" },
  D: { bg: "bg-orange-50", border: "border-orange-200", text: "text-orange-600" },
};

// ==================== 常量 ====================

const VERDICT_CONFIG = {
  GO: { bg: "bg-emerald-50", border: "border-emerald-300", text: "text-emerald-700", icon: "✅", label: "可以买入" },
  CAUTION: { bg: "bg-amber-50", border: "border-amber-300", text: "text-amber-700", icon: "⚠️", label: "谨慎观望" },
  STOP: { bg: "bg-red-50", border: "border-red-300", text: "text-red-700", icon: "🛑", label: "不建议买入" },
  UNKNOWN: { bg: "bg-gray-50", border: "border-gray-300", text: "text-gray-600", icon: "❓", label: "未知" },
};

const STATUS_COLORS: Record<string, string> = {
  GOOD: "text-emerald-600", DANGER: "text-red-600", WARNING: "text-amber-600", NEUTRAL: "text-gray-500",
};

const STATUS_ICONS: Record<string, string> = {
  GOOD: "✅", DANGER: "❌", WARNING: "⚠️", NEUTRAL: "➖",
};

const HOLDING_LABELS: Record<string, { icon: string; label: string; color: string }> = {
  trailing_stop: { icon: "🏦", label: "移动止盈", color: "text-emerald-400" },
  swing: { icon: "📈", label: "短线持有", color: "text-blue-400" },
  scalp_only: { icon: "⚡", label: "超短线", color: "text-amber-400" },
};

// ==================== 推荐卡片组件 ====================

function RecCard({ rec, onClick }: { rec: Recommendation; onClick: () => void }) {
  const isBuy = rec.action === "BUY";
  const strength = rec.big_order?.order_strength ?? 0;
  const ht = HOLDING_LABELS[rec.holding_type];

  return (
    <button
      onClick={onClick}
      className={`w-full text-left p-3 rounded-lg border transition-all hover:scale-[1.01] ${
        isBuy
          ? "bg-emerald-50 border-emerald-500/20 hover:border-emerald-500/50"
          : "bg-red-50 border-red-500/20 hover:border-red-500/50"
      }`}
    >
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className={`text-sm font-bold ${isBuy ? "text-emerald-400" : "text-red-400"}`}>
            {rec.stock_name}
          </span>
          <span className="text-xs text-gray-500">{rec.stock_code}</span>
        </div>
        <div className="flex items-center gap-2">
          {ht && <span className={`text-xs ${ht.color}`}>{ht.icon}{ht.label}</span>}
          <span className={`text-xs font-bold px-2 py-0.5 rounded ${
            isBuy ? "bg-emerald-100 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-400" : "bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400"
          }`}>
            {rec.score}分
          </span>
          <AIAnalysisButton stockCode={rec.stock_code} stockName={rec.stock_name} />
        </div>
      </div>
      <div className="flex items-center justify-between">
        <div className="flex flex-wrap gap-1">
          {rec.reasons.slice(0, 3).map((r, i) => (
            <span key={i} className="text-xs text-gray-400">{r}</span>

          ))}
        </div>
        {strength !== 0 && (
          <span className={`text-xs font-mono ${
            strength >= 0.2 ? "text-emerald-400" : strength <= -0.2 ? "text-red-400" : "text-gray-500"
          }`}>
            str:{strength.toFixed(2)}
          </span>
        )}
      </div>
      <div className="text-[10px] text-gray-600 mt-1">
        {rec.latest_signal_time?.split(" ")[1]?.slice(0, 5) || ""}
      </div>
    </button>
  );
}

// ==================== 主页面 ====================

export default function PreTradeCheckPage() {
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CheckResult | null>(null);
  const [error, setError] = useState("");
  const [recs, setRecs] = useState<RecommendationsData | null>(null);
  const [recsLoading, setRecsLoading] = useState(true);
  const [patterns, setPatterns] = useState<PatternData | null>(null);
  const [patternsLoading, setPatternsLoading] = useState(true);
  const inputRef = useRef<HTMLInputElement>(null);
  const searchParams = useSearchParams();

  // URL参数自动检查（从 Dashboard 信号流点击进来）
  useEffect(() => {
    const urlCode = searchParams.get("code");
    if (urlCode && !code) {
      setCode(urlCode);
      doCheck(urlCode);
    }
  }, [searchParams]); // eslint-disable-line react-hooks/exhaustive-deps

  // 加载推荐列表
  const loadRecs = useCallback(async () => {
    try {
      const res = await fetch("/api/pre-trade-check/recommendations");
      const json = await res.json();
      if (json.success && json.data) {
        setRecs(json.data);
      }
    } catch {
      // silent
    } finally {
      setRecsLoading(false);
    }
  }, []);

  // 加载模式匹配数据
  const loadPatterns = useCallback(async () => {
    try {
      const res = await fetch("/api/trade-pattern/similar-stocks");
      const json = await res.json();
      if (json.success && json.data) {
        setPatterns(json.data);
      }
    } catch {
      // silent
    } finally {
      setPatternsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRecs();
    loadPatterns();
    const timer = setInterval(loadRecs, 30000); // 30秒刷新
    return () => clearInterval(timer);
  }, [loadRecs, loadPatterns]);

  // 单股检查
  const doCheck = useCallback(async (stockCode: string) => {
    if (!stockCode.trim()) return;
    const cleaned = stockCode.trim().toUpperCase();
    setLoading(true);
    setError("");
    setResult(null);

    try {
      const res = await fetch(`/api/pre-trade-check/${cleaned}`);
      const json = await res.json();
      if (json.success && json.data) {
        setResult(json.data);
      } else {
        setError(json.message || "检查失败");
      }
    } catch {
      setError("网络错误，请确认后端服务是否运行");
    } finally {
      setLoading(false);
    }
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    doCheck(code);
  };

  const handleRecClick = (rec: Recommendation) => {
    setCode(rec.stock_code);
    doCheck(rec.stock_code);
  };

  const v = result ? VERDICT_CONFIG[result.verdict] : null;

  return (
    <div className="min-h-screen bg-[#f0f2f5] dark:bg-[#0a0a0f] text-gray-900 dark:text-gray-100">
      <div className="max-w-[1600px] mx-auto px-3 md:px-6 py-4 md:py-6">
        {/* 页面标题栏 */}
        <div className="flex items-center justify-between mb-4 md:mb-6">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600
                          flex items-center justify-center shadow-lg shadow-blue-500/20">
              <Activity className="w-4 h-4 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-semibold tracking-tight text-gray-900 dark:text-white">交易决策中心</h1>
              <p className="text-xs text-gray-500 dark:text-gray-400">实时推荐 · 模式匹配 · 买入前检查</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {recs && (
              <>
                <Badge variant="outline" className="text-[10px] text-gray-500 dark:text-gray-400 border-gray-300 dark:border-gray-600 font-normal">
                  {recs.total_signals} 只有信号
                </Badge>
                <Badge variant="outline" className="text-[10px] text-gray-500 dark:text-gray-400 border-gray-300 dark:border-gray-600 font-normal">
                  {recs.generated_at?.split("T")[1]?.slice(0, 5)}
                </Badge>
              </>
            )}
          </div>
        </div>

        {/* ═══ 双列布局：左=推荐+模式 | 右=检查结果(sticky) ═══ */}
        <div className="grid grid-cols-1 xl:grid-cols-5 gap-4 md:gap-6">
          {/* 左列：推荐 + 模式匹配 (3/5) */}
          <div className="xl:col-span-3 space-y-4 md:space-y-6">

        {/* ===== KPI 概览卡片 ===== */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
          <div className="bg-white dark:bg-gray-900 rounded-xl md:rounded-2xl border border-gray-200 dark:border-gray-800 p-3 md:p-5 shadow-sm">
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">买入推荐</p>
            <p className="text-2xl md:text-3xl font-bold text-emerald-600 dark:text-emerald-400 tabular-nums">
              {recs?.buy_recommendations.length ?? "—"}
            </p>
          </div>
          <div className="bg-white dark:bg-gray-900 rounded-xl md:rounded-2xl border border-gray-200 dark:border-gray-800 p-3 md:p-5 shadow-sm">
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">卖出推荐</p>
            <p className="text-2xl md:text-3xl font-bold text-red-600 dark:text-red-400 tabular-nums">
              {recs?.sell_recommendations.length ?? "—"}
            </p>
          </div>
          <div className="bg-white dark:bg-gray-900 rounded-xl md:rounded-2xl border border-gray-200 dark:border-gray-800 p-3 md:p-5 shadow-sm">
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">模式匹配</p>
            <p className="text-2xl md:text-3xl font-bold text-blue-600 dark:text-blue-400 tabular-nums">
              {patterns?.similar_stocks.length ?? "—"}
            </p>
          </div>
          <div className="bg-white dark:bg-gray-900 rounded-xl md:rounded-2xl border border-gray-200 dark:border-gray-800 p-3 md:p-5 shadow-sm">
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">参考案例</p>
            <p className="text-2xl md:text-3xl font-bold text-gray-900 dark:text-white tabular-nums">
              {patterns?.trade_patterns.length ?? "—"}
            </p>
          </div>
        </div>

        {/* ===== 上半部分：实时推荐 ===== */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-6">
          {/* BUY 推荐 */}
          <Card className="bg-white dark:bg-gray-900 border-gray-200 dark:border-gray-800 shadow-sm hover:shadow-md transition-shadow">
            <CardHeader className="pb-3 pt-5 px-5">
              <CardTitle className="text-sm font-medium text-gray-800 dark:text-gray-200 flex items-center gap-2">
                <div className="w-6 h-6 rounded-lg bg-emerald-500/10 flex items-center justify-center">
                  <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
                </div>
                适合买入
                {recs && (
                  <Badge className="bg-emerald-500/10 text-emerald-400 border-0 text-[10px] font-normal">
                    {recs.buy_recommendations.length}
                  </Badge>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className="px-5 pb-5">
              {recsLoading ? (
                <div className="text-center py-10 text-gray-400 dark:text-gray-500">
                  <RefreshCw className="w-4 h-4 mx-auto mb-2 animate-spin" />
                  <span className="text-xs">加载中...</span>
                </div>
              ) : recs && recs.buy_recommendations.length > 0 ? (
                <div className="space-y-2 max-h-[320px] overflow-y-auto pr-1
                              [&::-webkit-scrollbar]:w-1 [&::-webkit-scrollbar-thumb]:rounded-full
                              [&::-webkit-scrollbar-thumb]:bg-gray-300 dark:[&::-webkit-scrollbar-thumb]:bg-gray-600">
                  {recs.buy_recommendations.map((rec) => (
                    <RecCard key={rec.stock_code} rec={rec} onClick={() => handleRecClick(rec)} />
                  ))}
                </div>
              ) : (
                <div className="text-center py-3 text-gray-400 dark:text-gray-600 text-xs italic">暂无实时买入推荐</div>
              )}
            </CardContent>
          </Card>

          {/* SELL 推荐 */}
          <Card className="bg-white dark:bg-gray-900 border-gray-200 dark:border-gray-800 shadow-sm hover:shadow-md transition-shadow">
            <CardHeader className="pb-3 pt-5 px-5">
              <CardTitle className="text-sm font-medium text-gray-800 dark:text-gray-200 flex items-center gap-2">
                <div className="w-6 h-6 rounded-lg bg-red-500/10 flex items-center justify-center">
                  <TrendingDown className="w-3.5 h-3.5 text-red-400" />
                </div>
                建议卖出
                {recs && (
                  <Badge className="bg-red-500/10 text-red-400 border-0 text-[10px] font-normal">
                    {recs.sell_recommendations.length}
                  </Badge>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className="px-5 pb-5">
              {recsLoading ? (
                <div className="text-center py-10 text-gray-400 dark:text-gray-500">
                  <RefreshCw className="w-4 h-4 mx-auto mb-2 animate-spin" />
                  <span className="text-xs">加载中...</span>
                </div>
              ) : recs && recs.sell_recommendations.length > 0 ? (
                <div className="space-y-2 max-h-[320px] overflow-y-auto pr-1
                              [&::-webkit-scrollbar]:w-1 [&::-webkit-scrollbar-thumb]:rounded-full
                              [&::-webkit-scrollbar-thumb]:bg-gray-300 dark:[&::-webkit-scrollbar-thumb]:bg-gray-600">
                  {recs.sell_recommendations.map((rec) => (
                    <RecCard key={rec.stock_code} rec={rec} onClick={() => handleRecClick(rec)} />
                  ))}
                </div>
              ) : (
                <div className="text-center py-3 text-gray-400 dark:text-gray-600 text-xs italic">暂无卖出推荐</div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* ===== 中间部分：历史模式匹配 ===== */}
        <Card className="bg-white dark:bg-gray-900 border-gray-200 dark:border-gray-800 shadow-sm hover:shadow-md transition-shadow">
          <CardHeader className="pb-3 pt-5 px-5">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium text-gray-800 dark:text-gray-200 flex items-center gap-2">
                <div className="w-6 h-6 rounded-lg bg-purple-500/10 flex items-center justify-center">
                  <Sparkles className="w-3.5 h-3.5 text-purple-400" />
                </div>
                历史买入模式匹配
                {patterns && (
                  <Badge className="bg-purple-500/10 text-purple-400 border-0 text-[10px] font-normal">
                    {patterns.similar_stocks.length} 只匹配
                  </Badge>
                )}
              </CardTitle>
              <div className="flex items-center gap-2">
              {patterns && (
                <span className="text-[10px] text-gray-600">
                  基于 {patterns.trade_patterns.length} 个历史买入模式
                </span>
              )}
              <button
                onClick={loadPatterns}
                className="text-xs text-purple-400 hover:text-purple-300 px-3 py-1.5
                           border border-gray-700 rounded-lg hover:border-purple-500/30
                           hover:bg-purple-500/5 transition-all flex items-center gap-1.5"
              >
                <RefreshCw className="w-3 h-3" />
                刷新
              </button>
            </div>
            </div>
          </CardHeader>
          <CardContent className="px-5 pb-5">
          {patternsLoading ? (
            <div className="text-center py-10 text-gray-400 dark:text-gray-500">
              <RefreshCw className="w-4 h-4 mx-auto mb-2 animate-spin" />
              <span className="text-xs">分析历史交易模式中...</span>
            </div>
          ) : patterns && patterns.similar_stocks.length > 0 ? (
            <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1
                          [&::-webkit-scrollbar]:w-1 [&::-webkit-scrollbar-thumb]:rounded-full
                          [&::-webkit-scrollbar-thumb]:bg-gray-300 dark:[&::-webkit-scrollbar-thumb]:bg-gray-600">
              {patterns.similar_stocks.map((stock) => {
                const pc = PATTERN_COLORS[stock.pattern_id || "B"] || PATTERN_COLORS.B;
                const m = stock.current_metrics;
                const displayScore = stock.score ?? stock.similarity_score;
                const posLabel = m.kline_position != null
                  ? m.kline_position <= 0.3 ? "低位" : m.kline_position >= 0.7 ? "高位" : "中位"
                  : "";
                const posColor = m.kline_position != null
                  ? m.kline_position <= 0.3 ? "text-emerald-700" : m.kline_position >= 0.7 ? "text-red-600" : "text-gray-600"
                  : "text-gray-500";

                return (
                  <button
                    key={stock.stock_code}
                    onClick={() => {
                      setCode(stock.stock_code);
                      doCheck(stock.stock_code);
                    }}
                    className={`w-full text-left px-4 py-3.5 rounded-xl border transition-all duration-200
                               hover:shadow-md group relative overflow-hidden
                               bg-white dark:bg-gray-900/60 hover:bg-gray-50/50 dark:hover:bg-gray-800/60
                               ${pc.border} hover:border-opacity-60`}
                  >
                    {/* 左侧渐变条 */}
                    <div className={`absolute left-0 top-3 bottom-3 w-[3px] rounded-full ${
                      stock.pattern_id === "A" ? "bg-gradient-to-b from-red-400 to-red-600" :
                      stock.pattern_id === "C" ? "bg-gradient-to-b from-emerald-400 to-emerald-600" :
                      stock.pattern_id === "D" ? "bg-gradient-to-b from-orange-400 to-orange-600" :
                      "bg-gradient-to-b from-blue-400 to-blue-600"
                    }`} />

                    <div className="pl-3 flex items-center justify-between">
                      {/* 左侧：名称 + 代码 + 关键信息 */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-sm font-semibold text-gray-900 dark:text-white truncate">
                            {stock.stock_name}
                          </span>
                          <span className="text-[11px] text-gray-400 font-mono flex-shrink-0">{stock.stock_code}</span>
                          <Badge className={`text-[10px] px-1.5 py-0 h-[18px] font-medium border-0 flex-shrink-0 ${pc.bg} ${pc.text}`}>
                            {stock.pattern_name || stock.stage}
                          </Badge>
                        </div>
                        {/* 价格行：简洁展示 */}
                        <div className="flex items-center gap-3 text-[12px] text-gray-500 dark:text-gray-400">
                          {m.last_price != null && (
                            <span className="font-medium text-gray-700 dark:text-gray-300">
                              ${m.last_price.toFixed(2)}
                            </span>
                          )}
                          {m.today_change != null && (
                            <span className={m.today_change >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}>
                              今日 {m.today_change >= 0 ? "+" : ""}{m.today_change.toFixed(1)}%
                            </span>
                          )}
                          {m.change_5d != null && (
                            <span className={m.change_5d >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}>
                              5日 {m.change_5d >= 0 ? "+" : ""}{m.change_5d.toFixed(1)}%
                            </span>
                          )}
                          {posLabel && (
                            <span className="text-gray-400">{posLabel}</span>
                          )}
                        </div>
                        {/* 原因标签（最多3个） */}
                        {stock.reasons && stock.reasons.length > 0 && (
                          <div className="mt-1.5 flex flex-wrap gap-1">
                            {stock.reasons.slice(0, 3).map((r, i) => (
                              <span key={i} className={`text-[10px] px-1.5 py-0.5 rounded-full ${pc.bg} ${pc.text}`}>
                                {r}
                              </span>
                            ))}
                            {stock.reasons.length > 3 && (
                              <span className="text-[10px] text-gray-400">+{stock.reasons.length - 3}</span>
                            )}
                          </div>
                        )}
                      </div>

                      {/* 右侧：分数 */}
                      <div className={`text-2xl font-bold tabular-nums ml-4 flex-shrink-0 ${
                        displayScore >= 100 ? "text-emerald-600 dark:text-emerald-400" :
                        displayScore >= 80 ? "text-blue-600 dark:text-blue-400" :
                        displayScore >= 60 ? "text-amber-600 dark:text-amber-400" : "text-gray-400"
                      }`}>
                        {displayScore}
                        <span className="text-[10px] font-normal text-gray-400 ml-0.5">分</span>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="text-center py-10 text-gray-400 dark:text-gray-500 text-sm">
              {patterns?.message || "暂无匹配到类似模式的股票"}
            </div>
          )}

          {/* 历史买入模式摘要（默认展开） */}
          {patterns && patterns.trade_patterns.length > 0 && (
            <details open className="mt-6 border-t border-gray-100 dark:border-gray-800 pt-5">
              <summary className="text-[11px] text-gray-400 cursor-pointer hover:text-white/60 transition-colors">
                📋 参考案例：{patterns.trade_patterns.length} 个成功买入记录
              </summary>
              <div className="mt-2 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                {patterns.trade_patterns.map((p, i) => (
                  <div key={i} className="bg-gray-50 dark:bg-gray-800/50 rounded-lg p-2 border border-gray-100 dark:border-gray-700 text-[11px]">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-gray-800 dark:text-gray-200 font-medium">
                        {p.stock_name} <span className="text-gray-500">{p.stock_code}</span>
                      </span>
                      <span className="text-purple-400">{p.pattern_type}</span>
                    </div>
                    <div className="text-gray-500 flex items-center gap-2 flex-wrap">
                      <span>买入价 ${p.buy_price?.toFixed(2)}</span>
                      <span>·</span>
                      <span>距高点 -{p.drop_from_peak?.toFixed(1)}%</span>
                      <span>·</span>
                      <span>位置 {((p.kline_position ?? 0) * 100).toFixed(0)}%</span>
                      {p.post_buy_rise && (
                        <>
                          <span>·</span>
                          <span className="text-emerald-500">
                            次日{p.post_buy_rise.day1_change >= 0 ? "+" : ""}{p.post_buy_rise.day1_change}%
                          </span>
                          <span>·</span>
                          <span className="text-emerald-400">
                            3日最高+{p.post_buy_rise.max_rise_3d}%
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </details>
          )}
          </CardContent>
        </Card>

          </div>{/* 左列结束 */}

          {/* 右列：买入检查 (2/5, sticky) */}
          <div className="xl:col-span-2">
            <div className="xl:sticky xl:top-4 space-y-4">

        {/* ===== 买入前检查 ===== */}
        <Card className="bg-white dark:bg-gray-900 border-gray-200 dark:border-gray-800 shadow-sm hover:shadow-md transition-shadow">
          <CardHeader className="pb-3 pt-5 px-5">
            <CardTitle className="text-sm font-medium text-gray-800 dark:text-gray-200 flex items-center gap-2 mb-3">
              <div className="w-6 h-6 rounded-lg bg-blue-500/10 flex items-center justify-center">
                <ShieldCheck className="w-3.5 h-3.5 text-blue-400" />
              </div>
              买入前检查
            </CardTitle>
          </CardHeader>
          <CardContent className="px-5 pb-5">
          <form onSubmit={handleSubmit} className="flex flex-col md:flex-row gap-2 md:gap-3 mb-4">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
              <input
                ref={inputRef}
                type="text"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="输入股票代码，如 01236 或 HK.01236"
                className="w-full bg-gray-50 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-xl pl-10 pr-4 py-2.5
                           focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100
                           placeholder-white/20 text-sm transition-all"
              />
            </div>
            <button
              type="submit"
              disabled={loading || !code.trim()}
              className="px-6 py-2.5 bg-blue-600 text-white
                         hover:bg-blue-500
                         disabled:bg-gray-200 dark:disabled:bg-gray-700
                         disabled:text-gray-400 dark:disabled:text-gray-500 rounded-xl font-medium text-sm
                         transition-all shadow-sm
                         hover:shadow-md active:scale-[0.98]"
            >
              {loading ? "检查中..." : "检查"}
            </button>
            {code.trim() && (
              <a
                href={`/stock-detail?code=${code.trim().includes('.') ? code.trim() : 'HK.' + code.trim()}`}
                target="_blank"
                rel="noopener noreferrer"
                className="px-4 py-2.5 rounded-xl font-medium text-sm
                           border border-gray-300 dark:border-gray-600
                           text-gray-600 dark:text-gray-300
                           hover:bg-gray-100 dark:hover:bg-gray-800
                           transition-all flex items-center gap-1.5"
              >
                <BarChart3 className="w-3.5 h-3.5" />
                个股分析
              </a>
            )}
          </form>

          {error && (
            <div className="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 rounded-lg p-3 mb-4 text-red-400 text-sm">
              {error}
            </div>
          )}

          {loading && (
            <div className="text-center py-12">
              <div className="text-3xl mb-3 animate-pulse">⏳</div>
              <p className="text-gray-400 text-sm">正在检查 {code}...</p>
            </div>
          )}

          {/* Result */}
          {result && v && (
            <div className="space-y-3">
              {/* Verdict + Score */}
              <div className={`${v.bg} border ${v.border} rounded-xl p-5`}>
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-3 mb-1">
                      <span className="text-3xl">{v.icon}</span>
                      <div>
                        <h2 className={`text-xl font-bold ${v.text}`}>
                          {result.stock_code} {result.stock_name}
                        </h2>
                        <p className={`text-base font-semibold ${v.text}`}>{v.label}</p>
                      </div>
                    </div>
                    <p className="text-gray-600 dark:text-gray-300 text-sm mt-1">{result.verdict_reason}</p>
                  </div>
                  <div className={`w-20 h-20 rounded-full border-4 ${v.border} flex items-center justify-center flex-shrink-0`}>
                    <div className="text-center">
                      <div className={`text-2xl font-bold ${v.text}`}>{result.score}</div>
                      <div className="text-[10px] text-gray-400">评分</div>
                    </div>
                  </div>
                </div>
              </div>
              {/* AI 深度分析按钮 */}
              <div className="mt-3 flex justify-center">
                <AIAnalysisButton stockCode={result.stock_code} stockName={result.stock_name} />
                <span className="text-xs text-gray-400 ml-2 self-center">点击 AI 分析获取 Gemini 买卖建议</span>
              </div>

              {/* Holding Strategy */}
              {result.holding_strategy && (() => {
                const hs = result.holding_strategy;
                const colorMap: Record<string, { bg: string; border: string; text: string }> = {
                  emerald: { bg: "bg-emerald-50 dark:bg-emerald-500/10", border: "border-emerald-200 dark:border-emerald-500/40", text: "text-emerald-400" },
                  blue: { bg: "bg-blue-50 dark:bg-blue-500/10", border: "border-blue-200 dark:border-blue-500/40", text: "text-blue-400" },
                  amber: { bg: "bg-amber-50 dark:bg-amber-500/10", border: "border-amber-200 dark:border-amber-500/40", text: "text-amber-400" },
                  red: { bg: "bg-red-50 dark:bg-red-500/10", border: "border-red-200 dark:border-red-500/40", text: "text-red-400" },
                };
                const c = colorMap[hs.color] || colorMap.amber;
                return (
                  <div className={`${c.bg} border ${c.border} rounded-lg p-3`}>
                    <div className="flex items-start gap-2">
                      <span className="text-xl">{hs.icon}</span>
                      <div>
                        <h3 className={`text-sm font-bold ${c.text}`}>持有建议：{hs.label}</h3>
                        <p className="text-xs text-gray-600 mt-0.5">{hs.reason}</p>
                        {hs.detail && <p className="text-xs text-gray-400 mt-0.5">{hs.detail}</p>}
                      </div>
                    </div>
                  </div>
                );
              })()}

              {/* Warnings */}
              {result.warnings.length > 0 && (
                <div className="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 rounded-lg p-3">
                  <h3 className="text-xs font-bold text-red-400 mb-1">⚠️ 风险预警</h3>
                  {result.warnings.map((w, i) => (
                    <div key={i} className="text-xs text-red-300">{w}</div>
                  ))}
                </div>
              )}

              {/* Checks */}
              <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-3">
                <h3 className="text-xs font-bold text-gray-300 mb-2">📋 检查项目</h3>
                <div className="space-y-1">
                  {result.checks.map((check, i) => (
                    <div key={i} className="flex items-center justify-between py-1.5 border-b border-gray-100 dark:border-gray-800 last:border-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm">{STATUS_ICONS[check.status]}</span>
                        <span className="text-xs text-gray-700 dark:text-gray-300">{check.name}</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className={`text-xs ${STATUS_COLORS[check.status]}`}>{check.detail}</span>
                        <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                          check.impact.startsWith("+") ? "bg-emerald-100 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-400" :
                          check.impact.startsWith("-") ? "bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400" :
                          "bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400"
                        }`}>
                          {check.impact}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Big Order + Flow Signals (collapsed by default) */}
              <details className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg">
                <summary className="p-3 text-xs font-bold text-gray-600 dark:text-gray-300 cursor-pointer hover:text-gray-100">
                  📊 详细数据（点击展开）
                </summary>
                <div className="p-3 pt-0 space-y-3">
                  {/* Big Order */}
                  {result.big_order_summary && (
                    <div>
                      <h4 className="text-xs text-gray-500 mb-2">大单实时数据</h4>
                      <div className="grid grid-cols-3 gap-3">
                        <div>
                          <div className="text-[10px] text-gray-400">强度</div>
                          <div className={`text-lg font-bold ${
                            result.big_order_summary.order_strength >= 0.2 ? "text-emerald-400" :
                            result.big_order_summary.order_strength <= -0.2 ? "text-red-400" : "text-amber-400"
                          }`}>{result.big_order_summary.order_strength.toFixed(2)}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-gray-400">买卖比</div>
                          <div className={`text-lg font-bold ${
                            result.big_order_summary.buy_sell_ratio >= 1.5 ? "text-emerald-400" :
                            result.big_order_summary.buy_sell_ratio <= 0.7 ? "text-red-400" : "text-amber-400"
                          }`}>{result.big_order_summary.buy_sell_ratio.toFixed(2)}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-gray-400">买/卖笔数</div>
                          <div className="text-lg font-bold">
                            <span className="text-emerald-400">{result.big_order_summary.big_buy_count}</span>
                            <span className="text-gray-300">/</span>
                            <span className="text-red-400">{result.big_order_summary.big_sell_count}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                  {/* Flow Signals */}
                  {result.capital_flow_signals.length > 0 && (
                    <div>
                      <h4 className="text-xs text-gray-500 dark:text-gray-400 mb-2">资金流信号</h4>
                      <div className="space-y-1.5">
                        {result.capital_flow_signals.map((sig, i) => (
                          <div key={i} className={`flex items-start gap-2 p-2.5 rounded-lg ${
                            sig.signal_type === "BUY" ? "bg-emerald-50 dark:bg-emerald-500/10" :
                            sig.signal_type === "SELL" ? "bg-red-50 dark:bg-red-500/10" : "bg-amber-50 dark:bg-amber-500/10"
                          }`}>
                            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                              sig.signal_type === "BUY" ? "bg-emerald-100 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-400" :
                              sig.signal_type === "SELL" ? "bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400" :
                              "bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-400"
                            }`}>{sig.signal_type}</span>
                            <div className="flex-1 min-w-0">
                              <span className="text-xs font-medium text-emerald-700 dark:text-emerald-300">{sig.rule_name}</span>
                              <span className="text-[10px] text-gray-500 ml-2">conf~{sig.confidence?.toFixed(2)}</span>
                              <p className="text-[10px] text-gray-600 dark:text-gray-400 mt-0.5 break-all">{sig.reason}</p>
                            </div>
                            <span className="text-[10px] text-gray-500 dark:text-gray-400 flex-shrink-0">{sig.created_at?.split(" ")[1]?.slice(0, 5)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </details>
            </div>
          )}
          </CardContent>
        </Card>

            </div>{/* sticky end */}
          </div>{/* 右列结束 */}
        </div>{/* grid end */}
      </div>
    </div>
  );
}
