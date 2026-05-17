// 盘后优选 — 独立页面
"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, Button } from "@/components/common";
import { useToast } from "@/components/common/Toast";
import { overnightApi, type OvernightCandidate } from "@/lib/api/overnight-screen";
import { formatPrice, formatPercent } from "@/lib/utils";

// 分类颜色
const categoryColors: Record<string, string> = {
  "强势延续": "bg-red-100 text-red-700 border-red-200",
  "趋势反转": "bg-emerald-100 text-emerald-700 border-emerald-200",
  "资金吸筹": "bg-blue-100 text-blue-700 border-blue-200",
  "综合优选": "bg-purple-100 text-purple-700 border-purple-200",
};

// 评级颜色
const verdictColors: Record<string, string> = {
  "强烈推荐": "from-red-500 to-orange-500",
  "推荐": "from-blue-500 to-cyan-500",
  "可关注": "from-gray-500 to-gray-400",
  "观望": "from-gray-400 to-gray-300",
};

// 评分条颜色
function scoreBarColor(score: number): string {
  if (score >= 70) return "bg-gradient-to-r from-red-500 to-orange-400";
  if (score >= 50) return "bg-gradient-to-r from-blue-500 to-cyan-400";
  if (score >= 30) return "bg-gradient-to-r from-yellow-500 to-yellow-400";
  return "bg-gray-300";
}

// 维度中文名
const dimNames: Record<string, string> = {
  capital_continuity: "资金持续性",
  trend_reversal: "趋势反转",
  net_inflow_position: "净流入建仓",
  capital_score_v2: "资金评分",
  big_order_strength: "大单强度",
  kline_profile: "K线画像",
  quickscan_verdict: "快扫判定",
  leader_bonus: "龙头加分",
  volume_price_fit: "量价配合",
  opportunity_score: "机会评分",
};

export default function OvernightPanel() {
  const { showToast } = useToast();
  const [candidates, setCandidates] = useState<OvernightCandidate[]>([]);
  const [breakoutList, setBreakoutList] = useState<any[]>([]);
  const [consolList, setConsolList] = useState<any[]>([]);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState("");
  const [timestamp, setTimestamp] = useState("");
  const [expandedCode, setExpandedCode] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState("all");

  // 加载已有结果
  const loadResult = useCallback(async () => {
    try {
      const data = await overnightApi.getResult();
      if (data.candidates?.length) {
        setCandidates(data.candidates);
        setTimestamp(data.timestamp || "");
      }
      if (data.breakout_candidates?.length) {
        setBreakoutList(data.breakout_candidates);
      }
      if (data.consolidation_candidates?.length) {
        setConsolList(data.consolidation_candidates);
      }
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadResult(); }, [loadResult]);

  // 触发优选
  const handleTrigger = async () => {
    try {
      const res = await overnightApi.trigger();
      if (!res.success) {
        showToast("warning", "提示", res.message);
        return;
      }
      setRunning(true);
      setProgress("启动中...");
      showToast("success", "已启动", "盘后优选评分任务已启动");

      // 轮询状态
      const poll = setInterval(async () => {
        try {
          const status = await overnightApi.getStatus();
          setProgress(status.progress || "");
          if (!status.running) {
            clearInterval(poll);
            setRunning(false);
            if (status.error) {
              showToast("error", "失败", status.error);
            } else {
              showToast("success", "完成", "盘后优选评分已完成");
              loadResult();
            }
          }
        } catch {
          clearInterval(poll);
          setRunning(false);
        }
      }, 2000);
    } catch (err) {
      showToast("error", "错误", err instanceof Error ? err.message : "触发失败");
    }
  };

  // 筛选
  const filtered = categoryFilter === "all"
    ? candidates
    : candidates.filter(c => c.category === categoryFilter);

  // 统计
  const categories = [...new Set(candidates.map(c => c.category))];

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      {/* 标题栏 */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <i className="fas fa-moon text-indigo-600" />
            盘后优选
            {candidates.length > 0 && (
              <span className="text-sm font-medium text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded">
                Top {candidates.length}
              </span>
            )}
          </h1>
          <p className="text-gray-500 mt-1 text-sm">
            收盘后全规则综合评分，筛选明日交易候选
            {timestamp && (
              <span className="ml-2 text-xs text-gray-400">
                生成于 {new Date(timestamp).toLocaleString("zh-CN")}
              </span>
            )}
          </p>
        </div>
        <Button
          size="sm"
          variant="primary"
          loading={running}
          onClick={handleTrigger}
          className="flex items-center gap-2"
        >
          <i className="fas fa-magic" />
          {running ? progress : "生成明日优选"}
        </Button>
      </div>

      {/* 分类筛选标签 */}
      {candidates.length > 0 && (
        <div className="flex gap-2 mb-4">
          <button
            onClick={() => setCategoryFilter("all")}
            className={`px-3 py-1.5 text-xs rounded-full border transition-colors ${
              categoryFilter === "all"
                ? "bg-gray-900 text-white border-gray-900"
                : "bg-white text-gray-600 border-gray-300 hover:border-gray-400"
            }`}
          >
            全部 ({candidates.length})
          </button>
          {categories.map(cat => (
            <button
              key={cat}
              onClick={() => setCategoryFilter(cat)}
              className={`px-3 py-1.5 text-xs rounded-full border transition-colors ${
                categoryFilter === cat
                  ? "bg-gray-900 text-white border-gray-900"
                  : `${categoryColors[cat] || "bg-gray-50"} border hover:opacity-80`
              }`}
            >
              {cat} ({candidates.filter(c => c.category === cat).length})
            </button>
          ))}
        </div>
      )}

      {/* 空状态 */}
      {candidates.length === 0 && !running && (
        <Card className="text-center py-20">
          <i className="fas fa-moon text-5xl text-gray-200 mb-4 block" />
          <p className="text-gray-500 mb-4">暂无优选结果</p>
          <p className="text-gray-400 text-sm mb-6">
            收盘后点击"生成明日优选"，系统将对市场扫描池股票执行全规则综合评分
          </p>
          <Button variant="primary" onClick={handleTrigger}>
            <i className="fas fa-magic mr-2" />
            立即生成
          </Button>
        </Card>
      )}

      {/* 运行中 */}
      {running && candidates.length === 0 && (
        <Card className="text-center py-16">
          <i className="fas fa-spinner fa-spin text-4xl text-indigo-500 mb-4 block" />
          <p className="text-gray-700 font-medium">{progress || "评分中..."}</p>
          <p className="text-gray-400 text-sm mt-2">正在对全部活跃股票执行多规则评分</p>
        </Card>
      )}

      {/* 🔥 突破候选股信号 */}
      {breakoutList.length > 0 && (
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-lg">🚀</span>
            <h2 className="text-lg font-bold text-gray-900">缩量蓄势 → 放量突破</h2>
            <span className="text-xs font-medium text-orange-600 bg-orange-50 px-2 py-0.5 rounded-full border border-orange-200">
              {breakoutList.length} 只信号
            </span>
          </div>
          <p className="text-xs text-gray-500 mb-3">
            低换手率盘整后放量突破，建议明日早盘关注（开盘15分钟内确认放量再入场）
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {breakoutList.map((b) => (
              <div
                key={b.code}
                className="relative overflow-hidden rounded-xl border border-orange-200 bg-gradient-to-br from-orange-50 to-amber-50 p-4 hover:shadow-lg transition-shadow"
              >
                {/* 评分角标 */}
                <div className="absolute top-2 right-2 w-10 h-10 rounded-full bg-gradient-to-br from-orange-500 to-red-500 flex items-center justify-center text-white text-sm font-bold shadow">
                  {b.score?.toFixed(0)}
                </div>

                {/* 股票名称 */}
                <div className="mb-2">
                  <span className="font-bold text-gray-900 text-base">{b.name || b.code}</span>
                  <span className="text-xs text-gray-400 ml-2">{b.code}</span>
                </div>

                {/* 核心数据 */}
                <div className="grid grid-cols-3 gap-2 mb-3 text-center">
                  <div className="bg-white/70 rounded-lg p-1.5">
                    <div className="text-[10px] text-gray-400">突破涨幅</div>
                    <div className="text-sm font-bold text-red-600">+{b.change_pct?.toFixed(1)}%</div>
                  </div>
                  <div className="bg-white/70 rounded-lg p-1.5">
                    <div className="text-[10px] text-gray-400">放量倍数</div>
                    <div className="text-sm font-bold text-orange-600">{b.vol_ratio?.toFixed(1)}x</div>
                  </div>
                  <div className="bg-white/70 rounded-lg p-1.5">
                    <div className="text-[10px] text-gray-400">前3日换手</div>
                    <div className="text-sm font-bold text-blue-600">{b.prev3_avg_tr?.toFixed(2)}%</div>
                  </div>
                </div>

                {/* 信号描述 */}
                <div className="text-xs text-gray-600 bg-white/50 rounded-lg px-2 py-1.5">
                  💡 {b.signal_note}
                </div>

                {/* 底部标签 */}
                <div className="flex items-center gap-2 mt-2">
                  <span className="text-[10px] text-gray-400">
                    收盘 {b.close?.toFixed(2)}
                  </span>
                  <span className="text-[10px] text-gray-400">·</span>
                  <span className="text-[10px] text-gray-400">
                    前5日波幅 {b.prev5_range_pct?.toFixed(1)}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 🏔️ 横盘启动信号 */}
      {consolList.length > 0 && (
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-lg">🏔️</span>
            <h2 className="text-lg font-bold text-gray-900">底部横盘 → 放量启动</h2>
            <span className="text-xs font-medium text-teal-600 bg-teal-50 px-2 py-0.5 rounded-full border border-teal-200">
              {consolList.length} 只信号
            </span>
          </div>
          <p className="text-xs text-gray-500 mb-3">
            长期低位横盘后开始放量，类似富通式启动初期信号
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {consolList.map((c) => (
              <div
                key={c.code}
                className="relative overflow-hidden rounded-xl border border-teal-200 bg-gradient-to-br from-teal-50 to-cyan-50 p-4 hover:shadow-lg transition-shadow"
              >
                <div className="absolute top-2 right-2 w-10 h-10 rounded-full bg-gradient-to-br from-teal-500 to-cyan-600 flex items-center justify-center text-white text-sm font-bold shadow">
                  {c.score?.toFixed(0)}
                </div>
                <div className="mb-2">
                  <span className="font-bold text-gray-900 text-base">{c.name || c.code}</span>
                  <span className="text-xs text-gray-400 ml-2">{c.code}</span>
                  {c.breakout && (
                    <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-100 text-red-600 border border-red-200">已突破</span>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-2 mb-3 text-center">
                  <div className="bg-white/70 rounded-lg p-1.5">
                    <div className="text-[10px] text-gray-400">90日位置</div>
                    <div className="text-sm font-bold text-teal-700">{c.pos_90d?.toFixed(0)}%</div>
                  </div>
                  <div className="bg-white/70 rounded-lg p-1.5">
                    <div className="text-[10px] text-gray-400">放量倍数</div>
                    <div className="text-sm font-bold text-orange-600">{c.vol_ratio?.toFixed(1)}x</div>
                  </div>
                  <div className="bg-white/70 rounded-lg p-1.5">
                    <div className="text-[10px] text-gray-400">横盘振幅</div>
                    <div className="text-sm font-bold text-blue-600">{c.consol_range?.toFixed(0)}%</div>
                  </div>
                </div>
                <div className="text-xs text-gray-600 bg-white/50 rounded-lg px-2 py-1.5">
                  💡 {c.signal_note}
                </div>
                <div className="flex items-center gap-2 mt-2">
                  <span className="text-[10px] text-gray-400">现价 {c.price?.toFixed(2)}</span>
                  <span className="text-[10px] text-gray-400">·</span>
                  <span className="text-[10px] text-gray-400">3日涨 {c.change_3d >= 0 ? '+' : ''}{c.change_3d?.toFixed(1)}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 候选列表 */}
      {filtered.length > 0 && (
        <div className="space-y-3">
          {filtered.map((c) => {
            const isExpanded = expandedCode === c.stock_code;
            return (
              <Card
                key={c.stock_code}
                className="overflow-hidden hover:shadow-md transition-shadow"
              >
                {/* 主行 */}
                <div 
                  className="p-4 flex items-center gap-4 cursor-pointer"
                  onClick={() => setExpandedCode(isExpanded ? null : c.stock_code)}
                >
                  {/* 排名 */}
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center text-white font-bold text-sm bg-gradient-to-br ${verdictColors[c.verdict] || verdictColors["观望"]}`}>
                    {c.rank}
                  </div>

                  {/* 股票信息 */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-gray-900">{c.stock_name}</span>
                      <span className="text-xs text-gray-400">{c.stock_code}</span>
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${categoryColors[c.category] || "bg-gray-100 text-gray-600"}`}>
                        {c.category}
                      </span>
                      {c.r5_candidate && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-100 text-amber-700 border border-amber-200">
                          R5候选
                        </span>
                      )}
                      {c.penalty_factor < 1 && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-yellow-100 text-yellow-700">
                          降权{((1 - c.penalty_factor) * 100).toFixed(0)}%
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-gray-500 mt-1 truncate">
                      {c.reasons.slice(0, 2).join(" · ")}
                    </div>
                  </div>

                  {/* 关键指标 */}
                  <div className="hidden sm:flex items-center gap-4 text-sm">
                    <div className="text-center">
                      <div className="text-xs text-gray-400">现价</div>
                      <div className="font-medium">{formatPrice(c.key_metrics.last_price || 0)}</div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-gray-400">涨跌</div>
                      <div className={`font-medium ${(c.key_metrics.change_rate || 0) >= 0 ? "text-red-600" : "text-green-600"}`}>
                        {(c.key_metrics.change_rate || 0) >= 0 ? "+" : ""}{formatPercent(c.key_metrics.change_rate || 0)}
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-xs text-gray-400">换手</div>
                      <div className="font-medium">{formatPercent(c.key_metrics.turnover_rate || 0)}</div>
                    </div>
                  </div>

                  {/* 总分 */}
                  <div className="text-right w-20">
                    <div className="text-2xl font-bold text-gray-900">{c.total_score.toFixed(0)}</div>
                    <div className={`text-xs font-medium bg-gradient-to-r ${verdictColors[c.verdict] || ""} bg-clip-text text-transparent`}>
                      {c.verdict}
                    </div>
                  </div>

                  {/* 展开箭头 */}
                  <i className={`fas fa-chevron-${isExpanded ? "up" : "down"} text-gray-400 text-xs`} />
                </div>

                {/* 评分条 */}
                <div className="px-4 pb-2">
                  <div className="w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${scoreBarColor(c.total_score)}`}
                      style={{ width: `${Math.min(100, c.total_score)}%` }}
                    />
                  </div>
                </div>

                {/* 展开详情 */}
                {isExpanded && (
                  <div className="px-4 pb-4 border-t border-gray-100 pt-3">
                    {/* 推荐理由 */}
                    <div className="mb-3">
                      <h4 className="text-xs font-semibold text-gray-500 mb-1.5">推荐理由</h4>
                      <div className="flex flex-wrap gap-1.5">
                        {c.reasons.map((r, i) => (
                          <span key={i} className="px-2 py-1 bg-gray-50 text-gray-700 rounded text-xs">
                            {r}
                          </span>
                        ))}
                      </div>
                    </div>

                    {/* 各维度评分 */}
                    <div className="mb-3">
                      <h4 className="text-xs font-semibold text-gray-500 mb-1.5">维度评分</h4>
                      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                        {Object.entries(c.scores).map(([key, val]) => (
                          <div key={key} className="bg-gray-50 rounded p-2">
                            <div className="text-[10px] text-gray-400">{dimNames[key] || key}</div>
                            <div className="flex items-center gap-1 mt-0.5">
                              <div className="flex-1 h-1 bg-gray-200 rounded-full overflow-hidden">
                                <div className={`h-full rounded-full ${scoreBarColor(val)}`} style={{ width: `${val}%` }} />
                              </div>
                              <span className="text-xs font-semibold text-gray-700 w-7 text-right">{val.toFixed(0)}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* 降权警告 */}
                    {c.penalty_reasons.length > 0 && (
                      <div className="bg-yellow-50 border border-yellow-200 rounded p-2 text-xs text-yellow-700">
                        <i className="fas fa-exclamation-triangle mr-1" />
                        降权因素: {c.penalty_reasons.join("; ")}
                      </div>
                    )}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
