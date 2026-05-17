// 突破扫描 — 独立页面
"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, Button } from "@/components/common";
import { useToast } from "@/components/common/Toast";
import {
  resistanceBreakoutApi,
  type ResistanceBreakoutCandidate,
} from "@/lib/api/resistance-breakout";

// 突破级别颜色
const levelColors: Record<string, string> = {
  "20日高": "bg-red-100 text-red-700 border-red-300",
  "10日高": "bg-orange-100 text-orange-700 border-orange-300",
  "5日高": "bg-amber-100 text-amber-700 border-amber-300",
};

// 日内突破标签颜色
const intradayColors: Record<string, string> = {
  volume_poc: "bg-violet-100 text-violet-700",
  big_order_sell: "bg-blue-100 text-blue-700",
  order_book_ask: "bg-cyan-100 text-cyan-700",
};

function scoreGradient(score: number): string {
  if (score >= 70) return "from-red-500 to-orange-500";
  if (score >= 50) return "from-blue-500 to-cyan-500";
  if (score >= 30) return "from-yellow-500 to-amber-500";
  return "from-gray-400 to-gray-300";
}

function formatMoney(val: number): string {
  if (Math.abs(val) >= 1e8) return (val / 1e8).toFixed(1) + "亿";
  if (Math.abs(val) >= 1e4) return (val / 1e4).toFixed(0) + "万";
  return val.toFixed(0);
}

export default function BreakoutPanel() {
  const { showToast } = useToast();
  const [candidates, setCandidates] = useState<ResistanceBreakoutCandidate[]>([]);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState("");
  const [timestamp, setTimestamp] = useState("");

  // 加载已有结果
  const loadResult = useCallback(async () => {
    try {
      const data = await resistanceBreakoutApi.getResult();
      if (data.candidates?.length) {
        setCandidates(data.candidates);
        setTimestamp(data.timestamp || "");
      }
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    loadResult();
  }, [loadResult]);

  // 触发扫描
  const handleTrigger = async () => {
    try {
      const res = await resistanceBreakoutApi.trigger();
      if (!res.success) {
        showToast("warning", "提示", res.message);
        return;
      }
      setRunning(true);
      setProgress("启动中...");
      showToast("success", "已启动", "突破扫描任务已启动");

      const poll = setInterval(async () => {
        try {
          const status = await resistanceBreakoutApi.getStatus();
          setProgress(status.progress || "");
          if (!status.running) {
            clearInterval(poll);
            setRunning(false);
            if (status.error) {
              showToast("error", "失败", status.error);
            } else {
              showToast("success", "完成", "突破扫描已完成");
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

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      {/* 标题栏 */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <svg className="w-6 h-6 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
            突破扫描
            {candidates.length > 0 && (
              <span className="text-sm font-medium text-red-600 bg-red-50 px-2 py-0.5 rounded">
                {candidates.length} 只信号
              </span>
            )}
          </h1>
          <p className="text-gray-500 mt-1 text-sm">
            筛选刚突破核心阻力位且大单资金持续流入的股票
            {timestamp && (
              <span className="ml-2 text-xs text-gray-400">
                扫描于 {new Date(timestamp).toLocaleString("zh-CN")}
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
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          {running ? progress : "开始扫描"}
        </Button>
      </div>

      {/* 空状态 */}
      {candidates.length === 0 && !running && (
        <Card className="text-center py-20">
          <svg className="w-16 h-16 text-gray-200 mx-auto mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
          </svg>
          <p className="text-gray-500 mb-2">暂无扫描结果</p>
          <p className="text-gray-400 text-sm mb-6">
            点击"开始扫描"，系统将筛选突破阻力位+资金流入的股票
          </p>
          <Button variant="primary" onClick={handleTrigger}>
            <svg className="w-4 h-4 mr-2 inline" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            立即扫描
          </Button>
        </Card>
      )}

      {/* 运行中 */}
      {running && candidates.length === 0 && (
        <Card className="text-center py-16">
          <i className="fas fa-spinner fa-spin text-4xl text-red-500 mb-4 block" />
          <p className="text-gray-700 font-medium">{progress || "扫描中..."}</p>
          <p className="text-gray-400 text-sm mt-2">正在检查阻力位突破+资金流入条件</p>
        </Card>
      )}

      {/* 候选列表 */}
      {candidates.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {candidates.map((c) => (
            <div
              key={c.code}
              className="relative overflow-hidden rounded-xl border border-gray-200 bg-white hover:shadow-lg transition-all hover:border-red-200"
            >
              {/* 评分角标 */}
              <div className={`absolute top-3 right-3 w-11 h-11 rounded-full bg-gradient-to-br ${scoreGradient(c.score)} flex items-center justify-center text-white text-sm font-bold shadow-md`}>
                {c.score.toFixed(0)}
              </div>

              {/* 股票信息 */}
              <div className="p-4 pb-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-bold text-gray-900 text-lg">{c.name || c.code}</span>
                  <span className="text-xs text-gray-400">{c.code}</span>
                </div>

                {/* 突破标签 */}
                <div className="flex flex-wrap gap-1.5 mb-3">
                  {c.daily_breakout_level && (
                    <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold border ${levelColors[c.daily_breakout_level] || "bg-gray-100 text-gray-600"}`}>
                      ↗ 突破{c.daily_breakout_level}
                    </span>
                  )}
                  {c.intraday_breakout && (
                    <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${intradayColors[c.intraday_level_type] || "bg-gray-100 text-gray-600"}`}>
                      ⚡ {c.intraday_level_label}
                    </span>
                  )}
                  {c.capital_continuity_days >= 2 && (
                    <span className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-100 text-emerald-700">
                      💰 连续{c.capital_continuity_days}日流入
                    </span>
                  )}
                </div>

                {/* 核心数据网格 */}
                <div className="grid grid-cols-3 gap-2 mb-3">
                  <div className="bg-gray-50 rounded-lg p-2 text-center">
                    <div className="text-[10px] text-gray-400">涨幅</div>
                    <div className={`text-sm font-bold ${c.change_pct >= 0 ? "text-red-600" : "text-green-600"}`}>
                      {c.change_pct >= 0 ? "+" : ""}{c.change_pct.toFixed(1)}%
                    </div>
                  </div>
                  <div className="bg-gray-50 rounded-lg p-2 text-center">
                    <div className="text-[10px] text-gray-400">突破幅度</div>
                    <div className="text-sm font-bold text-orange-600">
                      +{c.daily_breakout_pct.toFixed(1)}%
                    </div>
                  </div>
                  <div className="bg-gray-50 rounded-lg p-2 text-center">
                    <div className="text-[10px] text-gray-400">量比</div>
                    <div className="text-sm font-bold text-blue-600">
                      {c.volume_ratio.toFixed(1)}x
                    </div>
                  </div>
                </div>

                {/* 资金数据 */}
                <div className="grid grid-cols-3 gap-2 mb-3">
                  <div className="bg-gray-50 rounded-lg p-2 text-center">
                    <div className="text-[10px] text-gray-400">净流入占比</div>
                    <div className={`text-sm font-bold ${c.net_inflow_ratio > 0 ? "text-red-600" : "text-green-600"}`}>
                      {(c.net_inflow_ratio * 100).toFixed(1)}%
                    </div>
                  </div>
                  <div className="bg-gray-50 rounded-lg p-2 text-center">
                    <div className="text-[10px] text-gray-400">大单买入比</div>
                    <div className="text-sm font-bold text-orange-600">
                      {(c.big_order_buy_ratio * 100).toFixed(0)}%
                    </div>
                  </div>
                  <div className="bg-gray-50 rounded-lg p-2 text-center">
                    <div className="text-[10px] text-gray-400">主力净流入</div>
                    <div className={`text-sm font-bold ${c.main_net_inflow > 0 ? "text-red-600" : "text-green-600"}`}>
                      {formatMoney(c.main_net_inflow)}
                    </div>
                  </div>
                </div>

                {/* 信号描述 */}
                <div className="text-xs text-gray-600 bg-gradient-to-r from-red-50 to-orange-50 rounded-lg px-3 py-2 border border-red-100">
                  💡 {c.signal_note}
                </div>

                {/* 底部 */}
                <div className="flex items-center justify-between mt-2 text-[10px] text-gray-400">
                  <span>收盘 {c.close.toFixed(2)}</span>
                  <span>阻力位 {c.daily_resistance_price.toFixed(2)}</span>
                  <span>换手 {c.turnover_rate.toFixed(2)}%</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
