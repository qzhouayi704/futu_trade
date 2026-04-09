// 资金流向详情组件 - 展示单只股票的资金流向和大单追踪数据

"use client";

import type { CapitalFlowData } from "@/types/enhanced-heat";

interface CapitalFlowDetailProps {
  capitalFlow: CapitalFlowData | null;
  loading: boolean;
}

/** 金额格式化：>= 1亿显示"X.X亿"，>= 1万显示"X.X万"，否则原值 */
function formatAmount(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_0000_0000) {
    return (value / 1_0000_0000).toFixed(1) + "亿";
  }
  if (abs >= 1_0000) {
    return (value / 1_0000).toFixed(1) + "万";
  }
  return value.toFixed(0);
}

/** 根据 capital_score 获取信号配置 */
function getSignalConfig(score: number) {
  if (score >= 60) {
    return { label: "多", color: "text-red-500", bg: "bg-red-500/10", border: "border-red-500/30" };
  }
  if (score <= 40) {
    return { label: "空", color: "text-green-500", bg: "bg-green-500/10", border: "border-green-500/30" };
  }
  return { label: "中性", color: "text-gray-400", bg: "bg-gray-500/10", border: "border-gray-500/30" };
}

/** 获取评分条颜色 */
function getScoreBarColor(score: number): string {
  if (score >= 60) return "bg-red-500";
  if (score <= 40) return "bg-green-500";
  return "bg-gray-400";
}

/** 净流入数值颜色 */
function getInflowColor(value: number): string {
  if (value > 0) return "text-red-500";
  if (value < 0) return "text-green-500";
  return "text-gray-400";
}

/** 资金流向分级数据 */
export interface FlowLevel {
  name: string;
  inflow: number;
  outflow: number;
}

/** 从 CapitalFlowData 提取分级数据 */
export function extractFlowLevels(data: CapitalFlowData): FlowLevel[] {
  return [
    { name: "超大单", inflow: data.super_large_inflow, outflow: data.super_large_outflow },
    { name: "大单", inflow: data.large_inflow, outflow: data.large_outflow },
    { name: "中单", inflow: data.medium_inflow, outflow: data.medium_outflow },
    { name: "小单", inflow: data.small_inflow, outflow: data.small_outflow },
  ];
}

/** 骨架屏 */
function Skeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-20 bg-gray-700/50 rounded-lg" />
      <div className="h-6 bg-gray-700/50 rounded w-1/3" />
      <div className="space-y-3">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-12 bg-gray-700/50 rounded" />
        ))}
      </div>
      <div className="h-6 bg-gray-700/50 rounded w-1/3 mt-4" />
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-10 bg-gray-700/50 rounded" />
        ))}
      </div>
    </div>
  );
}

/** 水平柱状图 - 流入流出对比 */
function FlowBar({ inflow, outflow, maxValue }: { inflow: number; outflow: number; maxValue: number }) {
  const inflowPct = maxValue > 0 ? (inflow / maxValue) * 100 : 0;
  const outflowPct = maxValue > 0 ? (outflow / maxValue) * 100 : 0;

  return (
    <div className="flex items-center gap-1 h-5">
      <div className="flex-1 flex justify-end">
        <div
          className="h-full bg-red-500/70 rounded-l"
          style={{ width: `${inflowPct}%`, minWidth: inflowPct > 0 ? "2px" : "0" }}
        />
      </div>
      <div className="w-px h-full bg-gray-600" />
      <div className="flex-1">
        <div
          className="h-full bg-green-500/70 rounded-r"
          style={{ width: `${outflowPct}%`, minWidth: outflowPct > 0 ? "2px" : "0" }}
        />
      </div>
    </div>
  );
}

/** 综合资金信号区域 */
function SignalSection({ capitalFlow }: { capitalFlow: CapitalFlowData }) {
  const signal = getSignalConfig(capitalFlow.capital_score);
  const score = capitalFlow.capital_score;

  return (
    <div className={`rounded-lg border p-4 ${signal.bg} ${signal.border}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">综合资金信号</span>
          <span className={`text-2xl font-bold ${signal.color}`}>{signal.label}</span>
        </div>
        <div className="text-right">
          <span className="text-xs text-gray-400">主力净流入</span>
          <div className={`text-lg font-semibold ${getInflowColor(capitalFlow.main_net_inflow)}`}>
            {formatAmount(capitalFlow.main_net_inflow)}
          </div>
        </div>
      </div>
      {/* 评分条 */}
      <div>
        <div className="flex items-center justify-between text-xs text-gray-400 mb-1">
          <span>资金评分</span>
          <span>{score.toFixed(0)}</span>
        </div>
        <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${getScoreBarColor(score)}`}
            style={{ width: `${Math.min(Math.max(score, 0), 100)}%` }}
          />
        </div>
        <div className="flex justify-between text-[10px] text-gray-500 mt-0.5">
          <span>0</span>
          <span>40</span>
          <span>60</span>
          <span>100</span>
        </div>
      </div>
    </div>
  );
}

/** 资金流向分级数据区域 */
function FlowLevelsSection({ capitalFlow }: { capitalFlow: CapitalFlowData }) {
  const levels = extractFlowLevels(capitalFlow);
  const maxValue = Math.max(
    ...levels.flatMap((l) => [l.inflow, l.outflow]),
    1 // 避免除零
  );

  return (
    <div>
      <h4 className="text-sm font-medium text-gray-300 mb-3">资金流向分级</h4>
      <div className="space-y-2">
        {levels.map((level) => {
          const net = level.inflow - level.outflow;
          return (
            <div key={level.name} className="bg-gray-800/50 rounded p-2">
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-gray-400 w-12">{level.name}</span>
                <span className="text-red-400">{formatAmount(level.inflow)}</span>
                <span className="text-green-400">{formatAmount(level.outflow)}</span>
                <span className={`font-medium ${getInflowColor(net)}`}>
                  {formatAmount(net)}
                </span>
              </div>
              <FlowBar inflow={level.inflow} outflow={level.outflow} maxValue={maxValue} />
            </div>
          );
        })}
      </div>
      {/* 表头说明 */}
      <div className="flex items-center justify-between text-[10px] text-gray-500 mt-1 px-2">
        <span className="w-12">级别</span>
        <span>流入</span>
        <span>流出</span>
        <span>净流入</span>
      </div>
    </div>
  );
}

/** 大单多空分析区域（从资金流向数据提取） */
function BigOrdersSection({ capitalFlow }: { capitalFlow: CapitalFlowData }) {
  // 超大单 + 大单 = 主力资金
  const buyAmount = capitalFlow.super_large_inflow + capitalFlow.large_inflow;
  const sellAmount = capitalFlow.super_large_outflow + capitalFlow.large_outflow;
  const netAmount = buyAmount - sellAmount;
  const totalAmount = buyAmount + sellAmount;
  const buyPct = totalAmount > 0 ? (buyAmount / totalAmount) * 100 : 50;
  const ratio = sellAmount > 0 ? buyAmount / sellAmount : (buyAmount > 0 ? 10.0 : 1.0);

  // 大单强度：净流入 / 总流量，映射到 [-1, 1]
  const strength = totalAmount > 0 ? netAmount / totalAmount : 0;

  // 多空判断
  const signal = strength > 0.1 ? "多" : strength < -0.1 ? "空" : "中性";
  const signalColor = strength > 0.1 ? "text-red-400" : strength < -0.1 ? "text-green-400" : "text-gray-400";

  return (
    <div>
      <h4 className="text-sm font-medium text-gray-300 mb-3">大单多空分析</h4>
      <div className="space-y-3">
        {/* 多空信号 + 净流入 */}
        <div className="flex items-center justify-between bg-gray-800/50 rounded p-3">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400">主力方向</span>
            <span className={`text-xl font-bold ${signalColor}`}>{signal}</span>
          </div>
          <div className="text-right">
            <span className="text-[10px] text-gray-500">大单净流入</span>
            <div className={`text-sm font-medium ${getInflowColor(netAmount)}`}>
              {formatAmount(netAmount)}
            </div>
          </div>
        </div>

        {/* 买入卖出金额 */}
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-gray-800/50 rounded p-2">
            <div className="text-[10px] text-gray-500">大单买入</div>
            <div className="text-sm font-medium text-red-400">{formatAmount(buyAmount)}</div>
          </div>
          <div className="bg-gray-800/50 rounded p-2">
            <div className="text-[10px] text-gray-500">大单卖出</div>
            <div className="text-sm font-medium text-green-400">{formatAmount(sellAmount)}</div>
          </div>
        </div>

        {/* 买卖比 */}
        <div className="bg-gray-800/50 rounded p-2">
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-gray-400">大单买卖比</span>
            <span className={`font-medium ${ratio >= 1 ? "text-red-400" : "text-green-400"}`}>
              {ratio.toFixed(2)}
            </span>
          </div>
          <div className="flex h-3 rounded-full overflow-hidden bg-gray-700">
            <div className="bg-red-500/80 transition-all" style={{ width: `${buyPct}%` }} />
            <div className="bg-green-500/80 transition-all" style={{ width: `${100 - buyPct}%` }} />
          </div>
          <div className="flex justify-between text-[10px] text-gray-500 mt-0.5">
            <span>买 {buyPct.toFixed(0)}%</span>
            <span>卖 {(100 - buyPct).toFixed(0)}%</span>
          </div>
        </div>

        {/* 大单强度 */}
        <div className="bg-gray-800/50 rounded p-2">
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-gray-400">大单强度</span>
            <span className={`font-medium ${strength > 0 ? "text-red-400" : strength < 0 ? "text-green-400" : "text-gray-400"}`}>
              {strength.toFixed(2)}
            </span>
          </div>
          <div className="relative h-3 bg-gray-700 rounded-full overflow-hidden">
            {strength >= 0 ? (
              <div
                className="absolute left-1/2 h-full bg-red-500/70 rounded-r-full"
                style={{ width: `${strength * 50}%` }}
              />
            ) : (
              <div
                className="absolute right-1/2 h-full bg-green-500/70 rounded-l-full"
                style={{ width: `${Math.abs(strength) * 50}%` }}
              />
            )}
            <div className="absolute left-1/2 top-0 w-px h-full bg-gray-500" />
          </div>
          <div className="flex justify-between text-[10px] text-gray-500 mt-0.5">
            <span>-1</span>
            <span>0</span>
            <span>1</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/** 资金流向详情组件 */
export default function CapitalFlowDetail({ capitalFlow, loading }: CapitalFlowDetailProps) {
  if (loading) {
    return <Skeleton />;
  }

  if (!capitalFlow) {
    return (
      <div className="text-center text-gray-500 text-sm py-8">
        暂无资金流向数据
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <SignalSection capitalFlow={capitalFlow} />
      <FlowLevelsSection capitalFlow={capitalFlow} />
      <BigOrdersSection capitalFlow={capitalFlow} />
    </div>
  );
}
