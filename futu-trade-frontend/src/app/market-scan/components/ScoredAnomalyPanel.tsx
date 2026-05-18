// 异动评分预警面板 — 展示盘中异动股经过 StockScorer 评分后的决策详情
// WebSocket 事件: anomaly_scored

"use client";

import { useState, useEffect } from "react";
import { useSocket } from "@/lib/socket";

interface ScoreDetail {
  dim: string;
  score: number;
  max: number;
  note: string;
}

interface TradeParams {
  trade_type: string;
  buy_dip_pct: number;
  take_profit_pct: number;
  stop_loss_pct: number;
  max_hold_days: number;
  confidence: string;
  reason: string;
}

interface ScoredAlert {
  code: string;
  name: string;
  price: number;
  change_rate: number;
  volume_ratio: number;
  anomaly_type: string;
  has_shrinkage: boolean;
  score: number;
  mode: string;
  passed: boolean;
  details: ScoreDetail[];
  trade_params: TradeParams | null;
  detected_at: string;
}

// 维度中文名映射
const dimLabels: Record<string, string> = {
  "5d_change": "5日涨跌",
  "5d_change(B-relax)": "5日涨跌(放宽)",
  "amplitude": "振幅",
  "vol_ratio": "量比",
  "flow": "资金流",
  "kline_pos": "K线位置",
  "prev_change": "前日涨幅",
  "kline_pos[R]": "K线位置",
  "5d_drop[R]": "5日跌幅",
  "prev_drop[R]": "前日跌幅",
  "rise_from_low[R]": "距低点反弹",
  "today_chg[R]": "今日涨跌",
  "flow_in[R]": "资金流入",
  "vol_ratio[R]": "量比",
  "amplitude[R]": "振幅",
};

// 模式标签
const modeStyles: Record<string, { text: string; bg: string }> = {
  TREND: { text: "趋势追涨", bg: "bg-red-500" },
  REVERSAL: { text: "超跌反弹", bg: "bg-emerald-500" },
};

function scoreBarColor(pct: number): string {
  if (pct >= 70) return "bg-gradient-to-r from-red-500 to-orange-400";
  if (pct >= 50) return "bg-gradient-to-r from-blue-500 to-cyan-400";
  if (pct >= 30) return "bg-gradient-to-r from-yellow-500 to-yellow-400";
  return "bg-gray-300";
}

export default function ScoredAnomalyPanel() {
  const { socket } = useSocket();
  const [alerts, setAlerts] = useState<ScoredAlert[]>([]);
  const [expandedCode, setExpandedCode] = useState<string | null>(null);
  const [scanTime, setScanTime] = useState("");
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (!socket) return;

    const handler = (data: { alerts: ScoredAlert[]; scan_time: string }) => {
      if (data.alerts?.length) {
        setAlerts((prev) => {
          // 合并新旧，相同code取最新
          const map = new Map(prev.map((a) => [a.code, a]));
          for (const a of data.alerts) map.set(a.code, a);
          return Array.from(map.values())
            .sort((a, b) => b.score - a.score)
            .slice(0, 10);
        });
        setScanTime(data.scan_time);
        setDismissed(false); // 有新预警时重新展示
      }
    };

    socket.on("anomaly_scored", handler);
    return () => { socket.off("anomaly_scored", handler); };
  }, [socket]);

  if (!alerts.length || dismissed) return null;

  return (
    <div className="mb-4 rounded-xl border-2 border-red-300 bg-gradient-to-r from-red-50 via-orange-50 to-amber-50 overflow-hidden shadow-lg animate-[pulse_2s_ease-in-out_1]">
      {/* 标题栏 */}
      <div className="flex items-center justify-between px-4 py-3 bg-gradient-to-r from-red-500/10 to-orange-500/10">
        <div className="flex items-center gap-2">
          <span className="text-xl animate-bounce">🚨</span>
          <span className="text-sm font-bold text-red-800">
            异动评分预警
          </span>
          <span className="inline-flex items-center justify-center min-w-[22px] h-5 px-1.5 rounded-full bg-red-500 text-white text-xs font-bold">
            {alerts.length}
          </span>
          {scanTime && (
            <span className="text-xs text-red-400">
              {scanTime} 发现
            </span>
          )}
        </div>
        <button
          onClick={() => setDismissed(true)}
          className="text-xs text-gray-400 hover:text-gray-600 px-2 py-1"
        >
          <i className="fas fa-times" />
        </button>
      </div>

      {/* 预警列表 */}
      <div className="px-4 pb-4 space-y-3 pt-2">
        {alerts.map((alert) => {
          const isExpanded = expandedCode === alert.code;
          const mode = modeStyles[alert.mode] || modeStyles.TREND;

          return (
            <div
              key={alert.code}
              className="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden"
            >
              {/* 概要行 */}
              <div
                className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-gray-50 transition-colors"
                onClick={() => setExpandedCode(isExpanded ? null : alert.code)}
              >
                <div className="flex items-center gap-3">
                  <div className="flex flex-col">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-gray-900">{alert.name}</span>
                      <span className="text-xs text-gray-400">{alert.code.replace("HK.", "")}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded text-white font-medium ${mode.bg}`}>
                        {mode.text}
                      </span>
                      {alert.has_shrinkage && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-100 text-green-700 font-medium">
                          缩量蓄势✓
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                      <span className="font-bold text-red-600">
                        {alert.change_rate >= 0 ? "+" : ""}{alert.change_rate.toFixed(1)}%
                      </span>
                      <span>量比 {alert.volume_ratio.toFixed(1)}</span>
                      <span>现价 {alert.price.toFixed(2)}</span>
                      <span className="text-gray-400">{alert.detected_at}</span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {/* 评分圆环 */}
                  <div className="relative w-12 h-12">
                    <svg className="w-12 h-12 -rotate-90" viewBox="0 0 36 36">
                      <circle cx="18" cy="18" r="15.5" fill="none" stroke="#e5e7eb" strokeWidth="3" />
                      <circle
                        cx="18" cy="18" r="15.5" fill="none"
                        stroke={alert.score >= 80 ? "#ef4444" : alert.score >= 60 ? "#3b82f6" : "#eab308"}
                        strokeWidth="3"
                        strokeDasharray={`${(alert.score / 100) * 97.4} 97.4`}
                        strokeLinecap="round"
                      />
                    </svg>
                    <div className="absolute inset-0 flex items-center justify-center">
                      <span className="text-sm font-bold text-gray-800">{alert.score}</span>
                    </div>
                  </div>
                  <i className={`fas fa-chevron-${isExpanded ? "up" : "down"} text-gray-400 text-xs`} />
                </div>
              </div>

              {/* 展开详情 */}
              {isExpanded && (
                <div className="border-t border-gray-100 px-4 py-3 space-y-3">
                  {/* 各维度评分 */}
                  <div>
                    <h4 className="text-xs font-semibold text-gray-500 mb-2">评分维度</h4>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                      {alert.details.map((d, i) => {
                        const pct = d.max > 0 ? (d.score / d.max) * 100 : 0;
                        const label = dimLabels[d.dim] || d.dim;
                        return (
                          <div key={i} className="bg-gray-50 rounded-lg p-2">
                            <div className="text-[10px] text-gray-400 truncate" title={d.note || label}>
                              {label}
                            </div>
                            <div className="flex items-center gap-1 mt-1">
                              <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                                <div
                                  className={`h-full rounded-full ${scoreBarColor(pct)}`}
                                  style={{ width: `${Math.min(100, pct)}%` }}
                                />
                              </div>
                              <span className="text-xs font-semibold text-gray-700 w-10 text-right">
                                {d.score}/{d.max}
                              </span>
                            </div>
                            {d.note && (
                              <div className="text-[9px] text-gray-400 mt-0.5 truncate" title={d.note}>
                                {d.note}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* 交易建议 */}
                  {alert.trade_params && (
                    <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
                      <h4 className="text-xs font-semibold text-blue-700 mb-2 flex items-center gap-1">
                        <i className="fas fa-chart-line" /> 交易建议
                      </h4>
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                        <div>
                          <div className="text-blue-400">入场方式</div>
                          <div className="font-bold text-blue-800">
                            回调{alert.trade_params.buy_dip_pct}%低吸
                          </div>
                        </div>
                        <div>
                          <div className="text-blue-400">入场价</div>
                          <div className="font-bold text-blue-800">
                            {(alert.price * (1 - alert.trade_params.buy_dip_pct / 100)).toFixed(2)}
                          </div>
                        </div>
                        <div>
                          <div className="text-blue-400">止损</div>
                          <div className="font-bold text-red-600">
                            -{alert.trade_params.stop_loss_pct}%
                            ({(alert.price * (1 - alert.trade_params.stop_loss_pct / 100)).toFixed(2)})
                          </div>
                        </div>
                        <div>
                          <div className="text-blue-400">目标</div>
                          <div className="font-bold text-emerald-600">
                            +{alert.trade_params.take_profit_pct}%
                            ({(alert.price * (1 + alert.trade_params.take_profit_pct / 100)).toFixed(2)})
                          </div>
                        </div>
                      </div>
                      {alert.trade_params.reason && (
                        <div className="mt-2 text-[11px] text-blue-600">
                          💡 {alert.trade_params.reason}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
