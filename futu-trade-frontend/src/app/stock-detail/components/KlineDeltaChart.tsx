/**
 * 5分钟K线 + Delta买卖净力量 联动图
 *
 * 上半部分：5分钟蜡烛图
 * 下半部分：Delta柱状图（红=买方主导，绿=卖方主导，亮色=极端值）
 */
"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  getKlineDelta,
  type KlineDeltaData,
  type KlineDeltaCandle,
} from "@/lib/api/stock-detail-composite";

interface Props {
  stockCode: string;
}

export function KlineDeltaChart({ stockCode }: Props) {
  const [data, setData] = useState<KlineDeltaData | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchData = useCallback(async () => {
    if (!stockCode) return;
    setLoading(true);
    try {
      const res = await getKlineDelta(stockCode, 48);
      if (res.success && res.data) setData(res.data);
    } catch { /* ignore */ }
    setLoading(false);
  }, [stockCode]);

  useEffect(() => {
    fetchData();
    const t = setInterval(fetchData, 30_000);
    return () => clearInterval(t);
  }, [fetchData]);

  if (loading && !data) {
    return (
      <div className="bg-card rounded-xl border border-border p-6 animate-pulse">
        <div className="h-4 w-52 bg-muted rounded mb-4" />
        <div className="h-[280px] bg-muted/50 rounded" />
      </div>
    );
  }

  if (!data || !data.candles.length) {
    return (
      <div className="bg-card rounded-xl border border-border p-6 text-center text-muted-foreground text-sm">
        暂无5分钟K线数据
      </div>
    );
  }

  return (
    <div className="bg-card rounded-xl border border-border overflow-hidden">
      <div className="px-4 py-2.5 bg-gradient-to-r from-orange-500/8 to-red-500/8 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-foreground">🕯 5min K线 · Delta动量</span>
          <span className="text-[10px] text-muted-foreground px-1.5 py-0.5 rounded bg-muted">
            {data.count}根
          </span>
        </div>
        <span className="text-[10px] text-muted-foreground">30s刷新</span>
      </div>
      <div className="px-4 py-3">
        <CandleDeltaSVG candles={data.candles} />
      </div>
    </div>
  );
}

// ==================== SVG Candlestick + Delta Chart ====================

function CandleDeltaSVG({ candles }: { candles: KlineDeltaCandle[] }) {
  const W = 800;
  const CANDLE_H = 180;
  const DELTA_H = 70;
  const GAP = 15;
  const TOTAL_H = CANDLE_H + GAP + DELTA_H + 30;
  const PAD = { l: 55, r: 15, t: 10, b: 25 };
  const chartW = W - PAD.l - PAD.r;
  const n = candles.length;
  const candleW = Math.max(2, (chartW / n) * 0.7);
  const wickW = 1;

  // Price range
  const allHighs = candles.map((c) => c.high);
  const allLows = candles.map((c) => c.low);
  const minP = Math.min(...allLows);
  const maxP = Math.max(...allHighs);
  const rangeP = maxP - minP || 1;
  const padP = rangeP * 0.05;

  // Delta range
  const deltas = candles.map((c) => c.delta);
  const maxAbsDelta = Math.max(...deltas.map(Math.abs), 1);

  // Compute delta std for extreme detection
  const avgDelta = deltas.reduce((a, b) => a + b, 0) / n;
  const stdDelta = Math.sqrt(deltas.reduce((a, b) => a + (b - avgDelta) ** 2, 0) / n) || 1;

  // X position
  const xPos = (i: number) => PAD.l + ((i + 0.5) / n) * chartW;

  // Y price
  const yPrice = (p: number) =>
    PAD.t + CANDLE_H - ((p - minP + padP) / (rangeP + padP * 2)) * CANDLE_H;

  // Y delta (centered)
  const deltaTop = PAD.t + CANDLE_H + GAP;
  const deltaMid = deltaTop + DELTA_H / 2;
  const yDelta = (d: number) => (Math.abs(d) / maxAbsDelta) * (DELTA_H / 2 - 2);

  // Price labels
  const priceLabels = useMemo(() => {
    const steps = 4;
    const arr = [];
    for (let i = 0; i <= steps; i++) {
      const p = minP - padP + ((rangeP + padP * 2) / steps) * i;
      arr.push({ price: p, y: yPrice(p) });
    }
    return arr;
  }, [minP, rangeP, padP]);

  // Time labels — detect daily kline fallback (all times are 00:00) and show dates instead
  const timeLabels = useMemo(() => {
    const labels: { i: number; label: string }[] = [];
    const step = Math.max(1, Math.floor(n / 8));

    // Check if all candle times are "00:00" (daily kline fallback)
    const allZeroTime = candles.every((c) => {
      const m = c.time.match(/(\d{2}:\d{2})/);
      return !m || m[1] === "00:00";
    });

    for (let i = 0; i < n; i += step) {
      const t = candles[i].time;
      if (allZeroTime) {
        // Daily kline: show MM/DD from date portion
        const dateMatch = t.match(/(\d{4})-(\d{2})-(\d{2})/);
        if (dateMatch) labels.push({ i, label: `${dateMatch[2]}/${dateMatch[3]}` });
      } else {
        // 5min kline: show HH:MM
        const match = t.match(/(\d{2}:\d{2})/);
        if (match) labels.push({ i, label: match[1] });
      }
    }
    return labels;
  }, [candles, n]);

  // Last candle stats
  const last = candles[n - 1];
  const prev = n >= 2 ? candles[n - 2] : last;
  const lastIsUp = last.close >= last.open;

  // Cumulative delta trend
  const lastCumDelta = last.cum_delta;
  const cumDeltaPositive = lastCumDelta >= 0;

  return (
    <div>
      {/* Stats row */}
      <div className="flex items-center gap-4 mb-2 text-xs">
        <span className={`font-bold tabular-nums ${lastIsUp ? "text-red-500" : "text-green-500"}`}>
          收 {last.close.toFixed(3)}
        </span>
        <span className="text-muted-foreground">
          高 <b className="text-red-400">{last.high.toFixed(3)}</b>
        </span>
        <span className="text-muted-foreground">
          低 <b className="text-green-400">{last.low.toFixed(3)}</b>
        </span>
        <span className={`px-1.5 py-0.5 rounded ${cumDeltaPositive ? "bg-red-500/10 text-red-500" : "bg-green-500/10 text-green-500"}`}>
          累计Delta: {cumDeltaPositive ? "+" : ""}{lastCumDelta.toFixed(0)}
        </span>
      </div>

      <svg viewBox={`0 0 ${W} ${TOTAL_H}`} className="w-full" style={{ maxHeight: 330 }}>
        {/* Price grid */}
        {priceLabels.map((pl, i) => (
          <g key={`pg-${i}`}>
            <line x1={PAD.l} y1={pl.y} x2={W - PAD.r} y2={pl.y}
              stroke="var(--border)" strokeWidth="0.5" strokeDasharray="3,3" />
            <text x={PAD.l - 5} y={pl.y + 3} textAnchor="end"
              fill="var(--muted-foreground)" fontSize="9" fontFamily="monospace">
              {pl.price.toFixed(3)}
            </text>
          </g>
        ))}

        {/* Delta zero line */}
        <line x1={PAD.l} y1={deltaMid} x2={W - PAD.r} y2={deltaMid}
          stroke="var(--border)" strokeWidth="0.5" />
        <text x={PAD.l - 5} y={deltaMid + 3} textAnchor="end"
          fill="var(--muted-foreground)" fontSize="8" fontFamily="monospace">0</text>

        {/* Separator */}
        <line x1={PAD.l} y1={deltaTop - 5} x2={W - PAD.r} y2={deltaTop - 5}
          stroke="var(--border)" strokeWidth="0.5" />

        {/* Candlesticks + Delta bars */}
        {candles.map((c, i) => {
          const x = xPos(i);
          const isUp = c.close >= c.open;
          const bodyTop = yPrice(Math.max(c.open, c.close));
          const bodyBot = yPrice(Math.min(c.open, c.close));
          const bodyH = Math.max(1, bodyBot - bodyTop);
          const wickTop = yPrice(c.high);
          const wickBot = yPrice(c.low);

          const fillColor = isUp ? "rgb(239,68,68)" : "rgb(34,197,94)";

          // Delta bar
          const d = c.delta;
          const dH = yDelta(d);
          const isExtreme = Math.abs(d - avgDelta) > 2 * stdDelta;
          const deltaColor = d >= 0
            ? (isExtreme ? "rgb(239,68,68)" : "rgba(239,68,68,0.5)")
            : (isExtreme ? "rgb(34,197,94)" : "rgba(34,197,94,0.5)");

          return (
            <g key={`c-${i}`}>
              {/* Wick */}
              <line x1={x} y1={wickTop} x2={x} y2={wickBot}
                stroke={fillColor} strokeWidth={wickW} />
              {/* Body */}
              <rect
                x={x - candleW / 2} y={bodyTop}
                width={candleW} height={bodyH}
                fill={isUp ? "none" : fillColor}
                stroke={fillColor} strokeWidth="0.8"
                rx="0.5"
              />
              {/* Delta bar */}
              {d >= 0 ? (
                <rect
                  x={x - candleW / 2} y={deltaMid - dH}
                  width={candleW} height={dH}
                  fill={deltaColor} rx="0.5"
                />
              ) : (
                <rect
                  x={x - candleW / 2} y={deltaMid}
                  width={candleW} height={dH}
                  fill={deltaColor} rx="0.5"
                />
              )}
              {/* Extreme marker */}
              {isExtreme && (
                <circle cx={x} cy={d >= 0 ? deltaMid - dH - 4 : deltaMid + dH + 4}
                  r="2" fill={deltaColor} />
              )}
            </g>
          );
        })}

        {/* Time labels */}
        {timeLabels.map((tl) => (
          <text key={tl.i} x={xPos(tl.i)} y={TOTAL_H - 5}
            textAnchor="middle" fill="var(--muted-foreground)" fontSize="9" fontFamily="monospace">
            {tl.label}
          </text>
        ))}

        {/* Legend */}
        <g transform={`translate(${PAD.l + 5}, ${deltaTop + DELTA_H + 5})`}>
          <rect x="0" y="-5" width="6" height="5" fill="rgb(239,68,68)" opacity="0.5" rx="0.5" />
          <text x="9" y="0" fontSize="8" fill="var(--muted-foreground)">买方Delta</text>
          <rect x="65" y="-5" width="6" height="5" fill="rgb(34,197,94)" opacity="0.5" rx="0.5" />
          <text x="74" y="0" fontSize="8" fill="var(--muted-foreground)">卖方Delta</text>
          <circle cx="140" cy="-2" r="2" fill="rgb(239,68,68)" />
          <text x="145" y="0" fontSize="8" fill="var(--muted-foreground)">极端值(2σ)</text>
        </g>
      </svg>
    </div>
  );
}
