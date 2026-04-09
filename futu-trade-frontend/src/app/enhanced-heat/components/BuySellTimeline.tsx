// 买卖力量比分时走势图
// Y 轴 = buy/sell 力量比，范围 0~5，1.0 为均衡基准线
// 数据按 5 分钟窗口聚合，避免小样本噪声

import type { DimensionSignal, BuySellTimelinePoint } from "@/types/enhanced-heat";

function formatAmount(v: number): string {
  if (Math.abs(v) >= 10000) return `${(v / 10000).toFixed(1)}万`;
  return v.toLocaleString();
}

/** 计算 Y 轴上限，下限固定为 0 */
function calcYMax(timeline: BuySellTimelinePoint[]): number {
  let max = 1;
  for (const p of timeline) {
    if (p.ratio > max) max = p.ratio;
  }
  return Math.max(max * 1.15, 1.8); // 至少到 1.8，让 1.0 基准线不贴底
}

/** 生成 Y 轴刻度 */
function calcYTicks(yMax: number): number[] {
  let step: number;
  if (yMax <= 2) step = 0.5;
  else if (yMax <= 4) step = 1.0;
  else step = 1.0;

  const ticks: number[] = [];
  for (let v = 0; v <= yMax + 0.01; v += step) {
    ticks.push(Math.round(v * 10) / 10);
  }
  if (!ticks.some((t) => Math.abs(t - 1) < 0.01)) ticks.push(1.0);
  return ticks.sort((a, b) => b - a);
}

export function BuySellTimeline({ dimensions }: { dimensions: DimensionSignal[] }) {
  const dim = dimensions.find((d) => d.name === "主动买卖");
  if (!dim) return null;

  const rawDetails = dim.details as unknown as { timeline?: BuySellTimelinePoint[] };
  const timeline = rawDetails.timeline ?? [];
  if (timeline.length < 2) return null;

  const W = 600;
  const H = 260;
  const PAD_L = 44;
  const PAD_R = 12;
  const PAD_T = 16;
  const PAD_B = 28;
  const chartW = W - PAD_L - PAD_R;
  const chartH = H - PAD_T - PAD_B;

  const yMax = calcYMax(timeline);

  const toX = (i: number) => PAD_L + (i / (timeline.length - 1)) * chartW;
  const toY = (ratio: number) => {
    const clamped = Math.max(0, Math.min(yMax, ratio));
    return PAD_T + ((yMax - clamped) / yMax) * chartH;
  };
  const oneY = toY(1.0);

  // 平滑贝塞尔曲线
  const pts = timeline.map((p, i) => ({ x: toX(i), y: toY(p.ratio) }));
  let smoothPath = `M${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)}`;
  for (let i = 1; i < pts.length; i++) {
    const cpx = (pts[i - 1].x + pts[i].x) / 2;
    smoothPath += ` C${cpx.toFixed(1)},${pts[i - 1].y.toFixed(1)} ${cpx.toFixed(1)},${pts[i].y.toFixed(1)} ${pts[i].x.toFixed(1)},${pts[i].y.toFixed(1)}`;
  }

  const firstX = pts[0].x.toFixed(1);
  const lastX = pts[pts.length - 1].x.toFixed(1);
  const areaPath = `${smoothPath} L${lastX},${oneY.toFixed(1)} L${firstX},${oneY.toFixed(1)} Z`;

  const yTicks = calcYTicks(yMax);

  // X 轴标签：每个窗口都显示（5 分钟窗口通常只有 3~5 个）
  const labelIndices = timeline.map((_, i) => i);

  return (
    <div className="mt-4 bg-gray-50 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-gray-600 font-medium">买卖力量比走势（5分钟）</span>
        <span className="text-[10px] text-gray-400">
          1.0 = 均衡 · &gt;1 多方强 · &lt;1 空方强
        </span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        preserveAspectRatio="xMidYMid meet"
        style={{ height: 260 }}
      >
        <defs>
          <clipPath id="clip-bull-area">
            <rect x={PAD_L} y={PAD_T} width={chartW} height={oneY - PAD_T} />
          </clipPath>
          <clipPath id="clip-bear-area">
            <rect x={PAD_L} y={oneY} width={chartW} height={PAD_T + chartH - oneY} />
          </clipPath>
        </defs>

        {/* Y 轴刻度线 + 标签 */}
        {yTicks.map((v) => {
          const y = toY(v);
          const isOne = Math.abs(v - 1) < 0.01;
          return (
            <g key={v}>
              <line
                x1={PAD_L} y1={y} x2={W - PAD_R} y2={y}
                stroke={isOne ? "#94a3b8" : "#e5e7eb"}
                strokeWidth={isOne ? 1.2 : 0.5}
                strokeDasharray={isOne ? "6,4" : "none"}
              />
              <text
                x={PAD_L - 6} y={y + 4}
                textAnchor="end" fontSize={11}
                fill={v > 1 ? "#dc2626" : v < 1 ? "#16a34a" : "#64748b"}
                fontWeight={isOne ? "600" : "400"}
              >
                {v.toFixed(1)}
              </text>
            </g>
          );
        })}

        {/* 红色面积（多方） */}
        <path d={areaPath} fill="rgba(239,68,68,0.18)" clipPath="url(#clip-bull-area)" />
        {/* 绿色面积（空方） */}
        <path d={areaPath} fill="rgba(34,197,94,0.18)" clipPath="url(#clip-bear-area)" />

        {/* 曲线 */}
        <path d={smoothPath} fill="none" stroke="#475569" strokeWidth={2.5} />

        {/* 数据点 + tooltip 标签 */}
        {timeline.map((p, i) => (
          <g key={i}>
            <circle
              cx={toX(i)} cy={toY(p.ratio)} r={4}
              fill={p.ratio >= 1 ? "#dc2626" : "#16a34a"}
              stroke="white" strokeWidth={2}
            />
            {/* 数据点上方显示力量比数值 */}
            <text
              x={toX(i)} y={toY(p.ratio) - 8}
              textAnchor="middle" fontSize={10}
              fill={p.ratio >= 1 ? "#dc2626" : "#16a34a"}
              fontWeight="500"
            >
              {p.ratio.toFixed(2)}
            </text>
          </g>
        ))}

        {/* X 轴时间标签 */}
        {labelIndices.map((idx) => (
          <text
            key={idx}
            x={toX(idx)} y={H - 6}
            textAnchor="middle" fontSize={11} fill="#9ca3af"
          >
            {timeline[idx].time}
          </text>
        ))}
      </svg>

      {/* 底部窗口详情 */}
      <div className="flex gap-2 mt-2 overflow-x-auto">
        {timeline.map((p, i) => (
          <div key={i} className="flex-shrink-0 text-[10px] text-gray-500 text-center">
            <div className="text-gray-400">{p.time}</div>
            <div>
              <span className="text-red-500">{formatAmount(p.buy_turnover)}</span>
              {" / "}
              <span className="text-green-500">{formatAmount(p.sell_turnover)}</span>
            </div>
            <div className="text-gray-400">{p.trade_count}笔</div>
          </div>
        ))}
      </div>
    </div>
  );
}
