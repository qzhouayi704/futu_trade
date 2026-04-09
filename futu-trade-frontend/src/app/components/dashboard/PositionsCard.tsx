// 持仓摘要组件

"use client";

import { Card } from "@/components/common";
import Link from "next/link";

interface Position {
  stock_code: string;
  stock_name: string;
  quantity: number;
  avg_price: number;
  current_price: number;
  market_value: number;
  profit_loss: number;
  profit_loss_pct: number;
}

interface PositionsCardProps {
  positions: Position[];
  loading?: boolean;
}

export function PositionsCard({ positions, loading = false }: PositionsCardProps) {
  // 计算统计数据
  const totalMarketValue = positions.reduce((sum, pos) => sum + (pos.market_value ?? 0), 0);
  const totalProfitLoss = positions.reduce((sum, pos) => sum + (pos.profit_loss ?? 0), 0);
  const totalProfitLossPct = totalMarketValue > 0 ? (totalProfitLoss / (totalMarketValue - totalProfitLoss)) * 100 : 0;

  return (
    <Card>
      <div className="p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <svg className="w-5 h-5 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
            </svg>
            持仓摘要
          </h3>
          <Link
            href="/trading"
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
        ) : (
          <>
            {/* 统计卡片 */}
            <div className="grid grid-cols-3 gap-4 mb-4">
              <div className="p-3 rounded-lg bg-blue-50 border border-blue-200">
                <div className="text-xs text-blue-600 mb-1">持仓数量</div>
                <div className="text-xl font-bold text-blue-700">{positions.length}</div>
              </div>
              <div className="p-3 rounded-lg bg-purple-50 border border-purple-200">
                <div className="text-xs text-purple-600 mb-1">总市值</div>
                <div className="text-xl font-bold text-purple-700">
                  {totalMarketValue.toFixed(0)}
                </div>
              </div>
              <div className={`p-3 rounded-lg ${totalProfitLoss >= 0 ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200'} border`}>
                <div className={`text-xs ${totalProfitLoss >= 0 ? 'text-red-600' : 'text-green-600'} mb-1`}>
                  总盈亏
                </div>
                <div className={`text-xl font-bold ${totalProfitLoss >= 0 ? 'text-red-700' : 'text-green-700'}`}>
                  {totalProfitLoss >= 0 ? '+' : ''}{totalProfitLoss.toFixed(0)}
                  <span className="text-sm ml-1">
                    ({totalProfitLossPct >= 0 ? '+' : ''}{totalProfitLossPct.toFixed(2)}%)
                  </span>
                </div>
              </div>
            </div>

            {/* 持仓列表 */}
            {positions.length === 0 ? (
              <div className="text-center py-8 text-gray-500">暂无持仓</div>
            ) : (
              <div className="space-y-2">
                {positions.slice(0, 3).map((position) => (
                  <div
                    key={position.stock_code}
                    className="p-3 rounded-lg border border-gray-200 hover:border-blue-300 hover:bg-blue-50 transition-colors"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div>
                        <span className="font-medium text-gray-900">{position.stock_name}</span>
                        <span className="text-xs text-gray-500 ml-2">{position.stock_code}</span>
                      </div>
                      <span
                        className={`text-sm font-semibold ${
                          (position.profit_loss ?? 0) >= 0 ? "text-red-600" : "text-green-600"
                        }`}
                      >
                        {(position.profit_loss ?? 0) >= 0 ? "+" : ""}
                        {(position.profit_loss_pct ?? 0).toFixed(2)}%
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-xs text-gray-600">
                      <span>持仓: {position.quantity ?? 0}</span>
                      <span>成本: {(position.avg_price ?? 0).toFixed(2)}</span>
                      <span>现价: {(position.current_price ?? 0).toFixed(2)}</span>
                      <span>市值: {(position.market_value ?? 0).toFixed(0)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </Card>
  );
}
