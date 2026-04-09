// 活跃个股摘要卡片 - Dashboard 展示换手率最高的前 5 只股票

"use client";

import { Card } from "@/components/common";
import Link from "next/link";
import type { HighTurnoverStock } from "@/types/stock";

interface HighTurnoverCardProps {
  stocks: HighTurnoverStock[];
  loading?: boolean;
}

/**
 * 根据换手率返回渐变背景色
 * 换手率越高颜色越深（橙色系）
 */
function getTurnoverColor(rate: number): string {
  if (rate >= 20) return "bg-orange-200 text-orange-900";
  if (rate >= 10) return "bg-orange-100 text-orange-800";
  if (rate >= 5) return "bg-amber-100 text-amber-800";
  return "bg-yellow-50 text-yellow-800";
}

export function HighTurnoverCard({ stocks, loading = false }: HighTurnoverCardProps) {
  return (
    <Card>
      <div className="p-6">
        {/* 标题栏 */}
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <svg className="w-5 h-5 text-orange-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            活跃个股
          </h3>
          <Link
            href="/high-turnover"
            className="text-sm text-blue-600 hover:text-blue-700 flex items-center gap-1"
          >
            查看更多
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </Link>
        </div>

        {/* 加载状态 */}
        {loading ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="animate-pulse flex items-center gap-3">
                <div className="w-6 h-6 bg-gray-200 rounded-full" />
                <div className="flex-1 space-y-1">
                  <div className="h-4 bg-gray-200 rounded w-24" />
                  <div className="h-3 bg-gray-100 rounded w-16" />
                </div>
                <div className="h-4 bg-gray-200 rounded w-14" />
                <div className="h-4 bg-gray-200 rounded w-14" />
              </div>
            ))}
          </div>
        ) : stocks.length === 0 ? (
          /* 空数据状态 */
          <div className="text-center py-8 text-gray-500">暂无活跃个股数据</div>
        ) : (
          /* 股票表格 */
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-2 px-2 font-medium text-gray-600">排名</th>
                  <th className="text-left py-2 px-2 font-medium text-gray-600">股票</th>
                  <th className="text-right py-2 px-2 font-medium text-gray-600">换手率</th>
                  <th className="text-right py-2 px-2 font-medium text-gray-600">涨跌幅</th>
                </tr>
              </thead>
              <tbody>
                {stocks.slice(0, 5).map((stock) => (
                  <tr
                    key={stock.code}
                    className="border-b border-gray-100 hover:bg-gray-50 transition-colors"
                  >
                    {/* 排名 */}
                    <td className="py-3 px-2">
                      <span className="flex items-center justify-center w-6 h-6 rounded-full bg-gradient-to-br from-orange-500 to-amber-500 text-white text-xs font-bold">
                        {stock.rank}
                      </span>
                    </td>
                    {/* 股票名称和代码 */}
                    <td className="py-3 px-2">
                      <div>
                        <div className="font-medium text-gray-900">{stock.name}</div>
                        <div className="text-xs text-gray-500">{stock.code}</div>
                      </div>
                    </td>
                    {/* 换手率（高亮） */}
                    <td className="py-3 px-2 text-right">
                      <span
                        className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${getTurnoverColor(stock.turnover_rate)}`}
                      >
                        {stock.turnover_rate.toFixed(2)}%
                      </span>
                    </td>
                    {/* 涨跌幅（红涨绿跌） */}
                    <td className="py-3 px-2 text-right">
                      <span
                        className={`font-medium ${
                          stock.change_rate >= 0 ? "text-red-600" : "text-green-600"
                        }`}
                      >
                        {stock.change_rate >= 0 ? "+" : ""}
                        {stock.change_rate.toFixed(2)}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Card>
  );
}
