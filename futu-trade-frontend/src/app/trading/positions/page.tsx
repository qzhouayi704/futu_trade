// 持仓订单历史记录页面

"use client";

import { useState, useEffect, useCallback, Fragment } from "react";
import { Card, Button } from "@/components/common";
import { tradeApi, positionOrderApi } from "@/lib/api";
import { formatPrice, formatPercent } from "@/lib/utils";
import type { Position, OrderRecord } from "@/types";
import {
  SummaryCard,
  ErrorBanner,
  PositionRow,
  type ExpandedOrderData,
} from "./components/PositionListParts";
import { OrderHistoryPanel } from "./components/OrderHistoryPanel";
import { LotTakeProfitDialog } from "./components/LotTakeProfitDialog";

/** 展开区域：处理加载/错误状态，成功时渲染 OrderHistoryPanel */
function ExpandedOrderSection({
  data,
  onRetry,
  onSetTakeProfit,
  onCancelTakeProfit,
}: {
  data: ExpandedOrderData | undefined;
  onRetry: () => void;
  onSetTakeProfit: (order: OrderRecord) => void;
  onCancelTakeProfit: (executionId: number) => void;
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

  return (
    <OrderHistoryPanel
      orders={data.orders}
      onSetTakeProfit={onSetTakeProfit}
      onCancelTakeProfit={onCancelTakeProfit}
      onRefresh={onRetry}
    />
  );
}

export default function PositionsPage() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedStock, setExpandedStock] = useState<string | null>(null);
  const [orderDataMap, setOrderDataMap] = useState<Record<string, ExpandedOrderData>>({});
  const [selectedOrder, setSelectedOrder] = useState<OrderRecord | null>(null);

  // 加载持仓数据
  const loadPositions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await tradeApi.getPositionsStandalone();
      if (response.success && response.data) {
        // 转换 BackendPosition 到 Position
        const convertedPositions: Position[] = response.data.positions.map(bp => ({
          stock_code: bp.stock_code,
          stock_name: bp.stock_name,
          qty: bp.qty,
          can_sell_qty: bp.can_sell_qty || bp.qty,
          cost_price: bp.cost_price,
          current_price: bp.nominal_price,
          market_value: bp.market_val,
          pl_val: bp.pl_val,
          pl_ratio: bp.pl_ratio,
          today_pl_val: bp.today_pl_val || 0,
        }));
        setPositions(convertedPositions);
      } else {
        throw new Error(response.message || "获取持仓数据失败");
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "获取持仓数据失败";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  // 页面加载时自动获取持仓数据
  useEffect(() => {
    loadPositions();
  }, [loadPositions]);

  // 加载某只股票的订单历史
  const loadOrderHistory = useCallback(async (stockCode: string) => {
    setOrderDataMap((prev) => ({
      ...prev,
      [stockCode]: { loading: true, error: null, orders: [] },
    }));
    try {
      const response = await positionOrderApi.getOrderLots(stockCode);
      if (response.success && response.data) {
        setOrderDataMap((prev) => ({
          ...prev,
          [stockCode]: { loading: false, error: null, orders: response.data! },
        }));
      } else {
        throw new Error(response.message || "获取订单历史失败");
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "获取订单历史失败";
      setOrderDataMap((prev) => ({
        ...prev,
        [stockCode]: { loading: false, error: message, orders: [] },
      }));
    }
  }, []);

  // 展开/收起订单历史
  const toggleExpand = useCallback(
    (stockCode: string) => {
      if (expandedStock === stockCode) {
        setExpandedStock(null);
        return;
      }
      setExpandedStock(stockCode);
      if (!orderDataMap[stockCode]) {
        loadOrderHistory(stockCode);
      }
    },
    [expandedStock, orderDataMap, loadOrderHistory]
  );

  // 持仓摘要
  const summary = {
    count: positions.length,
    marketValue: positions.reduce((sum, p) => sum + (p.market_value || 0), 0),
    totalPL: positions.reduce((sum, p) => sum + (p.pl_val || 0), 0),
    avgPLRatio:
      positions.length > 0
        ? positions.reduce((sum, p) => sum + (p.pl_ratio || 0), 0) / positions.length
        : 0,
  };

  // 点击"自动止盈"按钮 → 打开止盈配置对话框
  const handleSetTakeProfit = useCallback((order: OrderRecord) => {
    setSelectedOrder(order);
  }, []);

  // 取消止盈配置
  const handleCancelTakeProfit = useCallback(
    async (executionId: number, stockCode: string) => {
      try {
        const response = await positionOrderApi.cancelLotTakeProfit(executionId);
        if (response.success) {
          loadOrderHistory(stockCode);
        }
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : "取消止盈失败";
        console.error(message);
      }
    },
    [loadOrderHistory]
  );

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      {/* 页面标题 */}
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <i className="fas fa-layer-group text-blue-600"></i>
          持仓订单
        </h1>
        <Button variant="primary" size="sm" onClick={loadPositions} loading={loading}>
          <i className="fas fa-sync mr-1"></i>
          刷新
        </Button>
      </div>

      {/* 持仓摘要 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <SummaryCard label="持仓数量" value={String(summary.count)} />
        <SummaryCard label="总市值" value={formatPrice(summary.marketValue)} color="blue" />
        <SummaryCard
          label="总盈亏"
          value={formatPrice(summary.totalPL)}
          color={summary.totalPL >= 0 ? "red" : "green"}
        />
        <SummaryCard
          label="平均盈亏比例"
          value={formatPercent(summary.avgPLRatio)}
          color={summary.avgPLRatio >= 0 ? "red" : "green"}
        />
      </div>

      {/* 错误提示 */}
      {error && <ErrorBanner message={error} onRetry={loadPositions} />}

      {/* 加载状态 */}
      {loading && !error && (
        <Card>
          <div className="flex items-center justify-center py-12 text-gray-500">
            <svg className="animate-spin h-8 w-8 text-blue-600 mr-3" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            正在加载持仓数据...
          </div>
        </Card>
      )}

      {/* 持仓列表 */}
      {!loading && !error && (
        <Card>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">股票代码</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">股票名称</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">持仓数量</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">成本价</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">当前价</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">盈亏</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">盈亏比例</th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">操作</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {positions.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-gray-500">
                      <i className="fas fa-inbox text-3xl mb-2 block"></i>
                      暂无持仓数据
                    </td>
                  </tr>
                ) : (
                  positions.map((pos) => (
                    <Fragment key={pos.stock_code}>
                      <PositionRow
                        position={pos}
                        isExpanded={expandedStock === pos.stock_code}
                        onToggle={() => toggleExpand(pos.stock_code)}
                      />
                      {expandedStock === pos.stock_code && (
                        <tr>
                          <td colSpan={8} className="px-4 py-3 bg-gray-50">
                            <ExpandedOrderSection
                              data={orderDataMap[pos.stock_code]}
                              onRetry={() => loadOrderHistory(pos.stock_code)}
                              onSetTakeProfit={handleSetTakeProfit}
                              onCancelTakeProfit={(executionId) =>
                                handleCancelTakeProfit(executionId, pos.stock_code)
                              }
                            />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* 止盈配置对话框 */}
      <LotTakeProfitDialog
        order={selectedOrder}
        onClose={() => setSelectedOrder(null)}
        onSuccess={() => {
          if (selectedOrder) {
            loadOrderHistory(selectedOrder.stock_code);
          }
          setSelectedOrder(null);
        }}
      />
    </div>
  );
}
