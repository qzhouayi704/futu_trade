// 9维度综合分析条形图

import type { DimensionSignal, SignalType, CombinedAnalysisData } from "@/types/enhanced-heat";

const SIGNAL_STYLES: Record<SignalType, { text: string }> = {
  bullish: { text: "text-red-700" },
  slightly_bullish: { text: "text-red-600" },
  neutral: { text: "text-gray-600" },
  slightly_bearish: { text: "text-green-600" },
  bearish: { text: "text-green-700" },
};

function DimensionBar({ dim, group }: { dim: DimensionSignal; group?: string }) {
  const style = SIGNAL_STYLES[dim.signal] || SIGNAL_STYLES.neutral;
  const pct = Math.abs(dim.score);
  const isPositive = dim.score >= 0;
  const barColor = isPositive ? "bg-red-400" : "bg-green-400";

  return (
    <div className="flex items-center gap-2 py-1">
      {group && (
        <span className="w-6 text-[10px] text-gray-400 shrink-0">{group}</span>
      )}
      <span className="w-16 text-xs text-gray-600 shrink-0">{dim.name}</span>
      <div className="flex-1 h-3 bg-gray-100 rounded-full overflow-hidden relative">
        <div className="absolute left-1/2 top-0 w-px h-full bg-gray-300 z-10" />
        {isPositive ? (
          <div
            className={`absolute left-1/2 top-0 h-full ${barColor} rounded-r-full transition-all duration-300`}
            style={{ width: `${pct / 2}%` }}
          />
        ) : (
          <div
            className={`absolute top-0 h-full ${barColor} rounded-l-full transition-all duration-300`}
            style={{ width: `${pct / 2}%`, right: "50%" }}
          />
        )}
      </div>
      <span className={`w-10 text-xs font-mono text-right shrink-0 ${style.text}`}>
        {dim.score > 0 ? "+" : ""}{dim.score.toFixed(0)}
      </span>
      <span className="text-xs text-gray-500 shrink-0">{dim.description}</span>
    </div>
  );
}

export function AllDimensionsChart({ data }: { data: CombinedAnalysisData }) {
  return (
    <div className="mt-4 bg-gray-50 rounded-lg p-3">
      <div className="text-xs text-gray-500 mb-2 font-medium">9维度综合分析</div>
      <div className="space-y-0.5">
        {data.order_book_dimensions.map((dim) => (
          <DimensionBar key={`ob-${dim.name}`} dim={dim} group="挂" />
        ))}
        <div className="border-t border-dashed border-gray-200 my-1" />
        {data.ticker_dimensions.map((dim) => (
          <DimensionBar key={`tk-${dim.name}`} dim={dim} group="成" />
        ))}
      </div>
    </div>
  );
}
