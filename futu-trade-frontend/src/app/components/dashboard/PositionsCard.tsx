// 持仓摘要组件 — 含盘后操作建议

"use client";

import { useState, useEffect, useCallback } from "react";
import { Card } from "@/components/common";
import Link from "next/link";
import apiClient from "@/lib/api/client";

interface Position {
  stock_code: string;
  stock_name: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  market_value: number;
  profit_loss: number;
  profit_loss_pct: number;
}

interface PositionAdvice {
  stock_code: string;
  stock_name: string;
  action: string;       // HOLD | ADD | REDUCE | EXIT
  confidence: number;
  reasons: string[];
  stop_loss: number;
  take_profit: number;
  key_price: number;
  risk_level: string;
  summary: string;
  flow_pattern: string;
  flow_pattern_desc: string;
}

interface PositionsCardProps {
  positions: Position[];
  loading?: boolean;
}

// 操作建议标签配置
const ACTION_CONFIG: Record<string, { emoji: string; label: string; bg: string; text: string; border: string }> = {
  ADD:    { emoji: "🟢", label: "加仓", bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200" },
  HOLD:   { emoji: "🔵", label: "持有", bg: "bg-blue-50",    text: "text-blue-700",    border: "border-blue-200" },
  REDUCE: { emoji: "🟡", label: "减仓", bg: "bg-amber-50",   text: "text-amber-700",   border: "border-amber-200" },
  EXIT:   { emoji: "🔴", label: "清仓", bg: "bg-red-50",     text: "text-red-700",     border: "border-red-200" },
};

// 资金流模式配置
const FLOW_CONFIG: Record<string, { icon: string; text: string; color: string }> = {
  sustained_in:  { icon: "🔥", text: "", color: "text-red-600" },
  sustained_out: { icon: "💧", text: "", color: "text-green-600" },
  alternating:   { icon: "⚡", text: "交替进出", color: "text-yellow-600" },
};

export function PositionsCard({ positions, loading = false }: PositionsCardProps) {
  const [adviceMap, setAdviceMap] = useState<Record<string, PositionAdvice>>({});
  const [expandedCode, setExpandedCode] = useState<string | null>(null);
  const [adviceLoading, setAdviceLoading] = useState(false);
  const [aiResults, setAiResults] = useState<Record<string, {
    loading: boolean;
    data?: { action: string; confidence: number; reasoning: string; key_factors: string[]; risk_warning: string; target_price: number | null; stop_loss_price: number | null; time_horizon: string };
    error?: string;
  }>>({});

  // 加载操作建议
  const loadAdvice = useCallback(async () => {
    try {
      setAdviceLoading(true);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await apiClient.get("/trading/positions/advice");
      if (res.success && Array.isArray(res.data)) {
        const map: Record<string, PositionAdvice> = {};
        for (const a of res.data) {
          map[a.stock_code] = a;
        }
        setAdviceMap(map);
      }
    } catch (e) {
      console.debug("加载操作建议失败:", e);
    } finally {
      setAdviceLoading(false);
    }
  }, []);

  useEffect(() => {
    if (positions.length > 0) {
      loadAdvice();
    }
  }, [positions.length, loadAdvice]);

  // AI 分析持仓股
  const analyzePosition = async (stockCode: string) => {
    setAiResults(prev => ({ ...prev, [stockCode]: { loading: true } }));
    setExpandedCode(stockCode);
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await apiClient.post(`/ai-analysis/position/${stockCode}`);
      if (res.success && res.data) {
        setAiResults(prev => ({ ...prev, [stockCode]: { loading: false, data: res.data } }));
      } else {
        setAiResults(prev => ({ ...prev, [stockCode]: { loading: false, error: res.message || '分析失败' } }));
      }
    } catch (e) {
      setAiResults(prev => ({ ...prev, [stockCode]: { loading: false, error: '请求失败' } }));
    }
  };

  // 计算统计数据
  const totalMarketValue = positions.reduce((sum, pos) => sum + (pos.market_value ?? 0), 0);
  const totalProfitLoss = positions.reduce((sum, pos) => sum + (pos.profit_loss ?? 0), 0);
  const totalProfitLossPct = totalMarketValue > 0 ? (totalProfitLoss / (totalMarketValue - totalProfitLoss)) * 100 : 0;

  return (
    <Card>
      <div className="p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <svg className="w-5 h-5 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
            </svg>
            持仓摘要
          </h3>
          <Link
            href="/trading"
            className="text-sm text-blue-600 hover:text-blue-700 flex items-center gap-1"
          >
            查看全部
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </Link>
        </div>

        {loading ? (
          <div className="text-center py-8 text-gray-500">加载中...</div>
        ) : (
          <>
            {/* 统计卡片 */}
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div className="p-3 rounded-lg bg-blue-50 border border-blue-200">
                <div className="text-xs text-blue-600 mb-1">持仓数量</div>
                <div className="text-xl font-bold text-blue-700">{positions.length}</div>
              </div>
              <div className="p-3 rounded-lg bg-purple-50 border border-purple-200">
                <div className="text-xs text-purple-600 mb-1">总市值</div>
                <div className="text-xl font-bold text-purple-700">
                  {totalMarketValue.toFixed(0)}
                </div>
              </div>
              <div className={`p-3 rounded-lg ${totalProfitLoss >= 0 ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200'} border`}>
                <div className={`text-xs ${totalProfitLoss >= 0 ? 'text-red-600' : 'text-green-600'} mb-1`}>
                  总盈亏
                </div>
                <div className={`text-xl font-bold ${totalProfitLoss >= 0 ? 'text-red-700' : 'text-green-700'}`}>
                  {totalProfitLoss >= 0 ? '+' : ''}{totalProfitLoss.toFixed(0)}
                  <span className="text-sm ml-1">
                    ({totalProfitLossPct >= 0 ? '+' : ''}{totalProfitLossPct.toFixed(2)}%)
                  </span>
                </div>
              </div>
            </div>

            {/* 持仓列表 */}
            {positions.length === 0 ? (
              <div className="text-center py-8 text-gray-500">暂无持仓</div>
            ) : (
              <div className="space-y-2">
                {positions.slice(0, 5).map((position) => {
                  const advice = adviceMap[position.stock_code];
                  const actionCfg = advice ? ACTION_CONFIG[advice.action] || ACTION_CONFIG.HOLD : null;
                  const flowCfg = advice?.flow_pattern ? FLOW_CONFIG[advice.flow_pattern] : null;
                  const isExpanded = expandedCode === position.stock_code;

                  return (
                    <div
                      key={position.stock_code}
                      className={`p-3 rounded-lg border transition-all ${
                        isExpanded
                          ? "border-blue-300 bg-blue-50/30 shadow-sm"
                          : "border-gray-200 hover:border-blue-300 hover:bg-blue-50"
                      }`}
                    >
                      {/* 第一行：股名 + 盈亏 + 操作建议 */}
                      <div
                        className="flex items-center justify-between mb-2 cursor-pointer"
                        onClick={() => setExpandedCode(isExpanded ? null : position.stock_code)}
                      >
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-gray-900">{position.stock_name}</span>
                          <span className="text-xs text-gray-500">{position.stock_code}</span>
                          {/* 资金流模式标签 */}
                          {flowCfg && advice?.flow_pattern_desc && (
                            <span className={`text-[9px] font-bold ${flowCfg.color}`}>
                              {flowCfg.icon} {advice.flow_pattern_desc}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2">
                          {/* 操作建议标签 */}
                          {actionCfg && !adviceLoading && (
                            <span
                              className={`text-[10px] px-2 py-0.5 rounded-full border font-bold ${actionCfg.bg} ${actionCfg.text} ${actionCfg.border}`}
                            >
                              {actionCfg.emoji} {actionCfg.label}
                            </span>
                          )}
                          <span
                            className={`text-sm font-semibold ${
                              (position.profit_loss ?? 0) >= 0 ? "text-red-600" : "text-green-600"
                            }`}
                          >
                            {(position.profit_loss ?? 0) >= 0 ? "+" : ""}
                            {(position.profit_loss_pct ?? 0).toFixed(2)}%
                          </span>
                        </div>
                      </div>

                      {/* 第二行：持仓数据 + 快速操作 */}
                      <div className="flex items-center justify-between text-xs text-gray-600">
                        <div className="flex items-center gap-3">
                          <span>持仓: {position.quantity ?? 0}</span>
                          <span>成本: {(position.avg_price ?? 0).toFixed(2)}</span>
                          <span>现价: {(position.current_price ?? 0).toFixed(2)}</span>
                          <span>市值: {(position.market_value ?? 0).toFixed(0)}</span>
                        </div>
                        {/* 快速操作按钮 */}
                        <div className="flex items-center gap-1 shrink-0">
                          <button
                            onClick={(e) => { e.stopPropagation(); analyzePosition(position.stock_code); }}
                            disabled={aiResults[position.stock_code]?.loading}
                            className={`text-[9px] px-1.5 py-0.5 rounded font-medium transition-colors ${
                              aiResults[position.stock_code]?.loading
                                ? 'bg-purple-100 text-purple-400 cursor-wait'
                                : 'bg-purple-50 text-purple-600 hover:bg-purple-100 dark:bg-purple-900/30 dark:text-purple-400'
                            }`}
                          >
                            {aiResults[position.stock_code]?.loading ? '⏳分析中...' : '🤖AI诊断'}
                          </button>
                          <Link
                            href={`/stock-detail?code=${position.stock_code}`}
                            onClick={(e) => e.stopPropagation()}
                            className="text-[9px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 dark:bg-gray-800/50 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700/50 transition-colors font-medium"
                          >
                            🔍分析
                          </Link>
                          <Link
                            href={`/trading?stock=${position.stock_code}&action=buy`}
                            onClick={(e) => e.stopPropagation()}
                            className="text-[9px] px-1.5 py-0.5 rounded bg-red-50 text-red-600 hover:bg-red-100 dark:bg-red-900/30 dark:text-red-400 transition-colors font-medium"
                          >
                            🟢买
                          </Link>
                          <Link
                            href={`/trading?stock=${position.stock_code}&action=sell`}
                            onClick={(e) => e.stopPropagation()}
                            className="text-[9px] px-1.5 py-0.5 rounded bg-green-50 text-green-600 hover:bg-green-100 dark:bg-green-900/30 dark:text-green-400 transition-colors font-medium"
                          >
                            🔴卖
                          </Link>
                        </div>
                      </div>


                      {/* 展开：操作建议详情 */}
                      {isExpanded && advice && !aiResults[position.stock_code]?.data && (
                        <div className="mt-2 pt-2 border-t border-gray-200/60 space-y-1.5">
                          {/* 价位建议 */}
                          <div className="flex items-center gap-3 text-[10px]">
                            <span className="text-gray-500">
                              止损 <span className="font-bold text-green-600">{advice.stop_loss?.toFixed(2)}</span>
                            </span>
                            <span className="text-gray-500">
                              止盈 <span className="font-bold text-red-600">{advice.take_profit?.toFixed(2)}</span>
                            </span>
                            <span className="text-gray-500">
                              置信度 <span className="font-bold text-indigo-600">{(advice.confidence * 100).toFixed(0)}%</span>
                            </span>
                            <span className={`px-1.5 py-px rounded text-[9px] font-bold ${
                              advice.risk_level === 'LOW' ? 'bg-green-100 text-green-700' :
                              advice.risk_level === 'HIGH' ? 'bg-red-100 text-red-700' :
                              'bg-yellow-100 text-yellow-700'
                            }`}>
                              {advice.risk_level === 'LOW' ? '低风险' : advice.risk_level === 'HIGH' ? '高风险' : '中风险'}
                            </span>
                          </div>
                          {/* 理由 */}
                          <div className="flex flex-wrap gap-1">
                            {advice.reasons?.map((r, ri) => (
                              <span
                                key={ri}
                                className={`text-[9px] px-1.5 py-0.5 rounded border ${
                                  r.startsWith("⚠️")
                                    ? "bg-amber-50 text-amber-700 border-amber-200"
                                    : "bg-blue-50 text-blue-600 border-blue-100/60"
                                }`}
                              >
                                {r}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* AI 分析结果 */}
                      {isExpanded && aiResults[position.stock_code]?.loading && (
                        <div className="mt-2 pt-2 border-t border-purple-200/60 text-center py-4">
                          <div className="text-sm text-purple-500 animate-pulse">🤖 AI 正在分析持仓数据...</div>
                          <div className="text-[10px] text-gray-400 mt-1">聚合行情/资金流/信号/策略等 15 个维度</div>
                        </div>
                      )}
                      {isExpanded && aiResults[position.stock_code]?.error && (
                        <div className="mt-2 pt-2 border-t border-red-200/60 text-center py-3">
                          <div className="text-xs text-red-500">❌ {aiResults[position.stock_code].error}</div>
                        </div>
                      )}
                      {isExpanded && aiResults[position.stock_code]?.data && (() => {
                        const ai = aiResults[position.stock_code].data!;
                        const aiActionCfg: Record<string, { emoji: string; label: string; color: string }> = {
                          STRONG_BUY: { emoji: '🟢', label: '强烈买入', color: 'bg-emerald-100 text-emerald-700 border-emerald-300' },
                          BUY: { emoji: '🟢', label: '买入', color: 'bg-emerald-50 text-emerald-600 border-emerald-200' },
                          HOLD: { emoji: '🔵', label: '持有', color: 'bg-blue-50 text-blue-600 border-blue-200' },
                          REDUCE: { emoji: '🟡', label: '减仓', color: 'bg-amber-50 text-amber-700 border-amber-200' },
                          SELL: { emoji: '🔴', label: '卖出', color: 'bg-red-50 text-red-600 border-red-200' },
                          STRONG_SELL: { emoji: '🔴', label: '强烈卖出', color: 'bg-red-100 text-red-700 border-red-300' },
                        };
                        const cfg = aiActionCfg[ai.action] || aiActionCfg.HOLD;
                        return (
                          <div className="mt-2 pt-2 border-t border-purple-200/60 space-y-2">
                            {/* 操作建议标签 */}
                            <div className="flex items-center gap-2">
                              <span className={`text-xs px-2 py-0.5 rounded-full border font-bold ${cfg.color}`}>
                                {cfg.emoji} AI: {cfg.label}
                              </span>
                              <span className="text-[10px] text-gray-500">置信度 <span className="font-bold text-indigo-600">{ai.confidence}%</span></span>
                              {ai.time_horizon && (
                                <span className="text-[9px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{ai.time_horizon}</span>
                              )}
                            </div>
                            {/* 止损/止盈 */}
                            {(ai.stop_loss_price || ai.target_price) && (
                              <div className="flex items-center gap-3 text-[10px]">
                                {ai.stop_loss_price && (
                                  <span className="text-gray-500">止损 <span className="font-bold text-green-600">{ai.stop_loss_price.toFixed(2)}</span></span>
                                )}
                                {ai.target_price && (
                                  <span className="text-gray-500">目标 <span className="font-bold text-red-600">{ai.target_price.toFixed(2)}</span></span>
                                )}
                              </div>
                            )}
                            {/* 分析摘要 */}
                            <div className="text-[11px] text-gray-700 dark:text-gray-300 leading-relaxed">
                              {ai.reasoning}
                            </div>
                            {/* 关键因素 */}
                            {ai.key_factors?.length > 0 && (
                              <div className="flex flex-wrap gap-1">
                                {ai.key_factors.map((f, i) => (
                                  <span key={i} className="text-[9px] px-1.5 py-0.5 rounded bg-purple-50 text-purple-600 border border-purple-100">
                                    {f}
                                  </span>
                                ))}
                              </div>
                            )}
                            {/* 风险提示 */}
                            {ai.risk_warning && (
                              <div className="text-[10px] text-amber-600 bg-amber-50 border border-amber-100 rounded px-2 py-1">
                                ⚠️ {ai.risk_warning}
                              </div>
                            )}
                          </div>
                        );
                      })()}
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>
    </Card>
  );
}
