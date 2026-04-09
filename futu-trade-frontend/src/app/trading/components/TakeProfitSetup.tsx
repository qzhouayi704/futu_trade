// 止盈设置对话框

"use client";

import { useState, useEffect } from "react";
import { Modal } from "@/components/common";
import { tradeApi } from "@/lib/api";
import { useToast } from "@/components/common/Toast";
import { formatPrice } from "@/lib/utils";
import type { PositionLot } from "@/types";

interface TakeProfitSetupProps {
  isOpen: boolean;
  onClose: () => void;
  stockCode: string;
  stockName: string;
  currentPrice: number;
}

export default function TakeProfitSetup({
  isOpen,
  onClose,
  stockCode,
  stockName,
  currentPrice,
}: TakeProfitSetupProps) {
  const { showToast } = useToast();
  const [profitPct, setProfitPct] = useState(10);
  const [lots, setLots] = useState<PositionLot[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // 加载仓位数据
  useEffect(() => {
    if (isOpen && stockCode) {
      setLoading(true);
      tradeApi
        .getPositionLots(stockCode)
        .then((res) => {
          if (res.success && res.data) setLots(res.data);
        })
        .catch(console.error)
        .finally(() => setLoading(false));
    }
  }, [isOpen, stockCode]);

  // 计算预览的止盈触发价
  const previewLots = lots.map((lot) => ({
    ...lot,
    trigger_price: +(lot.buy_price * (1 + profitPct / 100)).toFixed(3),
  }));

  const handleSubmit = async () => {
    if (profitPct <= 0 || profitPct > 100) {
      showToast("warning", "提示", "止盈百分比需在 0-100 之间");
      return;
    }

    setSubmitting(true);
    try {
      const res = await tradeApi.createTakeProfitTask({
        stock_code: stockCode,
        take_profit_pct: profitPct,
      });

      if (res.success) {
        showToast("success", "成功", "止盈任务创建成功");
        onClose();
      } else {
        showToast("error", "失败", res.message || "创建失败");
      }
    } catch (err: any) {
      showToast("error", "错误", err.message || "创建失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="设置分仓止盈">
      <div className="space-y-4">
        {/* 股票信息 */}
        <div className="bg-gray-50 rounded-lg p-3">
          <div className="flex justify-between text-sm">
            <span className="text-gray-600">股票</span>
            <span className="font-medium">
              {stockCode} {stockName}
            </span>
          </div>
          <div className="flex justify-between text-sm mt-1">
            <span className="text-gray-600">当前价</span>
            <span className="font-medium">{formatPrice(currentPrice)}</span>
          </div>
          <div className="flex justify-between text-sm mt-1">
            <span className="text-gray-600">仓位数</span>
            <span className="font-medium">{lots.length} 个</span>
          </div>
        </div>

        {/* 止盈百分比 */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            止盈百分比
          </label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              value={profitPct}
              onChange={(e) => setProfitPct(parseFloat(e.target.value) || 0)}
              min={1}
              max={100}
              step={1}
              className="flex-1 px-3 py-2 border border-gray-300 rounded-md"
            />
            <span className="text-gray-500">%</span>
          </div>
          <p className="text-xs text-gray-500 mt-1">
            每个仓位根据买入价独立计算止盈触发价，低成本仓位优先卖出
          </p>
        </div>

        {/* 仓位预览 */}
        {!loading && previewLots.length > 0 && (
          <div>
            <div className="text-sm font-medium text-gray-700 mb-2">
              止盈触发价预览
            </div>
            <div className="space-y-1 max-h-40 overflow-y-auto">
              {previewLots.map((lot, idx) => (
                <div
                  key={lot.deal_id || idx}
                  className="flex justify-between text-sm bg-gray-50 rounded px-3 py-1.5"
                >
                  <span className="text-gray-600">
                    #{idx + 1} 买入@{formatPrice(lot.buy_price)} x
                    {lot.remaining_qty}股
                  </span>
                  <span className="font-medium text-blue-600">
                    触发@{formatPrice(lot.trigger_price)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {loading && (
          <div className="text-center py-4 text-gray-500 text-sm">
            加载仓位数据...
          </div>
        )}
      </div>

      {/* 操作按钮 */}
      <div className="flex justify-end gap-3 mt-6">
        <button
          onClick={onClose}
          className="px-4 py-2 text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200"
        >
          取消
        </button>
        <button
          onClick={handleSubmit}
          disabled={submitting || lots.length === 0}
          className="px-4 py-2 text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-50"
        >
          {submitting ? "创建中..." : "确认创建"}
        </button>
      </div>
    </Modal>
  );
}
