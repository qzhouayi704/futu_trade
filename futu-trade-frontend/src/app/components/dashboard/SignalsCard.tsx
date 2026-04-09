// 交易信号提醒组件

"use client";

import { Card } from "@/components/common";
import Link from "next/link";

interface TradeSignal {
  id: number;
  stock_code: string;
  stock_name: string;
  signal_type: string;
  signal_price: number;
  target_price?: number;
  stop_loss_price?: number;
  created_at: string;
  is_executed: boolean;
}

interface SignalsCardProps {
  signals: TradeSignal[];
  loading?: boolean;
}

export function SignalsCard({ signals, loading = false }: SignalsCardProps) {
  return (
    <Card>
      <div className="p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <svg className="w-5 h-5 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
            </svg>
            交易信号提醒
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
        ) : signals.length === 0 ? (
          <div className="text-center py-8 text-gray-500">暂无信号</div>
        ) : (
          <div className="space-y-3">
            {signals.slice(0, 5).map((signal) => (
              <div
                key={signal.id}
                className="p-3 rounded-lg border border-gray-200 hover:border-blue-300 hover:bg-blue-50 transition-colors"
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span
                      className={`px-2 py-1 rounded text-xs font-medium ${
                        signal.signal_type === "BUY"
                          ? "bg-red-100 text-red-700"
                          : "bg-green-100 text-green-700"
                      }`}
                    >
                      {signal.signal_type === "BUY" ? "买入" : "卖出"}
                    </span>
                    <span className="font-medium text-gray-900">{signal.stock_name}</span>
                    <span className="text-xs text-gray-500">{signal.stock_code}</span>
                  </div>
                  {signal.is_executed && (
                    <span className="px-2 py-1 rounded text-xs font-medium bg-gray-100 text-gray-600">
                      已执行
                    </span>
                  )}
                </div>

                <div className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-4 text-gray-600">
                    <span>
                      信号价: <span className="font-medium text-gray-900">{signal.signal_price.toFixed(2)}</span>
                    </span>
                    {signal.target_price && (
                      <span>
                        目标: <span className="font-medium text-red-600">{signal.target_price.toFixed(2)}</span>
                      </span>
                    )}
                    {signal.stop_loss_price && (
                      <span>
                        止损: <span className="font-medium text-green-600">{signal.stop_loss_price.toFixed(2)}</span>
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-gray-500">
                    {new Date(signal.created_at).toLocaleTimeString("zh-CN", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
