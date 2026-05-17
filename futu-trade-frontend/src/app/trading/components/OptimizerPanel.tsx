"use client";

import { useState, useEffect, useCallback } from "react";
import {
  getScoringStatus,
  getCurrentPhase,
  getGuardStatus,
  getOptimizerOverview,
  runPreMarketScoring,
  dailyReset,
  type ScoringResult,
  type PhaseStatus,
  type GuardStatus,
  type OverviewData,
} from "@/lib/api/trade-optimizer";

// 阶段中文映射
const PHASE_LABELS: Record<string, { label: string; color: string; emoji: string }> = {
  pre_market: { label: "盘前", color: "text-gray-400", emoji: "🌙" },
  phase1_opening: { label: "开盘抢先手", color: "text-green-400", emoji: "🚀" },
  phase2_observe: { label: "观察期(禁买)", color: "text-yellow-400", emoji: "⚠️" },
  phase3_rotate: { label: "资金流换票", color: "text-blue-400", emoji: "🔄" },
  lunch_break: { label: "午休", color: "text-gray-400", emoji: "☕" },
  after_hours: { label: "收盘后", color: "text-gray-500", emoji: "🌙" },
};

// 评分等级颜色
function getScoreColor(score: number): string {
  if (score >= 80) return "text-green-400";
  if (score >= 60) return "text-blue-400";
  if (score >= 40) return "text-yellow-400";
  return "text-red-400";
}

function getScoreBg(score: number): string {
  if (score >= 80) return "bg-green-500/20 border-green-500/30";
  if (score >= 60) return "bg-blue-500/20 border-blue-500/30";
  if (score >= 40) return "bg-yellow-500/20 border-yellow-500/30";
  return "bg-red-500/20 border-red-500/30";
}

export default function OptimizerPanel() {
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [scores, setScores] = useState<ScoringResult[]>([]);
  const [phase, setPhase] = useState<PhaseStatus | null>(null);
  const [guard, setGuard] = useState<GuardStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [scoring, setScoring] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [overviewRes, scoringRes, phaseRes, guardRes] = await Promise.allSettled([
        getOptimizerOverview(),
        getScoringStatus(),
        getCurrentPhase(),
        getGuardStatus(),
      ]);

      if (overviewRes.status === "fulfilled" && overviewRes.value.success) {
        setOverview(overviewRes.value.data);
      }
      if (scoringRes.status === "fulfilled" && scoringRes.value.success) {
        setScores(scoringRes.value.data.all_scores || []);
      }
      if (phaseRes.status === "fulfilled" && phaseRes.value.success) {
        setPhase(phaseRes.value.data);
      }
      if (guardRes.status === "fulfilled" && guardRes.value.success) {
        setGuard(guardRes.value.data);
      }

      setError(null);
    } catch (e) {
      setError("获取数据失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleRunScoring = async () => {
    setScoring(true);
    try {
      const res = await runPreMarketScoring();
      if (res.success) {
        await fetchData();
      }
    } finally {
      setScoring(false);
    }
  };

  const handleDailyReset = async () => {
    if (confirm("确认重置所有交易优化模块？")) {
      await dailyReset();
      await fetchData();
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  const phaseInfo = phase ? PHASE_LABELS[phase.phase] || { label: phase.phase, color: "text-gray-400", emoji: "❓" } : null;

  return (
    <div className="space-y-6">
      {/* 顶栏 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">交易优化面板</h1>
          <p className="text-sm text-gray-400 mt-1">评分系统 · 阶段管理 · 纪律管控</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={handleRunScoring}
            disabled={scoring}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 rounded-lg text-sm font-medium transition-colors"
          >
            {scoring ? "评分中..." : "运行盘前评分"}
          </button>
          <button
            onClick={handleDailyReset}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-medium transition-colors"
          >
            每日重置
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 text-sm">{error}</div>
      )}

      {/* 状态卡片 */}
      <div className="grid grid-cols-4 gap-4">
        {/* 当前阶段 */}
        <div className="bg-gray-800 rounded-xl p-5 border border-gray-700">
          <div className="text-sm text-gray-400 mb-2">当前阶段</div>
          <div className={`text-xl font-bold ${phaseInfo?.color || "text-gray-400"}`}>
            {phaseInfo?.emoji} {phaseInfo?.label || "未知"}
          </div>
          {phase?.note && <div className="text-xs text-gray-500 mt-2">{phase.note}</div>}
          <div className="mt-3 text-xs text-gray-500">
            {phase?.can_buy ? "✅ 可买入" : "🚫 禁买入"} · {phase?.can_sell ? "✅ 可卖出" : "🚫 禁卖出"}
          </div>
        </div>

        {/* 交易额度 */}
        <div className="bg-gray-800 rounded-xl p-5 border border-gray-700">
          <div className="text-sm text-gray-400 mb-2">今日交易额度</div>
          <div className="text-xl font-bold text-white">
            {guard?.trade_count || 0} / {guard?.max_trades || 8}
          </div>
          <div className="mt-2 w-full bg-gray-700 rounded-full h-2">
            <div
              className="bg-blue-500 h-2 rounded-full transition-all"
              style={{ width: `${((guard?.trade_count || 0) / (guard?.max_trades || 8)) * 100}%` }}
            />
          </div>
          {guard?.circuit_broken && (
            <div className="mt-2 text-xs text-red-400 font-bold">🔴 日亏损熔断</div>
          )}
        </div>

        {/* 候选标的 */}
        <div className="bg-gray-800 rounded-xl p-5 border border-gray-700">
          <div className="text-sm text-gray-400 mb-2">候选标的(≥60分)</div>
          <div className="text-xl font-bold text-green-400">
            {overview?.scoring?.candidates || 0} / {overview?.scoring?.total_scored || 0}
          </div>
          <div className="mt-2 text-xs text-gray-500">
            {overview?.scoring?.top3?.map((s) => (
              <span key={s.code} className="inline-block mr-2">
                {s.name}({s.score})
              </span>
            ))}
          </div>
        </div>

        {/* 换票状态 */}
        <div className="bg-gray-800 rounded-xl p-5 border border-gray-700">
          <div className="text-sm text-gray-400 mb-2">换票次数</div>
          <div className="text-xl font-bold text-blue-400">
            {overview?.rotation?.count || 0} / {overview?.rotation?.max || 2}
          </div>
          <div className="mt-2 text-xs text-gray-500">
            活跃持仓: {overview?.positions?.active || 0} 只
          </div>
          {phase?.buy_strategy && (
            <div className="mt-2 text-xs text-gray-500 truncate" title={phase.buy_strategy}>
              策略: {phase.buy_strategy}
            </div>
          )}
        </div>
      </div>

      {/* 评分列表 */}
      <div className="bg-gray-800 rounded-xl border border-gray-700">
        <div className="px-5 py-4 border-b border-gray-700 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">标的评分排行</h2>
          <span className="text-sm text-gray-400">{scores.length} 只标的</span>
        </div>

        {scores.length === 0 ? (
          <div className="p-12 text-center text-gray-500">
            <p className="text-lg mb-2">暂无评分数据</p>
            <p className="text-sm">点击「运行盘前评分」生成评分</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-900/50">
                <tr className="text-gray-400 text-left">
                  <th className="px-5 py-3 font-medium">排名</th>
                  <th className="px-5 py-3 font-medium">代码</th>
                  <th className="px-5 py-3 font-medium">名称</th>
                  <th className="px-5 py-3 font-medium text-center">总分</th>
                  <th className="px-5 py-3 font-medium text-center">状态</th>
                  <th className="px-5 py-3 font-medium text-center">5日趋势</th>
                  <th className="px-5 py-3 font-medium text-center">K线位置</th>
                  <th className="px-5 py-3 font-medium text-center">日振幅</th>
                  <th className="px-5 py-3 font-medium text-center">量比</th>
                  <th className="px-5 py-3 font-medium text-center">前日涨幅</th>
                  <th className="px-5 py-3 font-medium text-center">资金流</th>
                </tr>
              </thead>
              <tbody>
                {scores.map((s, idx) => (
                  <tr
                    key={s.stock_code}
                    className="border-t border-gray-700/50 hover:bg-gray-700/30 transition-colors"
                  >
                    <td className="px-5 py-3 text-gray-500">{idx + 1}</td>
                    <td className="px-5 py-3 font-mono text-gray-300">{s.stock_code}</td>
                    <td className="px-5 py-3 text-white font-medium">{s.stock_name}</td>
                    <td className="px-5 py-3 text-center">
                      <span className={`inline-block px-3 py-1 rounded-full text-sm font-bold border ${getScoreBg(s.total_score)} ${getScoreColor(s.total_score)}`}>
                        {s.total_score}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-center">
                      {s.passed ? (
                        <span className="text-green-400 text-xs font-medium">✅ 通过</span>
                      ) : (
                        <span className="text-red-400 text-xs font-medium" title={s.veto_reason}>
                          ❌ {s.veto_reason || "低分"}
                        </span>
                      )}
                    </td>
                    {s.details.map((d, i) => (
                      <td key={i} className="px-5 py-3 text-center">
                        <div className={`text-sm font-medium ${d.score >= d.max * 0.7 ? "text-green-400" : d.score >= d.max * 0.4 ? "text-yellow-400" : "text-gray-500"}`}>
                          {d.score}/{d.max}
                        </div>
                        <div className="text-xs text-gray-500 mt-0.5">
                          {d.value !== null ? (typeof d.value === "number" ? d.value.toFixed(1) : d.value) : "-"}
                        </div>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 日亏损统计 */}
      {guard && Object.keys(guard.buy_counts).length > 0 && (
        <div className="bg-gray-800 rounded-xl border border-gray-700 p-5">
          <h2 className="text-lg font-semibold text-white mb-3">今日交易统计</h2>
          <div className="grid grid-cols-6 gap-3">
            {Object.entries(guard.buy_counts).map(([code, count]) => (
              <div key={code} className="bg-gray-700/50 rounded-lg p-3 text-center">
                <div className="text-xs text-gray-400 font-mono">{code}</div>
                <div className="text-lg font-bold text-white mt-1">{count}次买入</div>
              </div>
            ))}
          </div>
          <div className="mt-3 text-sm text-gray-400">
            日盈亏: <span className={guard.daily_pnl >= 0 ? "text-green-400" : "text-red-400"}>
              {guard.daily_pnl >= 0 ? "+" : ""}{guard.daily_pnl.toFixed(2)}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
