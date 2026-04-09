// 板块热度排行组件

"use client";

import { Card } from "@/components/common";
import Link from "next/link";
import type { PlateStrength } from "@/types/stock";

interface PlateHeatCardProps {
  plates: PlateStrength[];
  loading?: boolean;
}

export function PlateHeatCard({ plates, loading = false }: PlateHeatCardProps) {
  return (
    <Card>
      <div className="p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <svg className="w-5 h-5 text-orange-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z" />
            </svg>
            板块热度排行
          </h3>
          <Link
            href="/plates"
            className="text-sm text-blue-600 hover:text-blue-700 flex items-center gap-1"
          >
            查看全部
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </Link>
        </div>

        {loading ? (
          <div className="text-center py-8 text-gray-500">加载中...</div>
        ) : plates.length === 0 ? (
          <div className="text-center py-8 text-gray-500">暂无数据</div>
        ) : (
          <div className="space-y-3">
            {plates.slice(0, 5).map((plate, index) => (
              <Link
                key={plate.plate_code}
                href={`/plate/${plate.plate_code}`}
                className="block p-3 rounded-lg border border-gray-200 hover:border-blue-300 hover:bg-blue-50 transition-colors"
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="flex items-center justify-center w-6 h-6 rounded-full bg-gradient-to-br from-orange-500 to-red-500 text-white text-xs font-bold">
                      {index + 1}
                    </span>
                    <span className="font-medium text-gray-900">{plate.plate_name}</span>
                    <span className="text-xs text-gray-500">{plate.market}</span>
                  </div>
                  <span className="text-sm font-semibold text-orange-600">
                    {plate.strength_score.toFixed(1)}
                  </span>
                </div>

                {/* 强势分进度条 */}
                <div className="mb-2">
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className="bg-gradient-to-r from-orange-500 to-red-500 h-2 rounded-full transition-all"
                      style={{ width: `${Math.min(plate.strength_score, 100)}%` }}
                    ></div>
                  </div>
                </div>

                <div className="flex items-center justify-between text-xs text-gray-600">
                  <span>上涨比例: {((plate.up_stock_ratio ?? 0) * 100).toFixed(1)}%</span>
                  <span className={(plate.avg_change_pct ?? 0) >= 0 ? "text-red-600" : "text-green-600"}>
                    平均涨幅: {(plate.avg_change_pct ?? 0) >= 0 ? "+" : ""}
                    {(plate.avg_change_pct ?? 0).toFixed(2)}%
                  </span>
                  <span>龙头: {plate.leader_count}/{plate.total_stocks ?? 0}</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
