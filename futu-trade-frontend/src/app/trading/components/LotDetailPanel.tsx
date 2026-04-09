// 分仓详情面板 - 展示某只股票的各仓位信息

"use client";

import { useState, useEffect } from "react";
import { Card } from "@/components/common";
import { tradeApi } from "@/lib/api";
import { formatPrice, formatPercent } from "@/lib/utils";
import type { PositionLot, TakeProfitTask } from "@/types";

interface LotDetailPanelProps {
  stockCode: string;
  currentPrice: number;
  onSetTakeProfit: () => void;
}

const STATUS_LABELS: Record<string, { text: string; color: string }> = {
  PENDING: { text: "等待触发", color: "text-yellow-600 bg-yellow-50" },
  TRIGGERED: { text: "已触发", color: "text-blue-600 bg-blue-50" },
  EXECUTED: { text: "已卖出", color: "text-green-600 bg-green-50" },
  FAILED: { text: "失败", color: "text-red-600 bg-red-50" },
  CANCELLED: { text: "已取消", color: "text-gray-600 bg-gray-50" },
};

export default function LotDetailPanel({
  stockCode,
  currentPrice,
  onSetTakeProfit,
}: LotDetailPanelProps) {
  const [lots, setLots] = useState<PositionLot[]>([]);
  const [task, setTask] = useState<TakeProfitTask | null>(null);
  const [loading, setLoading] = useState(false);

  const loadData = async () => {
    setLoading(true);
    try {
      const [lotsRes, taskRes] = await Promise.all([
        tradeApi.getPositionLots(stockCode),
        tradeApi.getTakeProfitDetail(stockCode),
      ]);

      if (lotsRes.success && lotsRes.data) {
        // 计算实时盈亏
        const lotsWithProfit = lotsRes.data.map((lot) => ({
          ...lot,
          current_profit_pct:
            lot.buy_price > 0
              ? ((currentPrice - lot.buy_price) / lot.buy_price) * 100
              : 0,
        }));
        setLots(lotsWithProfit);
      }

      if (taskRes.success && taskRes.data) {
        setTask(taskRes.data);
      }
    } catch (err) {
      console.error("加载分仓数据失败:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (stockCode) loadData();
  }, [stockCode, currentPrice]);

  const handleCancelTask = async () => {
    try {
      const res = await tradeApi.cancelTakeProfitTask(stockCode);
      if (res.success) {
        setTask(null);
        loadData();
      }
    } catch (err) {
      console.error("取消止盈任务失败:", err);
    }
  };

  if (loading && lots.length === 0) {
    return (
      <div className="py-4 text-center text-gray-500 text-sm">加载中...</div>
    );
  }

  if (lots.length === 0) {
    return (
      <div className="py-4 text-center text-gray-500 text-sm">
        暂无分仓数据（需连接富途API获取历史成交）
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* 止盈任务状态 */}
      {task && task.status === "ACTIVE" && (
        <div className="flex items-center justify-between bg-blue-50 border border-blue-200 rounded-lg px-3 py-2">
          <div className="text-sm">
            <span className="text-blue-800 font-medium">
              止盈任务进行中
            </span>
            <span className="text-blue-600 ml-2">
              {task.take_profit_pct}% | 已卖出 {task.sold_lots}/{task.total_lots}
            </span>
          </div>
          <button
            onClick={handleCancelTask}
            className="text-xs text-red-600 hover:text-red-800 px-2 py-1 rounded hover:bg-red-50"
          >
            取消
          </button>
        </div>
      )}

      {/* 仓位表格 */}
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">
                仓位
              </th>
              <th className="px-3 py-2 text-right text-xs font-medium text-gray-500">
                买入价
              </th>
              <th className="px-3 py-2 text-right text-xs font-medium text-gray-500">
                数量
              </th>
              <th className="px-3 py-2 text-right text-xs font-medium text-gray-500">
                盈亏
              </th>
              <th className="px-3 py-2 text-right text-xs font-medium text-gray-500">
                止盈价
              </th>
              <th className="px-3 py-2 text-center text-xs font-medium text-gray-500">
                状态
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {lots.map((lot, idx) => {
              const exec = task?.executions?.find(
                (e) =>
                  Math.abs(e.lot_buy_price - lot.buy_price) < 0.001 &&
                  e.lot_quantity === lot.remaining_qty
              );
              const statusInfo = exec
                ? STATUS_LABELS[exec.status] || STATUS_LABELS.PENDING
                : null;

              return (
                <tr key={lot.deal_id || idx} className="hover:bg-gray-50">
                  <td className="px-3 py-2 text-gray-600">#{idx + 1}</td>
                  <td className="px-3 py-2 text-right text-gray-900">
                    {formatPrice(lot.buy_price)}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-900">
                    {lot.remaining_qty}
                  </td>
                  <td
                    className={`px-3 py-2 text-right font-medium ${
                      lot.current_profit_pct >= 0
                        ? "text-red-600"
                        : "text-green-600"
                    }`}
                  >
                    {formatPercent(lot.current_profit_pct)}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-900">
                    {lot.trigger_price > 0 ? formatPrice(lot.trigger_price) : "-"}
                  </td>
                  <td className="px-3 py-2 text-center">
                    {statusInfo ? (
                      <span
                        className={`inline-block px-2 py-0.5 rounded text-xs ${statusInfo.color}`}
                      >
                        {statusInfo.text}
                      </span>
                    ) : (
                      <span className="text-xs text-gray-400">-</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* 操作按钮 */}
      {(!task || task.status !== "ACTIVE") && (
        <div className="flex justify-end">
          <button
            onClick={onSetTakeProfit}
            className="px-4 py-2 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700"
          >
            设置止盈
          </button>
        </div>
      )}
    </div>
  );
}
