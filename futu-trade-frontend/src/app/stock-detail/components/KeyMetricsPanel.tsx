// 关键指标面板 — 核心数字网格展示
"use client";

import type { TopHotStock } from "@/types";

interface Props {
  stock: TopHotStock | null;
}

interface MetricItem {
  label: string;
  value: string;
  sub?: string;
  color?: string;
  icon?: string;
}

export default function KeyMetricsPanel({ stock }: Props) {
  if (!stock) return null;

  const cf = stock.capital_flow_summary;
  const consensus = stock.consensus;
  const engines = consensus?.engines || {};
  const pricePos = engines.price_position;
  const capitalFlow = engines.capital_flow;

  const metrics: MetricItem[] = [
    {
      icon: "📊",
      label: "量比",
      value: stock.volume_ratio?.toFixed(2) || "-",
      sub: (stock.volume_ratio ?? 0) >= 1.5 ? "放量" : (stock.volume_ratio ?? 0) >= 1.0 ? "正常" : "缩量",
      color: (stock.volume_ratio ?? 0) >= 1.5 ? "green" : (stock.volume_ratio ?? 0) >= 1.0 ? "blue" : "red",
    },
    {
      icon: "🔄",
      label: "换手率",
      value: stock.turnover_rate?.toFixed(2) + "%" || "-",
      sub: stock.turnover_rate > 5 ? "活跃" : stock.turnover_rate > 2 ? "正常" : "低迷",
      color: stock.turnover_rate > 5 ? "green" : "blue",
    },
    {
      icon: "📐",
      label: "振幅",
      value: stock.amplitude?.toFixed(2) + "%" || "-",
      sub: stock.amplitude > 10 ? "高波动" : stock.amplitude > 5 ? "中等" : "低波动",
      color: stock.amplitude > 10 ? "orange" : "blue",
    },
    {
      icon: "💰",
      label: "资金评分",
      value: cf?.capital_score?.toFixed(0) || "-",
      sub: (cf?.capital_score ?? 0) >= 70 ? "强" : (cf?.capital_score ?? 0) >= 50 ? "中" : "弱",
      color: (cf?.capital_score ?? 0) >= 70 ? "green" : (cf?.capital_score ?? 0) >= 50 ? "blue" : "red",
    },
    {
      icon: "🐋",
      label: "大单买比",
      value: cf?.big_order_buy_ratio ? (cf.big_order_buy_ratio * 100).toFixed(1) + "%" : "-",
      sub: (cf?.big_order_buy_ratio ?? 0) > 0.55 ? "买入主导" : (cf?.big_order_buy_ratio ?? 0) > 0.45 ? "均衡" : "卖出主导",
      color: (cf?.big_order_buy_ratio ?? 0) > 0.55 ? "green" : (cf?.big_order_buy_ratio ?? 0) > 0.45 ? "blue" : "red",
    },
    {
      icon: "💵",
      label: "主力净流入",
      value: formatFlow(cf?.main_net_inflow),
      sub: (cf?.main_net_inflow ?? 0) > 0 ? "净流入" : "净流出",
      color: (cf?.main_net_inflow ?? 0) > 0 ? "green" : "red",
    },
    {
      icon: "📍",
      label: "价格位置",
      value: pricePos ? pricePos.score.toString() : "-",
      sub: pricePos?.details?.find(d => d.label === "入场信号")?.value || "-",
      color: (pricePos?.score ?? 50) > 60 ? "orange" : "blue",
    },
    {
      icon: "🎯",
      label: "共识判定",
      value: consensus?.verdict_label || "-",
      sub: `信心 ${((consensus?.confidence ?? 0) * 100).toFixed(0)}%`,
      color: consensus?.verdict === "buy" ? "green" : consensus?.verdict === "watch" ? "blue" : "amber",
    },
  ];

  const colorMap: Record<string, string> = {
    green: "text-green-600 bg-green-500/10 border-green-500/20",
    blue: "text-blue-600 bg-blue-500/10 border-blue-500/20",
    red: "text-red-500 bg-red-500/10 border-red-500/20",
    amber: "text-amber-600 bg-amber-500/10 border-amber-500/20",
    orange: "text-orange-600 bg-orange-500/10 border-orange-500/20",
  };

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {metrics.map((m, i) => {
        const c = colorMap[m.color || "blue"];
        return (
          <div key={i} className={`rounded-xl border p-3 ${c} transition-all hover:scale-[1.02]`}>
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-sm">{m.icon}</span>
              <span className="text-[11px] font-medium opacity-80">{m.label}</span>
            </div>
            <div className="text-xl font-bold tabular-nums leading-tight">{m.value}</div>
            {m.sub && <div className="text-[10px] opacity-70 mt-0.5">{m.sub}</div>}
          </div>
        );
      })}
    </div>
  );
}

function formatFlow(v?: number): string {
  if (v == null) return "-";
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "-";
  if (abs >= 1e8) return sign + (abs / 1e8).toFixed(2) + "亿";
  if (abs >= 1e4) return sign + (abs / 1e4).toFixed(0) + "万";
  return sign + abs.toFixed(0);
}
