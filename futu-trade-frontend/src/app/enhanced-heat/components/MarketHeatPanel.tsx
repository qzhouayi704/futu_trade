// 市场热度监控面板

"use client";

import { useEffect, useState, useCallback } from "react";
import type { MarketHeatData } from "@/types/enhanced-heat";
import { getMarketHeat } from "@/lib/api/enhanced-heat";

/** 热度颜色映射 */
function getHeatColor(heat: number): string {
  if (heat >= 80) return "text-red-600";
  if (heat >= 60) return "text-orange-500";
  if (heat >= 40) return "text-yellow-500";
  if (heat >= 20) return "text-blue-500";
  return "text-gray-500";
}

function getHeatBgColor(heat: number): string {
  if (heat >= 80) return "bg-red-500";
  if (heat >= 60) return "bg-orange-500";
  if (heat >= 40) return "bg-yellow-500";
  if (heat >= 20) return "bg-blue-500";
  return "bg-gray-400";
}

/** 报价覆盖率样式映射（导出供测试使用） */
export function getCoverageStyle(coverage: number): {
  color: string;
  bgColor: string;
  label: string;
} {
  if (coverage >= 0.8) {
    return {
      color: "text-green-700",
      bgColor: "bg-green-50",
      label: "报价数据正常",
    };
  }
  if (coverage >= 0.5) {
    return {
      color: "text-yellow-700",
      bgColor: "bg-yellow-50",
      label: "数据可能不完整",
    };
  }
  return {
    color: "text-red-700",
    bgColor: "bg-red-50",
    label: "报价数据不足",
  };
}

function getSentimentBadge(sentiment: string): string {
  const map: Record<string, string> = {
    极度活跃: "bg-red-100 text-red-800",
    活跃: "bg-orange-100 text-orange-800",
    正常: "bg-green-100 text-green-800",
    冷淡: "bg-blue-100 text-blue-800",
    极度冷淡: "bg-gray-100 text-gray-800",
  };
  return map[sentiment] || "bg-gray-100 text-gray-800";
}

/** 报价覆盖率展示条 */
function QuoteCoverageBar({ coverage }: { coverage: number }) {
  const style = getCoverageStyle(coverage);
  const pct = Math.round(coverage * 100);

  return (
    <div className={`${style.bgColor} rounded-lg p-3 mb-4`}>
      <div className="flex items-center justify-between mb-1">
        <span className={`text-sm ${style.color}`}>报价覆盖率</span>
        <div className="flex items-center gap-2">
          <span className={`text-sm font-medium ${style.color}`}>
            {style.label}
          </span>
          <span className={`text-lg font-bold ${style.color}`}>{pct}%</span>
        </div>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2">
        <div
          className={`h-2 rounded-full transition-all duration-500 ${
            coverage >= 0.8
              ? "bg-green-500"
              : coverage >= 0.5
                ? "bg-yellow-500"
                : "bg-red-500"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export function MarketHeatPanel() {
  const [data, setData] = useState<MarketHeatData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await getMarketHeat();
      if (res.success && res.data) {
        setData(res.data);
        setError(null);
      }
    } catch (e) {
      setError("获取市场热度失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, 60000);
    return () => clearInterval(timer);
  }, [fetchData]);

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow p-6 animate-pulse">
        <div className="h-6 bg-gray-200 rounded w-1/3 mb-4" />
        <div className="h-24 bg-gray-200 rounded" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <p className="text-gray-500">{error || "暂无数据"}</p>
      </div>
    );
  }

  const heat = data.market_heat;
  const positionPct = Math.round(data.recommended_position_ratio * 100);

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
        <svg className="w-5 h-5 text-orange-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
        市场热度
      </h3>

      {/* 热度仪表 */}
      <div className="flex items-center gap-6 mb-4">
        <div className="text-center">
          <div className={`text-4xl font-bold ${getHeatColor(heat)}`}>
            {heat.toFixed(1)}
          </div>
          <span className={`inline-block mt-1 px-2 py-0.5 rounded-full text-xs font-medium ${getSentimentBadge(data.sentiment)}`}>
            {data.sentiment}
          </span>
        </div>

        {/* 热度条 */}
        <div className="flex-1">
          <div className="w-full bg-gray-200 rounded-full h-3">
            <div
              className={`h-3 rounded-full transition-all duration-500 ${getHeatBgColor(heat)}`}
              style={{ width: `${Math.min(heat, 100)}%` }}
            />
          </div>
          <div className="flex justify-between text-xs text-gray-400 mt-1">
            <span>0</span>
            <span>50</span>
            <span>100</span>
          </div>
        </div>
      </div>

      {/* 推荐仓位 */}
      <div className="bg-blue-50 rounded-lg p-3 mb-4">
        <div className="flex items-center justify-between">
          <span className="text-sm text-blue-700">推荐仓位</span>
          <span className="text-lg font-bold text-blue-800">{positionPct}%</span>
        </div>
        <div className="w-full bg-blue-200 rounded-full h-2 mt-2">
          <div
            className="h-2 rounded-full bg-blue-600 transition-all duration-500"
            style={{ width: `${positionPct}%` }}
          />
        </div>
      </div>

      {/* 报价覆盖率 */}
      {data.quote_coverage != null && (
        <QuoteCoverageBar coverage={data.quote_coverage} />
      )}

      {/* 热门板块 */}
      {data.hot_plates.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-gray-600 mb-2">热门板块</h4>
          <div className="space-y-2">
            {data.hot_plates.map((plate, idx) => (
              <div
                key={plate.plate_code}
                className="border border-gray-100 rounded-lg p-3 hover:bg-gray-50 transition-colors"
                role="listitem"
                aria-label={`第${idx + 1}名 ${plate.plate_name}`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-gray-800">
                    <span className="text-orange-500 font-bold mr-1">#{idx + 1}</span>
                    {plate.plate_name}
                  </span>
                  <span
                    className={`text-sm font-semibold ${plate.avg_change_pct >= 0 ? "text-red-600" : "text-green-600"}`}
                  >
                    {plate.avg_change_pct >= 0 ? "+" : ""}
                    {plate.avg_change_pct.toFixed(2)}%
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs text-gray-500">
                  <span>
                    涨跌比 {(plate.up_ratio * 100).toFixed(0)}%
                  </span>
                  <span>{plate.stock_count}只</span>
                  <span>热度 {plate.heat_score.toFixed(1)}</span>
                </div>
                {plate.leading_stock_name && (
                  <div className="text-xs text-orange-600 mt-1">
                    领涨：{plate.leading_stock_name}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
