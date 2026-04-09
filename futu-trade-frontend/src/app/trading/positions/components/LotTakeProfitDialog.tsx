// 止盈配置对话框组件 - 为单笔订单设置止盈参数

"use client";

import { useState, useEffect, useCallback } from "react";
import { Modal, Button, useToast } from "@/components/common";
import { positionOrderApi } from "@/lib/api";
import { formatPrice } from "@/lib/utils";
import type { OrderRecord } from "@/types";

// ==================== 类型定义 ====================

interface LotTakeProfitDialogProps {
  order: OrderRecord | null; // null 时不显示对话框
  onClose: () => void;
  onSuccess: () => void; // 创建成功后回调（刷新订单列表）
}

interface FormState {
  takeProfitPct: string;
  takeProfitPrice: string;
}

interface ValidationError {
  pct: string | null;
  price: string | null;
}

// ==================== 计算工具 ====================

/** 根据止盈点数计算目标价格：目标价 = 买入价 × (1 + 止盈点数 / 100) */
function calcPriceFromPct(buyPrice: number, pct: number): number {
  return buyPrice * (1 + pct / 100);
}

/** 根据止盈价格计算止盈点数：止盈点数 = (目标价 - 买入价) / 买入价 × 100 */
function calcPctFromPrice(buyPrice: number, targetPrice: number): number {
  return ((targetPrice - buyPrice) / buyPrice) * 100;
}

// ==================== 子组件 ====================

/** 订单信息展示区 */
function OrderInfoSection({ order }: { order: OrderRecord }) {
  return (
    <div className="bg-gray-50 rounded-lg p-4 mb-4">
      <h4 className="text-sm font-medium text-gray-700 mb-3">订单信息</h4>
      <div className="grid grid-cols-3 gap-4 text-sm">
        <div>
          <span className="text-gray-500">买入价格</span>
          <p className="font-medium text-gray-900 mt-0.5">{formatPrice(order.buy_price)}</p>
        </div>
        <div>
          <span className="text-gray-500">买入数量</span>
          <p className="font-medium text-gray-900 mt-0.5">{order.quantity}</p>
        </div>
        <div>
          <span className="text-gray-500">剩余数量</span>
          <p className="font-medium text-gray-900 mt-0.5">{order.remaining_qty}</p>
        </div>
      </div>
    </div>
  );
}

/** 预计盈利展示 */
function ProfitPreview({ buyPrice, takeProfitPrice, remainingQty }: {
  buyPrice: number;
  takeProfitPrice: number;
  remainingQty: number;
}) {
  const profit = (takeProfitPrice - buyPrice) * remainingQty;
  if (isNaN(profit) || takeProfitPrice <= 0) return null;

  return (
    <div className="bg-blue-50 rounded-lg p-3 mt-4">
      <div className="flex items-center justify-between text-sm">
        <span className="text-blue-700">预计盈利金额</span>
        <span className={`font-semibold ${profit >= 0 ? "text-red-600" : "text-green-600"}`}>
          {profit >= 0 ? "+" : ""}{profit.toFixed(2)}
        </span>
      </div>
    </div>
  );
}

// ==================== 主组件 ====================

export function LotTakeProfitDialog({ order, onClose, onSuccess }: LotTakeProfitDialogProps) {
  const { showToast } = useToast();
  const [form, setForm] = useState<FormState>({ takeProfitPct: "", takeProfitPrice: "" });
  const [errors, setErrors] = useState<ValidationError>({ pct: null, price: null });
  const [submitting, setSubmitting] = useState(false);

  // 对话框打开时重置表单
  useEffect(() => {
    if (order) {
      setForm({ takeProfitPct: "", takeProfitPrice: "" });
      setErrors({ pct: null, price: null });
      setSubmitting(false);
    }
  }, [order]);

  // 止盈点数变化 → 自动计算止盈价格
  const handlePctChange = useCallback((value: string) => {
    setForm((prev) => {
      const pct = parseFloat(value);
      if (!order || isNaN(pct)) {
        return { takeProfitPct: value, takeProfitPrice: "" };
      }
      const price = calcPriceFromPct(order.buy_price, pct);
      return { takeProfitPct: value, takeProfitPrice: price.toFixed(2) };
    });
    setErrors({ pct: null, price: null });
  }, [order]);

  // 止盈价格变化 → 自动计算止盈点数
  const handlePriceChange = useCallback((value: string) => {
    setForm((prev) => {
      const price = parseFloat(value);
      if (!order || isNaN(price)) {
        return { takeProfitPct: "", takeProfitPrice: value };
      }
      const pct = calcPctFromPrice(order.buy_price, price);
      return { takeProfitPct: pct.toFixed(2), takeProfitPrice: value };
    });
    setErrors({ pct: null, price: null });
  }, [order]);

  // 表单验证
  const validate = useCallback((): boolean => {
    if (!order) return false;
    const pct = parseFloat(form.takeProfitPct);
    const price = parseFloat(form.takeProfitPrice);
    const newErrors: ValidationError = { pct: null, price: null };

    if (isNaN(pct) || pct <= 0) {
      newErrors.pct = "止盈点数必须大于 0";
    }
    if (isNaN(price) || price <= order.buy_price) {
      newErrors.price = `止盈价格必须大于买入价格 (${formatPrice(order.buy_price)})`;
    }

    setErrors(newErrors);
    return !newErrors.pct && !newErrors.price;
  }, [order, form]);

  // 提交止盈配置
  const handleSubmit = useCallback(async () => {
    if (!order || !validate()) return;

    setSubmitting(true);
    try {
      const response = await positionOrderApi.createLotTakeProfit({
        stock_code: order.stock_code,
        deal_id: order.deal_id,
        buy_price: order.buy_price,
        quantity: order.remaining_qty,
        take_profit_pct: parseFloat(form.takeProfitPct),
        take_profit_price: parseFloat(form.takeProfitPrice),
      });

      if (response.success) {
        showToast("success", "设置成功", "止盈配置已保存");
        onSuccess();
        onClose();
      } else {
        showToast("error", "设置失败", response.message || "创建止盈配置失败");
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "创建止盈配置失败";
      showToast("error", "设置失败", message);
    } finally {
      setSubmitting(false);
    }
  }, [order, form, validate, onSuccess, onClose, showToast]);

  if (!order) return null;

  const pctValue = parseFloat(form.takeProfitPrice);

  const footer = (
    <div className="flex justify-end gap-3">
      <Button variant="secondary" size="sm" onClick={onClose} disabled={submitting}>
        取消
      </Button>
      <Button variant="primary" size="sm" onClick={handleSubmit} loading={submitting}>
        确认设置
      </Button>
    </div>
  );

  return (
    <Modal isOpen={!!order} onClose={onClose} title="设置止盈" size="sm" footer={footer}>
      <OrderInfoSection order={order} />

      {/* 止盈点数输入 */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-1">止盈点数 (%)</label>
        <input
          type="number"
          step="0.01"
          min="0"
          value={form.takeProfitPct}
          onChange={(e) => handlePctChange(e.target.value)}
          placeholder="输入止盈百分比，如 10 表示 10%"
          className={`w-full px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
            errors.pct ? "border-red-300 bg-red-50" : "border-gray-300"
          }`}
        />
        {errors.pct && <p className="text-xs text-red-600 mt-1">{errors.pct}</p>}
      </div>

      {/* 止盈价格输入 */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-1">止盈价格</label>
        <input
          type="number"
          step="0.01"
          min="0"
          value={form.takeProfitPrice}
          onChange={(e) => handlePriceChange(e.target.value)}
          placeholder={`输入目标价格，需大于买入价 ${formatPrice(order.buy_price)}`}
          className={`w-full px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
            errors.price ? "border-red-300 bg-red-50" : "border-gray-300"
          }`}
        />
        {errors.price && <p className="text-xs text-red-600 mt-1">{errors.price}</p>}
      </div>

      {/* 预计盈利 */}
      {!isNaN(pctValue) && pctValue > 0 && (
        <ProfitPreview
          buyPrice={order.buy_price}
          takeProfitPrice={pctValue}
          remainingQty={order.remaining_qty}
        />
      )}
    </Modal>
  );
}
