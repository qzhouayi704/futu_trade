// AI 分析弹窗组件 — 供选股工作台和交易决策中心共用

"use client";

import { useState, useCallback } from "react";
import { analyzeStockAI, clearAICache, ACTION_LABELS, type AIAnalysisResult } from "@/lib/api/ai-analysis";

interface AIAnalysisDialogProps {
  isOpen: boolean;
  onClose: () => void;
  stockCode: string;
  stockName: string;
}

export function AIAnalysisDialog({ isOpen, onClose, stockCode, stockName }: AIAnalysisDialogProps) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AIAnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fromCache, setFromCache] = useState(false);

  const doAnalyze = useCallback(async (refresh = false) => {
    setLoading(true);
    setError(null);
    try {
      if (refresh) {
        await clearAICache(stockCode);
      }
      const res = await analyzeStockAI(stockCode);
      if (res.success && res.data) {
        setResult(res.data);
        setFromCache(!refresh && !!res.data);
      } else {
        setError(res.message || "分析失败");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "请求失败");
    } finally {
      setLoading(false);
    }
  }, [stockCode]);

  // 打开时自动触发分析
  const [initialized, setInitialized] = useState(false);
  if (isOpen && !initialized && !loading) {
    setInitialized(true);
    doAnalyze();
  }
  if (!isOpen && initialized) {
    setInitialized(false);
  }

  if (!isOpen) return null;

  const actionInfo = result ? (ACTION_LABELS[result.action] || ACTION_LABELS.HOLD) : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <div
        className="bg-white rounded-2xl shadow-2xl w-[520px] max-h-[85vh] overflow-hidden flex flex-col animate-in fade-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between bg-gradient-to-r from-indigo-50 to-purple-50">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-md">
              <i className="fas fa-robot text-white text-sm" />
            </div>
            <div>
              <h3 className="text-base font-bold text-gray-900">AI 分析助理</h3>
              <p className="text-xs text-gray-500">{stockCode} · {stockName}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {result && (
              <button
                onClick={() => doAnalyze(true)}
                disabled={loading}
                className="text-xs text-indigo-600 hover:text-indigo-800 hover:bg-indigo-50 px-2 py-1 rounded-md transition-colors"
              >
                <i className="fas fa-redo mr-1" />重新分析
              </button>
            )}
            <button onClick={onClose} className="w-8 h-8 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors">
              <i className="fas fa-times" />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {/* Loading */}
          {loading && (
            <div className="flex flex-col items-center justify-center py-16 text-gray-500">
              <div className="w-12 h-12 border-3 border-indigo-200 border-t-indigo-600 rounded-full animate-spin mb-4" />
              <p className="text-sm font-medium">Gemini 正在分析中...</p>
              <p className="text-xs text-gray-400 mt-1">首次分析可能需要 10-30 秒</p>
            </div>
          )}

          {/* Error */}
          {error && !loading && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-center">
              <i className="fas fa-exclamation-triangle text-red-500 text-2xl mb-2" />
              <p className="text-sm text-red-700 font-medium">{error}</p>
              <button
                onClick={() => doAnalyze(true)}
                className="mt-3 text-xs bg-red-600 text-white px-4 py-1.5 rounded-lg hover:bg-red-700 transition-colors"
              >
                重试
              </button>
            </div>
          )}

          {/* Result */}
          {result && !loading && actionInfo && (
            <>
              {/* Action Banner */}
              <div className={`rounded-xl p-4 ${actionInfo.bg} border ${actionInfo.color.replace('text-', 'border-').replace('700', '200').replace('600', '200')}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-3xl">{actionInfo.emoji}</span>
                    <div>
                      <div className={`text-xl font-extrabold ${actionInfo.color}`}>{actionInfo.label}</div>
                      <div className="text-xs text-gray-500 mt-0.5">
                        置信度 <span className="font-bold text-gray-700">{result.confidence}%</span>
                        {result.time_horizon && (
                          <span className="ml-2">{result.time_horizon === "SHORT_TERM" ? "短线(1-3天)" : "中线(3-10天)"}</span>
                        )}
                      </div>
                    </div>
                  </div>
                  {/* 置信度环形指示器 */}
                  <div className="relative w-14 h-14">
                    <svg className="w-14 h-14 transform -rotate-90" viewBox="0 0 56 56">
                      <circle cx="28" cy="28" r="24" fill="none" stroke="#e5e7eb" strokeWidth="4" />
                      <circle
                        cx="28" cy="28" r="24" fill="none"
                        stroke={result.confidence >= 70 ? "#dc2626" : result.confidence >= 50 ? "#f59e0b" : "#6b7280"}
                        strokeWidth="4"
                        strokeDasharray={`${result.confidence * 1.508} 150.8`}
                        strokeLinecap="round"
                      />
                    </svg>
                    <span className="absolute inset-0 flex items-center justify-center text-xs font-bold text-gray-700">
                      {result.confidence}
                    </span>
                  </div>
                </div>
              </div>

              {/* 目标价 / 止损价 */}
              {(result.target_price || result.stop_loss_price) && (
                <div className="grid grid-cols-2 gap-3">
                  {result.target_price && (
                    <div className="bg-red-50/50 border border-red-100 rounded-lg p-3 text-center">
                      <div className="text-xs text-gray-500 mb-1">目标价</div>
                      <div className="text-lg font-bold text-red-600">{result.target_price.toFixed(3)}</div>
                    </div>
                  )}
                  {result.stop_loss_price && (
                    <div className="bg-green-50/50 border border-green-100 rounded-lg p-3 text-center">
                      <div className="text-xs text-gray-500 mb-1">止损价</div>
                      <div className="text-lg font-bold text-green-600">{result.stop_loss_price.toFixed(3)}</div>
                    </div>
                  )}
                </div>
              )}

              {/* 分析推理 */}
              <div className="bg-gray-50 rounded-xl p-4">
                <h4 className="text-sm font-semibold text-gray-800 mb-2 flex items-center gap-1.5">
                  <i className="fas fa-brain text-indigo-500" />
                  分析推理
                </h4>
                <p className="text-sm text-gray-700 leading-relaxed">{result.reasoning}</p>
              </div>

              {/* 关键因素 */}
              {result.key_factors && result.key_factors.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold text-gray-800 mb-2 flex items-center gap-1.5">
                    <i className="fas fa-list-check text-indigo-500" />
                    关键因素
                  </h4>
                  <div className="space-y-1.5">
                    {result.key_factors.map((factor, idx) => (
                      <div key={idx} className="flex items-start gap-2 text-sm text-gray-600">
                        <span className="w-5 h-5 rounded-full bg-indigo-100 text-indigo-600 flex items-center justify-center flex-shrink-0 text-xs font-bold mt-0.5">
                          {idx + 1}
                        </span>
                        <span>{factor}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 风险提示 */}
              {result.risk_warning && (
                <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
                  <h4 className="text-sm font-semibold text-amber-800 mb-1 flex items-center gap-1.5">
                    <i className="fas fa-exclamation-triangle text-amber-500" />
                    风险提示
                  </h4>
                  <p className="text-sm text-amber-700">{result.risk_warning}</p>
                </div>
              )}

              {/* 评分评价 */}
              {result.score_assessment && (
                <div className="text-xs text-gray-400 bg-gray-50 rounded-lg p-3">
                  <i className="fas fa-chart-bar mr-1" />
                  评分评价: {result.score_assessment}
                </div>
              )}

              {/* Footer 信息 */}
              <div className="text-xs text-gray-300 text-right">
                {fromCache && <span className="mr-2">📦 缓存结果</span>}
                分析时间: {result.analyzed_at ? new Date(result.analyzed_at).toLocaleString("zh-CN") : "-"}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** 简化版 AI 分析触发按钮 */
export function AIAnalysisButton({ stockCode, stockName }: { stockCode: string; stockName: string }) {
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <>
      <button
        onClick={(e) => {
          e.stopPropagation();
          setDialogOpen(true);
        }}
        className="inline-flex items-center justify-center w-7 h-7 rounded-md text-xs transition-all bg-indigo-50 text-indigo-500 hover:bg-indigo-100 hover:text-indigo-700 hover:shadow-sm"
        title="AI 分析"
      >
        <i className="fas fa-robot text-xs" />
      </button>
      <AIAnalysisDialog
        isOpen={dialogOpen}
        onClose={() => setDialogOpen(false)}
        stockCode={stockCode}
        stockName={stockName}
      />
    </>
  );
}
