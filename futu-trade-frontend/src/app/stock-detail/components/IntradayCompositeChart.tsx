/**
 * 日内分时走势 + 成交强度叠加图
 *
 * 一张图看清：价格走势 + 买卖力量对比 + 大单标记
 * - 上半部分：分时价格线 + 均价线
 * - 下半部分：买卖力量柱状图（红=主动买入，绿=主动卖出）
 * - 大单用金色菱形标记在价格线上
 */
"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  getIntradayComposite,
  type IntradayCompositeData,
  type PriceLine,
  type TickerStrength,
  type BigOrder,
} from "@/lib/api/stock-detail-composite";

interface Props {
  stockCode: string;
}

export function IntradayCompositeChart({ stockCode }: Props) {
  const [data, setData] = useState<IntradayCompositeData | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchData = useCallback(async () => {
    if (!stockCode) return;
    setLoading(true);
    try {
      const res = await getIntradayComposite(stockCode);
      if (res.success && res.data) setData(res.data);
    } catch {
      /* ignore */
    }
    setLoading(false);
  }, [stockCode]);

  useEffect(() => {
    fetchData();
    const t = setInterval(fetchData, 15_000);
    return () => clearInterval(t);
  }, [fetchData]);

  if (loading && !data) {
    return (
      <div className="bg-card rounded-xl border border-border p-6 animate-pulse">
        <div className="h-4 w-48 bg-muted rounded mb-4" />
        <div className="h-[300px] bg-muted/50 rounded" />
      </div>
    );
  }

  if (!data || !data.price_line.length) {
    return (
      <div className="bg-card rounded-xl border border-border p-6 text-center text-muted-foreground text-sm">
        暂无分时数据
      </div>
    );
  }

  return (
    <div className="bg-card rounded-xl border border-border overflow-hidden">
      {/* Header */}
      <div className="px-4 py-2.5 bg-gradient-to-r from-blue-500/8 to-cyan-500/8 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-foreground">📈 日内分时 · 成交强度</span>
          {data.big_orders.length > 0 && (
            <span className="px-1.5 py-0.5 text-[10px] rounded bg-amber-500/15 text-amber-600 border border-amber-500/20">
              {data.big_orders.length}笔大单
            </span>
          )}
        </div>
        <span className="text-[10px] text-muted-foreground">15s刷新</span>
      </div>

      {/* Chart Area */}
      <div className="px-4 py-3">
        <PriceChart
          priceData={data.price_line}
          tickerData={data.ticker_strength}
          bigOrders={data.big_orders}
        />
      </div>
    </div>
  );
}

// ==================== SVG Chart ====================

function PriceChart({
  priceData,
  tickerData,
  bigOrders,
}: {
  priceData: PriceLine[];
  tickerData: TickerStrength[];
  bigOrders: BigOrder[];
}) {
  const W = 800;
  const PRICE_H = 180;
  const BAR_H = 80;
  const TOTAL_H = PRICE_H + BAR_H + 20;
  const PAD = { l: 55, r: 15, t: 10, b: 25 };
  const chartW = W - PAD.l - PAD.r;

  // Price bounds
  const prices = priceData.map((d) => d.price).filter(Boolean);
  const avgPrices = priceData.map((d) => d.avg_price).filter(Boolean);
  const allPrices = [...prices, ...avgPrices];
  const minP = Math.min(...allPrices);
  const maxP = Math.max(...allPrices);
  const rangeP = maxP - minP || 1;
  const padP = rangeP * 0.08;

  // Ticker strength bounds
  const maxStrength = Math.max(
    ...tickerData.map((d) => Math.max(d.buy_volume, d.sell_volume)),
    1
  );

  // X mapping - by index
  const xScale = (i: number, total: number) =>
    PAD.l + (i / Math.max(total - 1, 1)) * chartW;

  // Y mapping - price
  const yPrice = (p: number) =>
    PAD.t + PRICE_H - ((p - minP + padP) / (rangeP + padP * 2)) * PRICE_H;

  // Y mapping - bars
  const yBar = (vol: number) =>
    (vol / maxStrength) * (BAR_H - 10);

  const barTop = PRICE_H + 15;

  // Price line path
  const pricePath = priceData
    .map((d, i) => {
      const x = xScale(i, priceData.length);
      const y = yPrice(d.price);
      return `${i === 0 ? "M" : "L"}${x},${y}`;
    })
    .join(" ");

  // Avg price path
  const avgPath = priceData
    .filter((d) => d.avg_price > 0)
    .map((d, i) => {
      const x = xScale(priceData.indexOf(d), priceData.length);
      const y = yPrice(d.avg_price);
      return `${i === 0 ? "M" : "L"}${x},${y}`;
    })
    .join(" ");

  // Area fill under price line
  const firstX = xScale(0, priceData.length);
  const lastX = xScale(priceData.length - 1, priceData.length);
  const areaPath = `${pricePath} L${lastX},${PAD.t + PRICE_H} L${firstX},${PAD.t + PRICE_H} Z`;

  // Build ticker bar index map (by time prefix matching)
  const tickerMap = useMemo(() => {
    const m: Record<string, TickerStrength> = {};
    tickerData.forEach((t) => {
      // Extract HH:MM from time string
      const match = t.time.match(/(\d{2}:\d{2})/);
      if (match) m[match[1]] = t;
    });
    return m;
  }, [tickerData]);

  // Map price data to time labels
  const timeLabels = useMemo(() => {
    const labels: { i: number; label: string }[] = [];
    const step = Math.max(1, Math.floor(priceData.length / 6));
    for (let i = 0; i < priceData.length; i += step) {
      const t = priceData[i].time;
      const match = t.match(/(\d{2}:\d{2})/);
      if (match) labels.push({ i, label: match[1] });
    }
    return labels;
  }, [priceData]);

  // Price Y-axis labels
  const priceLabels = useMemo(() => {
    const steps = 5;
    const arr = [];
    for (let i = 0; i <= steps; i++) {
      const p = minP - padP + ((rangeP + padP * 2) / steps) * i;
      arr.push({ price: p, y: yPrice(p) });
    }
    return arr;
  }, [minP, maxP, rangeP, padP]);

  // Big order markers
  const bigOrderMarkers = useMemo(() => {
    if (!bigOrders.length || !priceData.length) return [];

    return bigOrders.map((bo) => {
      // Find closest price point by time
      const boTime = bo.time;
      let bestIdx = 0;
      let bestDist = Infinity;
      priceData.forEach((p, i) => {
        // Simple time comparison
        const dist = Math.abs(
          new Date(p.time).getTime() - new Date(boTime).getTime()
        );
        if (dist < bestDist) {
          bestDist = dist;
          bestIdx = i;
        }
      });

      return {
        x: xScale(bestIdx, priceData.length),
        y: yPrice(bo.price),
        direction: bo.direction,
        volume: bo.volume,
        turnover: bo.turnover,
      };
    });
  }, [bigOrders, priceData]);

  // Current price info
  const lastPrice = priceData[priceData.length - 1];
  const firstPrice = priceData[0];
  const priceChange = lastPrice && firstPrice
    ? ((lastPrice.price - firstPrice.price) / firstPrice.price * 100)
    : 0;
  const isUp = priceChange >= 0;

  return (
    <div>
      {/* Current price badge */}
      <div className="flex items-center gap-3 mb-2">
        <span className={`text-lg font-bold tabular-nums ${isUp ? "text-red-500" : "text-green-500"}`}>
          {lastPrice?.price?.toFixed(3)}
        </span>
        <span className={`text-sm px-1.5 py-0.5 rounded ${isUp ? "bg-red-500/10 text-red-500" : "bg-green-500/10 text-green-500"}`}>
          {isUp ? "+" : ""}{priceChange.toFixed(2)}%
        </span>
        {lastPrice?.avg_price > 0 && (
          <span className="text-xs text-muted-foreground">
            均价 {lastPrice.avg_price.toFixed(3)}
          </span>
        )}
      </div>

      <svg viewBox={`0 0 ${W} ${TOTAL_H}`} className="w-full" style={{ maxHeight: 340 }}>
        <defs>
          <linearGradient id="priceAreaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={isUp ? "rgb(239,68,68)" : "rgb(34,197,94)"} stopOpacity="0.15" />
            <stop offset="100%" stopColor={isUp ? "rgb(239,68,68)" : "rgb(34,197,94)"} stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Grid lines */}
        {priceLabels.map((pl, i) => (
          <g key={i}>
            <line x1={PAD.l} y1={pl.y} x2={W - PAD.r} y2={pl.y} stroke="var(--border)" strokeWidth="0.5" strokeDasharray="3,3" />
            <text x={PAD.l - 5} y={pl.y + 3} textAnchor="end" fill="var(--muted-foreground)" fontSize="9" fontFamily="monospace">
              {pl.price.toFixed(3)}
            </text>
          </g>
        ))}

        {/* Area fill */}
        <path d={areaPath} fill="url(#priceAreaGrad)" />

        {/* Avg price line */}
        {avgPath && (
          <path d={avgPath} fill="none" stroke="rgb(99,102,241)" strokeWidth="1" strokeDasharray="4,3" opacity="0.6" />
        )}

        {/* Price line */}
        <path d={pricePath} fill="none" stroke={isUp ? "rgb(239,68,68)" : "rgb(34,197,94)"} strokeWidth="1.5" />

        {/* Separator */}
        <line x1={PAD.l} y1={barTop - 5} x2={W - PAD.r} y2={barTop - 5} stroke="var(--border)" strokeWidth="0.5" />

        {/* Ticker strength bars */}
        {priceData.map((p, i) => {
          const timeMatch = p.time.match(/(\d{2}:\d{2})/);
          if (!timeMatch) return null;
          const td = tickerMap[timeMatch[1]];
          if (!td) return null;

          const x = xScale(i, priceData.length);
          const barW = Math.max(1, chartW / priceData.length * 0.6);
          const buyH = yBar(td.buy_volume);
          const sellH = yBar(td.sell_volume);

          return (
            <g key={`bar-${i}`}>
              {/* Buy bar (red, upward from baseline) */}
              <rect
                x={x - barW / 2}
                y={barTop + (BAR_H - 10) / 2 - buyH}
                width={barW / 2}
                height={buyH}
                fill="rgb(239,68,68)"
                opacity="0.7"
                rx="0.5"
              />
              {/* Sell bar (green, downward from baseline) */}
              <rect
                x={x}
                y={barTop + (BAR_H - 10) / 2}
                width={barW / 2}
                height={sellH}
                fill="rgb(34,197,94)"
                opacity="0.7"
                rx="0.5"
              />
            </g>
          );
        })}

        {/* Big order markers */}
        {bigOrderMarkers.map((m, i) => (
          <g key={`bo-${i}`}>
            <polygon
              points={`${m.x},${m.y - 8} ${m.x + 5},${m.y} ${m.x},${m.y + 8} ${m.x - 5},${m.y}`}
              fill={m.direction === "BUY" ? "rgb(245,158,11)" : "rgb(168,85,247)"}
              stroke="white"
              strokeWidth="0.5"
              opacity="0.9"
            />
          </g>
        ))}

        {/* X axis time labels */}
        {timeLabels.map((tl) => (
          <text
            key={tl.i}
            x={xScale(tl.i, priceData.length)}
            y={TOTAL_H - 5}
            textAnchor="middle"
            fill="var(--muted-foreground)"
            fontSize="9"
            fontFamily="monospace"
          >
            {tl.label}
          </text>
        ))}

        {/* Legend */}
        <g transform={`translate(${PAD.l + 5}, ${barTop + BAR_H - 5})`}>
          <rect x="0" y="-6" width="6" height="6" fill="rgb(239,68,68)" opacity="0.7" rx="1" />
          <text x="9" y="0" fontSize="8" fill="var(--muted-foreground)">主买</text>
          <rect x="35" y="-6" width="6" height="6" fill="rgb(34,197,94)" opacity="0.7" rx="1" />
          <text x="44" y="0" fontSize="8" fill="var(--muted-foreground)">主卖</text>
          <polygon points="74,-5 77,-1 74,3 71,-1" fill="rgb(245,158,11)" />
          <text x="80" y="0" fontSize="8" fill="var(--muted-foreground)">大单买</text>
          <polygon points="118,-5 121,-1 118,3 115,-1" fill="rgb(168,85,247)" />
          <text x="124" y="0" fontSize="8" fill="var(--muted-foreground)">大单卖</text>
        </g>
      </svg>
    </div>
  );
}
