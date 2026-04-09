// 热门股票排行组件

"use client";

import { Card } from "@/components/common";
import Link from "next/link";

interface HotStock {
  stock_code: string;
  stock_name: string;
  market: string;
  current_price: number;
  change_pct: number;
  heat_score: number;
  turnover_rate?: number;
  volume?: number;
}

interface HotStocksCardProps {
  stocks: HotStock[];
  loading?: boolean;
}

export function HotStocksCard({ stocks, loading = false }: HotStocksCardProps) {
  return (
    <Card>
      <div className="p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <svg className="w-5 h-5 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
            热门股票排行
          </h3>
          <Link
            href="/stock-pool-monitor"
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
        ) : stocks.length === 0 ? (
          <div className="text-center py-8 text-gray-500">暂无数据</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-2 px-2 font-medium text-gray-600">排名</th>
                  <th className="text-left py-2 px-2 font-medium text-gray-600">股票</th>
                  <th className="text-right py-2 px-2 font-medium text-gray-600">价格</th>
                  <th className="text-right py-2 px-2 font-medium text-gray-600">涨跌幅</th>
                  <th className="text-right py-2 px-2 font-medium text-gray-600">热度分</th>
                </tr>
              </thead>
              <tbody>
                {stocks.slice(0, 5).map((stock, index) => (
                  <tr
                    key={stock.stock_code}
                    className="border-b border-gray-100 hover:bg-gray-50 transition-colors"
                  >
                    <td className="py-3 px-2">
                      <span className="flex items-center justify-center w-6 h-6 rounded-full bg-gradient-to-br from-red-500 to-orange-500 text-white text-xs font-bold">
                        {index + 1}
                      </span>
                    </td>
                    <td className="py-3 px-2">
                      <div>
                        <div className="font-medium text-gray-900">{stock.stock_name}</div>
                        <div className="text-xs text-gray-500">
                          {stock.stock_code} · {stock.market}
                        </div>
                      </div>
                    </td>
                    <td className="py-3 px-2 text-right font-medium text-gray-900">
                      {stock.current_price?.toFixed(2) ?? '-'}
                    </td>
                    <td className="py-3 px-2 text-right">
                      <span
                        className={`font-medium ${
                          (stock.change_pct ?? 0) >= 0 ? "text-red-600" : "text-green-600"
                        }`}
                      >
                        {stock.change_pct !== undefined && stock.change_pct !== null
                          ? `${stock.change_pct >= 0 ? "+" : ""}${stock.change_pct.toFixed(2)}%`
                          : '-'}
                      </span>
                    </td>
                    <td className="py-3 px-2 text-right">
                      <span className="font-semibold text-orange-600">
                        {stock.heat_score?.toFixed(1) ?? '-'}
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
