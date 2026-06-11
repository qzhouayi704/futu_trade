// 多维信号驾驶舱聚合卡片 — 三维证据与一键操作
"use client";

import { useState, useEffect, useCallback } from "react";
import { Card } from "@/components/common";
import apiClient from "@/lib/api/client";

interface MultiDimensionalSignal {
  stock_code: string;
  stock_name: string;
  current_price: number;
  v1_sniper: {
    strength: number;
    label: string;
    ranking: number;
    signal_types: string[];
  } | null;
  v2_scorer: {
    score: number;
    mode: 'TREND' | 'BREAKOUT' | 'MOMENTUM';
    details: { name: string; score: number; max: number }[];
  } | null;
  momentum_engine: {
    verdict: 'STRONG_BUY' | 'MODERATE_BUY' | 'STRONG_SELL' | 'MODERATE_SELL' | 'WATCH';
    resonance_count: number;
    dimensions: string[];
  } | null;
  consensus: {
    verdict: 'STRONG_BUY' | 'BUY' | 'WATCH' | 'SELL';
    confidence: number;
    triggered_dimensions: number;
  };
}

interface MultiSignalDashboardProps {
  stockCode: string;
  onClose?: () => void;
}

export function MultiSignalDashboard({ stockCode, onClose }: MultiSignalDashboardProps) {
  const [data, setData] = useState<MultiDimensionalSignal | null>(null);
  const [loading, setLoading] = useState(true);
  const [cooldownTime, setCooldownTime] = useState<number | null>(null);

  const fetchSignalData = useCallback(async () => {
    if (!stockCode) return;
    setLoading(true);
    try {
      const res: any = await apiClient.get(`/signals/multi-dimensional/${stockCode}`);
      if (res?.success && res.data) {
        setData(res.data);
      }
    } catch (e) {
      console.error("加载多维信号失败:", e);
    } finally {
      setLoading(false);
    }
  }, [stockCode]);

  useEffect(() => {
    fetchSignalData();
    const timer = setInterval(fetchSignalData, 15000); // 15秒自动刷新
    return () => clearInterval(timer);
  }, [fetchSignalData]);

  // 15分钟屏蔽处理
  const handleMute = () => {
    const expires = Date.now() + 15 * 60 * 1000;
    setCooldownTime(expires);
    localStorage.setItem(`mute_signal_${stockCode}`, expires.toString());
  };

  useEffect(() => {
    const muted = localStorage.getItem(`mute_signal_${stockCode}`);
    if (muted) {
      const expires = parseInt(muted, 10);
      if (expires > Date.now()) {
        setCooldownTime(expires);
      } else {
        localStorage.removeItem(`mute_signal_${stockCode}`);
      }
    }
  }, [stockCode]);

  if (loading && !data) {
    return (
      <Card className="p-6 bg-slate-900/90 text-slate-100 border-slate-800">
        <div className="flex flex-col items-center justify-center py-10 space-y-3">
          <div className="w-8 h-8 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-slate-400">正在聚合 {stockCode} 的多维信号...</p>
        </div>
      </Card>
    );
  }

  if (!data) {
    return (
      <Card className="p-6 bg-slate-900/90 text-slate-100 border-slate-800">
        <div className="text-center py-6 text-slate-400">
          未找到 {stockCode} 的多维机会信号数据
        </div>
      </Card>
    );
  }

  const { consensus } = data;
  const confidencePercent = Math.round(consensus.confidence * 100);

  // 共识样式
  const getConsensusBadge = (verdict: string) => {
    switch (verdict) {
      case "STRONG_BUY":
        return { label: "强烈买入 (3维共振)", bg: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30", bar: "bg-emerald-500" };
      case "BUY":
        return { label: "偏多买入 (2维共振)", bg: "bg-teal-500/20 text-teal-400 border-teal-500/30", bar: "bg-teal-500" };
      case "SELL":
        return { label: "高危信号 (空头警告)", bg: "bg-rose-500/20 text-rose-400 border-rose-500/30", bar: "bg-rose-500" };
      default:
        return { label: "观望待定 (1维活跃)", bg: "bg-amber-500/20 text-amber-400 border-amber-500/30", bar: "bg-amber-500" };
    }
  };

  const badge = getConsensusBadge(consensus.verdict);

  return (
    <Card className="overflow-hidden border border-slate-800 bg-slate-950/95 shadow-2xl backdrop-blur-xl transition-all duration-300">
      <div className="p-5">
        {/* 头栏 */}
        <div className="flex items-center justify-between mb-4 border-b border-slate-800/80 pb-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg font-bold text-white tracking-tight">{data.stock_name}</span>
              <span className="text-xs text-slate-400 font-mono">{data.stock_code}</span>
            </div>
            <span className="text-sm font-semibold text-slate-300 font-mono">
              现价: <span className="text-indigo-400">{data.current_price?.toFixed(3) || "---"}</span>
            </span>
          </div>
          {onClose && (
            <button 
              onClick={onClose} 
              className="text-slate-400 hover:text-slate-200 transition-colors p-1"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>

        {/* 三个维度 */}
        <div className="grid grid-cols-3 gap-3.5 mb-5">
          {/* V1 - 狙击 */}
          <div className="bg-slate-900/60 rounded-xl p-3 border border-slate-800/60 flex flex-col justify-between min-h-[105px]">
            <div>
              <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold block mb-1">V1 盘中狙击</span>
              {data.v1_sniper ? (
                <>
                  <span className="text-sm font-bold text-emerald-400 block">{data.v1_sniper.label || "活跃"}</span>
                  <span className="text-[10px] text-slate-400 font-mono">强度: {data.v1_sniper.strength}/100</span>
                </>
              ) : (
                <span className="text-xs text-slate-500 italic block mt-1">无今日活跃</span>
              )}
            </div>
            {data.v1_sniper && data.v1_sniper.ranking > 0 && (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-950/40 text-emerald-400 border border-emerald-800/30 w-fit">
                机会榜 #{data.v1_sniper.ranking}
              </span>
            )}
          </div>

          {/* V2 - 选股 */}
          <div className="bg-slate-900/60 rounded-xl p-3 border border-slate-800/60 flex flex-col justify-between min-h-[105px]">
            <div>
              <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold block mb-1">V2 选股评分</span>
              {data.v2_scorer ? (
                <>
                  <span className="text-sm font-bold text-blue-400 block">{data.v2_scorer.score}分</span>
                  <span className="text-[10px] text-slate-400 uppercase tracking-widest">{data.v2_scorer.mode}</span>
                </>
              ) : (
                <span className="text-xs text-slate-500 italic block mt-1">未达评分线</span>
              )}
            </div>
            {data.v2_scorer && (
              <span className="text-[9px] px-1.5 py-0.5 rounded bg-blue-950/40 text-blue-400 border border-blue-800/30 w-fit">
                指标 {data.v2_scorer.details?.length || 0} 项
              </span>
            )}
          </div>

          {/* 动量 */}
          <div className="bg-slate-900/60 rounded-xl p-3 border border-slate-800/60 flex flex-col justify-between min-h-[105px]">
            <div>
              <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold block mb-1">动量引擎</span>
              {data.momentum_engine ? (
                <>
                  <span className={`text-sm font-bold block ${
                    data.momentum_engine.verdict.includes('BUY') ? 'text-cyan-400' : 'text-rose-400'
                  }`}>
                    {data.momentum_engine.verdict}
                  </span>
                  <span className="text-[10px] text-slate-400 block">共振: {data.momentum_engine.resonance_count}维</span>
                </>
              ) : (
                <span className="text-xs text-slate-500 italic block mt-1">无动量爆发</span>
              )}
            </div>
            {data.momentum_engine && data.momentum_engine.dimensions?.length > 0 && (
              <span className="text-[9px] text-slate-400 font-mono truncate">
                {data.momentum_engine.dimensions.join("+")}
              </span>
            )}
          </div>
        </div>

        {/* 决策建议与置信度 */}
        <div className="bg-slate-900/40 border border-slate-900 rounded-xl p-4 mb-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-400">🎯 决策建议:</span>
            <span className={`text-xs px-2.5 py-0.5 rounded-full border font-bold ${badge.bg}`}>
              {badge.label}
            </span>
          </div>

          {/* 置信度百分比条 */}
          <div>
            <div className="flex justify-between text-[11px] font-medium text-slate-400 mb-1">
              <span>置信度</span>
              <span className="font-mono text-indigo-400">{confidencePercent}%</span>
            </div>
            <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
              <div 
                className={`h-2 rounded-full transition-all duration-500 ${badge.bar}`}
                style={{ width: `${confidencePercent}%` }}
              />
            </div>
          </div>
        </div>

        {/* 一键快捷操作 */}
        <div className="flex items-center gap-2 flex-wrap">
          <button 
            onClick={() => window.open(`/stock-detail?code=${stockCode}`, "_blank")}
            className="flex-1 min-w-[70px] bg-slate-800 hover:bg-slate-700 text-slate-100 text-xs font-bold py-2 px-3 rounded-lg transition-colors"
          >
            详情
          </button>
          
          <button 
            onClick={async () => {
              // 触发模拟下单
              try {
                const isBuy = consensus.verdict !== 'SELL';
                await apiClient.post("/trading/execute", {
                  stock_code: stockCode,
                  stock_name: data.stock_name,
                  direction: isBuy ? "BUY" : "SELL",
                  price: data.current_price,
                  quantity: 100, // 默认手
                  simulated: true,
                  reason: `驾驶舱多维买入: ${consensus.verdict}`
                });
                alert("模拟交易委托成功！");
              } catch (err: any) {
                alert(`交易失败: ${err?.message || err}`);
              }
            }}
            className="flex-1 min-w-[80px] bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold py-2 px-3 rounded-lg transition-colors shadow-lg shadow-indigo-600/20"
          >
            模拟下单
          </button>

          <button 
            onClick={handleMute}
            disabled={cooldownTime !== null && cooldownTime > Date.now()}
            className={`flex-1 min-w-[90px] text-xs font-bold py-2 px-3 rounded-lg transition-colors ${
              cooldownTime !== null && cooldownTime > Date.now()
                ? "bg-slate-800/40 text-slate-600 cursor-not-allowed"
                : "bg-amber-600/20 text-amber-400 border border-amber-500/20 hover:bg-amber-600/30"
            }`}
          >
            {cooldownTime !== null && cooldownTime > Date.now() 
              ? `${Math.round((cooldownTime - Date.now()) / 1000 / 60)}m已屏蔽`
              : "屏蔽 15分钟"
            }
          </button>
        </div>
      </div>
    </Card>
  );
}
