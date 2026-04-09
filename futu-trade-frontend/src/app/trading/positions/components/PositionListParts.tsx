// 持仓列表子组件

import { Card, Button } from "@/components/common";
import { formatPrice, formatPercent } from "@/lib/utils";
import type { Position, OrderRecord } from "@/types";

/** 展开行的订单数据缓存 */
export interface ExpandedOrderData {
  loading: boolean;
  error: string | null;
  orders: OrderRecord[];
}

/** 摘要卡片 */
export function SummaryCard({ label, value, color }: { label: string; value: string; color?: string }) {
  const colorClass =
    color === "red" ? "text-red-600" : color === "green" ? "text-green-600" : color === "blue" ? "text-blue-600" : "text-gray-900";
  return (
    <Card>
      <div className="text-center">
        <div className="text-sm text-gray-600 mb-1">{label}</div>
        <div className={`text-2xl font-bold ${colorClass}`}>{value}</div>
      </div>
    </Card>
  );
}

/** 错误提示横幅 */
export function ErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="mb-6 bg-red-50 border border-red-200 rounded-lg p-4 flex items-center justify-between">
      <div className="flex items-center text-red-800">
        <i className="fas fa-exclamation-circle text-red-500 mr-2"></i>
        {message}
      </div>
      <Button variant="danger" size="sm" onClick={onRetry}>
        <i className="fas fa-redo mr-1"></i>
        重试
      </Button>
    </div>
  );
}

/** 持仓行 */
export function PositionRow({
  position,
  isExpanded,
  onToggle,
}: {
  position: Position;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const plColor = (position.pl_val || 0) >= 0 ? "text-red-600" : "text-green-600";
  const ratioColor = (position.pl_ratio || 0) >= 0 ? "text-red-600" : "text-green-600";

  return (
    <tr className="hover:bg-gray-50">
      <td className="px-4 py-3 text-sm font-medium text-gray-900">{position.stock_code}</td>
      <td className="px-4 py-3 text-sm text-gray-900">{position.stock_name}</td>
      <td className="px-4 py-3 text-sm text-right text-gray-900">{position.qty || position.quantity || 0}</td>
      <td className="px-4 py-3 text-sm text-right text-gray-900">{formatPrice(position.cost_price)}</td>
      <td className="px-4 py-3 text-sm text-right text-gray-900">{formatPrice(position.current_price || 0)}</td>
      <td className={`px-4 py-3 text-sm text-right font-medium ${plColor}`}>{formatPrice(position.pl_val || 0)}</td>
      <td className={`px-4 py-3 text-sm text-right font-medium ${ratioColor}`}>{formatPercent(position.pl_ratio || 0)}</td>
      <td className="px-4 py-3 text-center">
        <button
          onClick={onToggle}
          className="text-xs text-blue-600 hover:text-blue-800 px-2 py-1 rounded hover:bg-blue-50 transition-colors"
        >
          <i className={`fas fa-chevron-${isExpanded ? "up" : "down"} mr-1`}></i>
          {isExpanded ? "收起" : "订单"}
        </button>
      </td>
    </tr>
  );
}

/** 订单历史占位（任务 6.2 将替换为 OrderHistoryPanel 组件） */
export function OrderHistoryPlaceholder({
  data,
  onRetry,
}: {
  data: ExpandedOrderData | undefined;
  onRetry: () => void;
}) {
  if (!data || data.loading) {
    return (
      <div className="flex items-center justify-center py-6 text-gray-500 text-sm">
        <svg className="animate-spin h-5 w-5 text-blue-600 mr-2" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
        </svg>
        正在加载订单历史...
      </div>
    );
  }

  if (data.error) {
    return (
      <div className="flex items-center justify-between py-4 text-sm">
        <span className="text-red-600">
          <i className="fas fa-exclamation-circle mr-1"></i>
          {data.error}
        </span>
        <button onClick={onRetry} className="text-blue-600 hover:text-blue-800 text-xs px-2 py-1 rounded hover:bg-blue-50">
          <i className="fas fa-redo mr-1"></i>重试
        </button>
      </div>
    );
  }

  if (data.orders.length === 0) {
    return <div className="text-center py-4 text-gray-500 text-sm">暂无订单历史</div>;
  }

  return (
    <div className="space-y-2">
      <div className="text-sm font-medium text-gray-700 mb-2">订单历史（共 {data.orders.length} 条）</div>
      <table className="min-w-full text-sm">
        <thead>
          <tr className="text-xs text-gray-500">
            <th className="text-left py-1 pr-4">买入时间</th>
            <th className="text-right py-1 pr-4">买入价格</th>
            <th className="text-right py-1 pr-4">买入数量</th>
            <th className="text-right py-1 pr-4">剩余数量</th>
            <th className="text-right py-1">盈亏%</th>
          </tr>
        </thead>
        <tbody>
          {data.orders.map((order) => (
            <tr key={order.deal_id} className="border-t border-gray-100">
              <td className="py-1.5 pr-4 text-gray-600">{order.deal_time}</td>
              <td className="py-1.5 pr-4 text-right">{formatPrice(order.buy_price)}</td>
              <td className="py-1.5 pr-4 text-right">{order.quantity}</td>
              <td className="py-1.5 pr-4 text-right">{order.remaining_qty}</td>
              <td className={`py-1.5 text-right font-medium ${order.current_profit_pct >= 0 ? "text-red-600" : "text-green-600"}`}>
                {formatPercent(order.current_profit_pct)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
