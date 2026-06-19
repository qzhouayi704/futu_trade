// 信号强度 TOP 5 排名面板 — 独立组件
// 实时展示机会/风险排名，3分钟自动刷新

"use client";

import { useSniperRanking } from "@/app/hooks/useSniper";

interface RankItem {
  stock_code: string;
  stock_name: string;
  score: number;
  chg: number;
  detail: {
    window: number;
    flow: number;
    momentum: number;
    signal: number;
    w_net: number;
    w_chg: number;
    combo?: number;
    multi_mega?: number;
    multi_accel?: number;
  };
}

interface Ranking {
  opportunity: RankItem[];
  risk: RankItem[];
  updated_at: string | null;
}

export function SignalRankingPanel() {
  // 共享 RQ 缓存：tab 切换不再重复请求 /sniper/ranking
  const { data, isLoading: loading } = useSniperRanking();
  const ranking: Ranking = (data as Ranking) ?? { opportunity: [], risk: [], updated_at: null };

  const hasData = ranking.opportunity.length > 0 || ranking.risk.length > 0;

  if (loading) {
    return (
      <div className="rounded-xl border border-border bg-card p-4">
        <div className="text-center text-sm text-muted-foreground py-2">加载排名中...</div>
      </div>
    );
  }

  const medalColors = [
    "bg-amber-400 text-white",      // 🥇
    "bg-gray-300 text-gray-700",     // 🥈
    "bg-amber-600 text-white",       // 🥉
    "bg-gray-200 text-gray-600",
    "bg-gray-200 text-gray-600",
  ];

  return (
    <div className="rounded-xl border border-border bg-card shadow-sm">
      {/* 标题 */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border">
        <h3 className="text-sm font-bold text-foreground flex items-center gap-1.5">
          <span className="text-base">🏆</span>
          信号强度 TOP 5
        </h3>
        <span className="text-[10px] text-muted-foreground">
          {ranking.updated_at ? `${ranking.updated_at} 更新` : ""}
        </span>
      </div>

      {/* 双列(移动端单列) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-border">
        {/* 🟢 机会 */}
        <div className="p-3">
          <div className="text-[11px] font-bold text-emerald-600 dark:text-emerald-400 mb-2 flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
            机会排名
          </div>
          {ranking.opportunity.length === 0 ? (
            <div className="text-[11px] text-muted-foreground py-4 text-center">暂无机会信号</div>
          ) : (
            <div className="space-y-1.5">
              {ranking.opportunity.map((item, idx) => (
                <div
                  key={item.stock_code}
                  className={`flex items-center justify-between px-2 py-1.5 rounded-lg transition-colors ${
                    idx === 0
                      ? "bg-emerald-500/10 border border-emerald-500/30"
                      : "hover:bg-muted"
                  }`}
                >
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className={`text-[9px] font-bold w-4 h-4 flex items-center justify-center rounded-full shrink-0 ${medalColors[idx] || medalColors[4]}`}>
                      {idx + 1}
                    </span>
                    <span className={`text-[12px] font-semibold truncate ${idx === 0 ? "text-emerald-700 dark:text-emerald-300" : "text-foreground"}`}>
                      {item.stock_name}
                    </span>
                  </div>
                  <div className="flex items-center gap-1 shrink-0 ml-1">
                    {/* 加分标签 */}
                    {item.detail?.combo ? (
                      <span className="text-[8px] px-1 py-px rounded-full bg-amber-100 text-amber-700 font-bold border border-amber-200/60">
                        共振
                      </span>
                    ) : null}
                    {item.detail?.multi_mega ? (
                      <span className="text-[8px] px-1 py-px rounded-full bg-purple-100 text-purple-700 font-bold border border-purple-200/60">
                        多M
                      </span>
                    ) : null}
                    {item.detail?.multi_accel ? (
                      <span className="text-[8px] px-1 py-px rounded-full bg-blue-100 text-blue-700 font-bold border border-blue-200/60">
                        加速
                      </span>
                    ) : null}
                    {/* 涨跌幅 */}
                    <span className={`text-[10px] font-bold tabular-nums min-w-[40px] text-right ${
                      item.chg >= 0 ? "text-red-500" : "text-green-600"
                    }`}>
                      {item.chg >= 0 ? "+" : ""}{item.chg}%
                    </span>
                    {/* 评分 */}
                    <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold tabular-nums ${
                      item.score >= 60 ? "bg-emerald-500 text-white" :
                      item.score >= 40 ? "bg-emerald-400 text-white" :
                      "bg-emerald-200 text-emerald-800"
                    }`}>
                      {item.score}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 🔴 风险 */}
        <div className="p-3">
          <div className="text-[11px] font-bold text-red-600 dark:text-red-400 mb-2 flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500"></span>
            风险排名
          </div>
          {ranking.risk.length === 0 ? (
            <div className="text-[11px] text-muted-foreground py-4 text-center">暂无风险信号</div>
          ) : (
            <div className="space-y-1.5">
              {ranking.risk.map((item, idx) => (
                <div
                  key={item.stock_code}
                  className={`flex items-center justify-between px-2 py-1.5 rounded-lg transition-colors ${
                    idx === 0
                      ? "bg-red-500/10 border border-red-500/30"
                      : "hover:bg-muted"
                  }`}
                >
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className={`text-[9px] font-bold w-4 h-4 flex items-center justify-center rounded-full shrink-0 ${
                      idx === 0 ? "bg-red-500 text-white" : "bg-muted text-muted-foreground"
                    }`}>
                      {idx + 1}
                    </span>
                    <span className={`text-[12px] font-semibold truncate ${idx === 0 ? "text-red-700 dark:text-red-300" : "text-foreground"}`}>
                      {item.stock_name}
                    </span>
                  </div>
                  <div className="flex items-center gap-1 shrink-0 ml-1">
                    <span className={`text-[10px] font-bold tabular-nums min-w-[40px] text-right ${
                      item.chg >= 0 ? "text-red-500" : "text-green-600"
                    }`}>
                      {item.chg >= 0 ? "+" : ""}{item.chg}%
                    </span>
                    <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold tabular-nums ${
                      item.score >= 60 ? "bg-red-500 text-white" :
                      item.score >= 40 ? "bg-red-400 text-white" :
                      "bg-red-200 text-red-800"
                    }`}>
                      {item.score}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
