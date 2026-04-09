// 订单历史面板组件 - 展示某只股票的历史买入订单列表及止盈状态

"use client";

import { Button } from "@/components/common";
import { formatPrice, formatPercent } from "@/lib/utils";
import type { OrderRecord } from "@/types";

// ==================== 类型定义 ====================

interface OrderHistoryPanelProps {
  orders: OrderRecord[];
  onSetTakeProfit: (order: OrderRecord) => void;
  onCancelTakeProfit: (executionId: number) => void;
  onRefresh: () => void;
}

type TakeProfitStatus = NonNullable<OrderRecord["take_profit_status"]>;

interface StatusConfig {
  label: string;
  className: string;
}

// ==================== 止盈状态配置 ====================

const STATUS_MAP: Record<TakeProfitStatus, StatusConfig> = {
  PENDING: { label: "待触发", className: "bg-yellow-100 text-yellow-800" },
  TRIGGERED: { label: "已触发，等待成交", className: "bg-blue-100 text-blue-800" },
  EXECUTED: { label: "已成交", className: "bg-green-100 text-green-800" },
  FAILED: { label: "失败", className: "bg-red-100 text-red-800" },
  CANCELLED: { label: "已取消", className: "bg-gray-100 text-gray-600" },
};

// ==================== 子组件 ====================

/** 止盈状态标签 */
function StatusBadge({ status }: { status: TakeProfitStatus }) {
  const config = STATUS_MAP[status];
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${config.className}`}>
      {config.label}
    </span>
  );
}

/** PENDING 状态：显示止盈目标价 + 取消按钮 */
function PendingActions({
  order,
  onCancel,
}: {
  order: OrderRecord;
  onCancel: (executionId: number) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <StatusBadge status="PENDING" />
      {order.take_profit_price && (
        <span className="text-xs text-gray-500">
          目标: {formatPrice(order.take_profit_price)}
        </span>
      )}
      <button
        onClick={() => onCancel(order.execution_id!)}
        className="text-xs text-red-600 hover:text-red-800 px-1.5 py-0.5 rounded hover:bg-red-50 transition-colors"
      >
        取消
      </button>
    </div>
  );
}

/** 可重新设置的状态（FAILED / CANCELLED） */
function ResettableActions({
  order,
  onSetTakeProfit,
}: {
  order: OrderRecord;
  onSetTakeProfit: (order: OrderRecord) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <StatusBadge status={order.take_profit_status!} />
      <button
        onClick={() => onSetTakeProfit(order)}
        className="text-xs text-blue-600 hover:text-blue-800 px-1.5 py-0.5 rounded hover:bg-blue-50 transition-colors"
      >
        重新设置
      </button>
    </div>
  );
}

/** 止盈操作列 - 根据状态渲染不同内容 */
function TakeProfitCell({
  order,
  onSetTakeProfit,
  onCancelTakeProfit,
}: {
  order: OrderRecord;
  onSetTakeProfit: (order: OrderRecord) => void;
  onCancelTakeProfit: (executionId: number) => void;
}) {
  const status = order.take_profit_status;

  // 无止盈配置 → 显示"自动止盈"按钮
  if (!status) {
    return (
      <Button variant="primary" size="sm" onClick={() => onSetTakeProfit(order)}>
        自动止盈
      </Button>
    );
  }

  switch (status) {
    case "PENDING":
      return <PendingActions order={order} onCancel={onCancelTakeProfit} />;
    case "TRIGGERED":
      return <StatusBadge status="TRIGGERED" />;
    case "EXECUTED":
      return <StatusBadge status="EXECUTED" />;
    case "FAILED":
    case "CANCELLED":
      return <ResettableActions order={order} onSetTakeProfit={onSetTakeProfit} />;
    default:
      return null;
  }
}

/** 单条订单行 */
function OrderRow({
  order,
  onSetTakeProfit,
  onCancelTakeProfit,
}: {
  order: OrderRecord;
  onSetTakeProfit: (order: OrderRecord) => void;
  onCancelTakeProfit: (executionId: number) => void;
}) {
  const profitColor = order.current_profit_pct >= 0 ? "text-red-600" : "text-green-600";

  return (
    <tr className="border-t border-gray-100 hover:bg-gray-50/50">
      <td className="py-2 pr-4 text-gray-600 text-xs">{order.deal_time}</td>
      <td className="py-2 pr-4 text-right">{formatPrice(order.buy_price)}</td>
      <td className="py-2 pr-4 text-right">{order.quantity}</td>
      <td className="py-2 pr-4 text-right">{order.remaining_qty}</td>
      <td className={`py-2 pr-4 text-right font-medium ${profitColor}`}>
        {formatPercent(order.current_profit_pct)}
      </td>
      <td className="py-2 text-right">
        <TakeProfitCell
          order={order}
          onSetTakeProfit={onSetTakeProfit}
          onCancelTakeProfit={onCancelTakeProfit}
        />
      </td>
    </tr>
  );
}

// ==================== 主组件 ====================

export function OrderHistoryPanel({
  orders,
  onSetTakeProfit,
  onCancelTakeProfit,
  onRefresh,
}: OrderHistoryPanelProps) {
  if (orders.length === 0) {
    return <div className="text-center py-4 text-gray-500 text-sm">暂无订单历史</div>;
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-gray-700">
          订单历史（共 {orders.length} 条）
        </span>
        <button
          onClick={onRefresh}
          className="text-xs text-blue-600 hover:text-blue-800 px-2 py-1 rounded hover:bg-blue-50 transition-colors"
        >
          <i className="fas fa-sync mr-1"></i>刷新
        </button>
      </div>

      <table className="min-w-full text-sm">
        <thead>
          <tr className="text-xs text-gray-500">
            <th className="text-left py-1 pr-4">买入时间</th>
            <th className="text-right py-1 pr-4">买入价格</th>
            <th className="text-right py-1 pr-4">买入数量</th>
            <th className="text-right py-1 pr-4">剩余数量</th>
            <th className="text-right py-1 pr-4">盈亏%</th>
            <th className="text-right py-1">止盈操作</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => (
            <OrderRow
              key={order.deal_id}
              order={order}
              onSetTakeProfit={onSetTakeProfit}
              onCancelTakeProfit={onCancelTakeProfit}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}
