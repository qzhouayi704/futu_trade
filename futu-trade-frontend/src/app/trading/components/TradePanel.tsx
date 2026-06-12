// 自动交易页面

"use client";

import { useState, useEffect, Fragment } from "react";
import { Card, Button, Modal } from "@/components/common";
import { tradeApi } from "@/lib/api";
import { useSocket } from "@/lib/socket";
import { useTradingStore } from "@/lib/stores";
import { useToast } from "@/components/common/Toast";
import { formatPrice, formatPercent } from "@/lib/utils";
import type { TradeSignal, Position, TradeRecord } from "@/types";
import LotDetailPanel from "./LotDetailPanel";
import TakeProfitSetup from "./TakeProfitSetup";
import { AutoTradeStrategySelector } from "./AutoTradeStrategySelector";

export default function TradePanel() {
  const { socket } = useSocket();
  const { showToast } = useToast();
  const { signals, positions, setSignals, setPositions } = useTradingStore();

  const [selectedStock, setSelectedStock] = useState<TradeSignal | null>(null);
  const [tradeQuantity, setTradeQuantity] = useState(100);
  const [tradePrice, setTradePrice] = useState<number | null>(null);
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [tradeType, setTradeType] = useState<"buy" | "sell">("buy");
  const [loading, setLoading] = useState(false);
  const [records, setRecords] = useState<TradeRecord[]>([]);
  const [expandedStock, setExpandedStock] = useState<string | null>(null);
  const [takeProfitTarget, setTakeProfitTarget] = useState<Position | null>(null);
  const [manualCode, setManualCode] = useState("");
  const [preCheckResult, setPreCheckResult] = useState<any>(null);
  const [checkingTrade, setCheckingTrade] = useState(false);

  // 加载交易信号
  const loadSignals = async () => {
    try {
      const response = await tradeApi.getSignals({ type: "all" });
      console.log("交易信号响应:", response);
      if (response.success && response.data) {
        console.log("交易信号数据:", response.data);
        setSignals(response.data);
      } else {
        console.warn("未获取到交易信号数据");
      }
    } catch (err: any) {
      console.error("加载交易信号失败:", err);
      showToast("error", "错误", "加载交易信号失败: " + err.message);
    }
  };

  // 加载持仓
  const loadPositions = async () => {
    try {
      const response = await tradeApi.getPositions();
      if (response.success && response.data) {
        setPositions(response.data);
      }
    } catch (err: any) {
      console.error("加载持仓失败:", err);
    }
  };

  // 加载交易记录
  const loadRecords = async () => {
    try {
      const response = await tradeApi.getTradeRecords();
      if (response.success && response.data) {
        setRecords(response.data);
      }
    } catch (err: any) {
      console.error("加载交易记录失败:", err);
    }
  };

  // 初始化加载
  useEffect(() => {
    loadSignals();
    loadPositions();
    loadRecords();
  }, []);

  // 监听实时更新
  useEffect(() => {
    if (!socket) return;

    const handlePositionsUpdate = (data: any) => {
      if (data.positions) {
        setPositions(data.positions);
      }
    };

    const handleTradeExecuted = (data: any) => {
      showToast("success", "交易执行", `${data.message}`);
      loadPositions();
      loadRecords();
    };

    socket.on("positions_update", handlePositionsUpdate);
    socket.on("trade_executed", handleTradeExecuted);

    return () => {
      socket.off("positions_update", handlePositionsUpdate);
      socket.off("trade_executed", handleTradeExecuted);
    };
  }, [socket]);

  // 显示交易确认（先调 pre-trade-check 检查）
  const handleShowConfirm = async (type: "buy" | "sell") => {
    // 如果手动输入了代码但没按回车，自动创建 selectedStock
    let stock = selectedStock;
    if (!stock && manualCode.trim()) {
      const val = manualCode.trim();
      const code = val.startsWith("HK.") ? val : `HK.${val}`;
      stock = {
        stock_code: code,
        stock_name: "",
        signal_type: "buy",
        signal_price: 0,
        id: 0,
      } as TradeSignal;
      setSelectedStock(stock);
      setManualCode("");
    }
    if (!stock) {
      showToast("warning", "提示", "请先输入或选择股票");
      return;
    }
    setTradeType(type);
    setCheckingTrade(true);
    setPreCheckResult(null);

    try {
      const code = stock.stock_code;
      const res = await fetch(`/api/pre-trade-check/${encodeURIComponent(code)}`);
      const json = await res.json();
      if (json.success && json.data) {
        setPreCheckResult(json.data);
      }
    } catch (err) {
      console.error("pre-trade-check 失败:", err);
      // 检查失败不阻止交易，只给提示
      setPreCheckResult(null);
    } finally {
      setCheckingTrade(false);
      setShowConfirmModal(true);
    }
  };

  // 执行交易
  const handleExecuteTrade = async () => {
    if (!selectedStock) return;

    setShowConfirmModal(false);
    setLoading(true);

    try {
      const response = await tradeApi.executeTrade({
        stock_code: selectedStock.stock_code,
        trade_type: tradeType,
        quantity: tradeQuantity,
        price: tradePrice || undefined,
      });

      if (response.success) {
        showToast("success", "成功", "交易已提交");
        loadPositions();
        loadRecords();
      } else {
        throw new Error(response.message || "交易失败");
      }
    } catch (err: any) {
      showToast("error", "错误", err.message || "交易失败");
    } finally {
      setLoading(false);
    }
  };

  // 计算持仓摘要
  const summary = {
    count: positions.length,
    marketValue: positions.reduce((sum, p) => sum + (p.market_value || 0), 0),
    totalPL: positions.reduce((sum, p) => sum + (p.pl_val || 0), 0),
    totalPLRatio:
      positions.length > 0
        ? (positions.reduce((sum, p) => sum + (p.pl_ratio || 0), 0) / positions.length)
        : 0,
  };

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      {/* 页面标题 */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <i className="fas fa-chart-line text-green-600"></i>
          自动交易
        </h1>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左侧：交易信号和操作面板 */}
        <div className="lg:col-span-1 space-y-6">
          {/* 自动交易策略选择器 */}
          <AutoTradeStrategySelector />

          {/* 交易信号列表 */}
          <Card>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-medium text-gray-900">交易信号</h2>
              <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium">
                {signals.length}
              </span>
            </div>

            <div className="space-y-2 max-h-96 overflow-y-auto">
              {signals.length === 0 ? (
                <div className="text-center py-8 text-gray-500">
                  <i className="fas fa-inbox text-3xl mb-2"></i>
                  <div>暂无交易信号</div>
                </div>
              ) : (
                signals.map((signal, index) => (
                  <div
                    key={signal.id || `signal_${signal.stock_code}_${index}`}
                    onClick={() => setSelectedStock(signal)}
                    className={`p-3 border rounded-lg cursor-pointer transition-colors ${
                      selectedStock?.id === signal.id
                        ? "border-blue-500 bg-blue-50"
                        : "border-gray-200 hover:border-blue-300"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium text-gray-900">
                        {signal.stock_code}
                      </span>
                      <span
                        className={`px-2 py-1 rounded text-xs font-medium ${
                          signal.signal_type === "buy"
                            ? "bg-green-100 text-green-800"
                            : "bg-red-100 text-red-800"
                        }`}
                      >
                        {signal.signal_type === "buy" ? "买入" : "卖出"}
                      </span>
                    </div>
                    <div className="text-sm text-gray-600">{signal.stock_name}</div>
                    <div className="text-sm text-gray-900 mt-1">
                      {formatPrice(signal.signal_price)}
                    </div>
                  </div>
                ))
              )}
            </div>
          </Card>

          {/* 交易操作面板 */}
          <Card>
            <h2 className="text-lg font-medium text-gray-900 mb-4">交易面板</h2>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  股票代码
                </label>
                <input
                  type="text"
                  value={selectedStock?.stock_code || manualCode}
                  onChange={(e) => {
                    setManualCode(e.target.value.toUpperCase());
                    // 清除之前选中的信号（手动输入模式）
                    if (selectedStock) setSelectedStock(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      const val = (selectedStock?.stock_code || manualCode).trim();
                      if (val) {
                        const code = val.startsWith("HK.") ? val : `HK.${val}`;
                        setSelectedStock({
                          stock_code: code,
                          stock_name: "",
                          signal_type: "buy",
                          signal_price: 0,
                          id: 0,
                        } as TradeSignal);
                        setManualCode("");
                      }
                    }
                  }}
                  placeholder="输入代码如 01236 或从信号列表选择"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  交易数量
                </label>
                <input
                  type="number"
                  value={tradeQuantity}
                  onChange={(e) => setTradeQuantity(parseInt(e.target.value))}
                  min={100}
                  step={100}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md"
                />
                <p className="text-xs text-gray-500 mt-1">最小交易单位：100股</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  交易价格
                </label>
                <input
                  type="number"
                  value={tradePrice || ""}
                  onChange={(e) =>
                    setTradePrice(e.target.value ? parseFloat(e.target.value) : null)
                  }
                  step={0.01}
                  placeholder="留空使用市价"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md"
                />
                <p className="text-xs text-gray-500 mt-1">留空使用市价交易</p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <Button
                  onClick={() => handleShowConfirm("buy")}
                  disabled={(!selectedStock && !manualCode.trim()) || loading || checkingTrade}
                  className="bg-red-600 hover:bg-red-700 text-white"
                >
                  <i className="fas fa-arrow-up mr-1"></i>
                  {checkingTrade && tradeType === "buy" ? "检查中..." : "买入"}
                </Button>
                <Button
                  onClick={() => handleShowConfirm("sell")}
                  disabled={(!selectedStock && !manualCode.trim()) || loading || checkingTrade}
                  className="bg-green-600 hover:bg-green-700 text-white"
                >
                  <i className="fas fa-arrow-down mr-1"></i>
                  {checkingTrade && tradeType === "sell" ? "检查中..." : "卖出"}
                </Button>
              </div>

              {/* 内联Pre-check结果预览 */}
              {checkingTrade && (
                <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-700 flex items-center gap-2">
                  <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin shrink-0" />
                  正在检查交易条件...
                </div>
              )}
              {preCheckResult && !checkingTrade && (
                <div
                  className={`rounded-lg p-3 border text-sm ${
                    preCheckResult.verdict === "STOP"
                      ? "bg-red-50 border-red-300 text-red-700"
                      : preCheckResult.verdict === "CAUTION"
                      ? "bg-yellow-50 border-yellow-300 text-yellow-700"
                      : "bg-green-50 border-green-300 text-green-700"
                  }`}
                >
                  <div className="flex items-center gap-1.5 font-bold text-xs">
                    <span>
                      {preCheckResult.verdict === "STOP" ? "🚫" : preCheckResult.verdict === "CAUTION" ? "⚠️" : "✅"}
                    </span>
                    {preCheckResult.verdict} · 评分 {preCheckResult.score}
                  </div>
                  <p className="text-[11px] mt-1 opacity-80">{preCheckResult.verdict_reason}</p>
                </div>
              )}

              <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 text-sm text-yellow-800">
                <i className="fas fa-exclamation-triangle mr-1"></i>
                交易将通过富途API执行，请确保富途客户端已登录
              </div>
            </div>
          </Card>
        </div>

        {/* 右侧：持仓和摘要 */}
        <div className="lg:col-span-2 space-y-6">
          {/* 持仓摘要 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card>
              <div className="text-center">
                <div className="text-sm text-gray-600 mb-1">持仓数量</div>
                <div className="text-2xl font-bold text-gray-900">{summary.count}</div>
              </div>
            </Card>
            <Card>
              <div className="text-center">
                <div className="text-sm text-gray-600 mb-1">总市值</div>
                <div className="text-2xl font-bold text-blue-600">
                  {formatPrice(summary.marketValue)}
                </div>
              </div>
            </Card>
            <Card>
              <div className="text-center">
                <div className="text-sm text-gray-600 mb-1">总盈亏</div>
                <div
                  className={`text-2xl font-bold ${
                    summary.totalPL >= 0 ? "text-red-600" : "text-green-600"
                  }`}
                >
                  {formatPrice(summary.totalPL)}
                </div>
              </div>
            </Card>
            <Card>
              <div className="text-center">
                <div className="text-sm text-gray-600 mb-1">盈亏比例</div>
                <div
                  className={`text-2xl font-bold ${
                    summary.totalPLRatio >= 0 ? "text-red-600" : "text-green-600"
                  }`}
                >
                  {formatPercent(summary.totalPLRatio)}
                </div>
              </div>
            </Card>
          </div>

          {/* 持仓列表 */}
          <Card>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-medium text-gray-900">持仓信息</h2>
              <Button variant="secondary" size="sm" onClick={loadPositions}>
                <i className="fas fa-sync mr-1"></i>
                刷新
              </Button>
            </div>

            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      股票代码
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      股票名称
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                      持仓数量
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                      成本价
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                      当前价
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                      盈亏
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                      盈亏比例
                    </th>
                    <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                      操作
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {positions.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="px-4 py-8 text-center text-gray-500">
                        暂无持仓
                      </td>
                    </tr>
                  ) : (
                    positions.map((position, index) => (
                      <Fragment key={position.stock_code + '_' + index}>
                        <tr className="hover:bg-gray-50">
                          <td className="px-4 py-3 text-sm font-medium text-gray-900">
                            {position.stock_code}
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-900">
                            {position.stock_name}
                          </td>
                          <td className="px-4 py-3 text-sm text-right text-gray-900">
                            {position.qty || position.quantity || 0}
                          </td>
                          <td className="px-4 py-3 text-sm text-right text-gray-900">
                            {formatPrice(position.cost_price)}
                          </td>
                          <td className="px-4 py-3 text-sm text-right text-gray-900">
                            {formatPrice(position.current_price || 0)}
                          </td>
                          <td
                            className={`px-4 py-3 text-sm text-right font-medium ${
                              (position.pl_val || 0) >= 0
                                ? "text-red-600"
                                : "text-green-600"
                            }`}
                          >
                            {formatPrice(position.pl_val || 0)}
                          </td>
                          <td
                            className={`px-4 py-3 text-sm text-right font-medium ${
                              (position.pl_ratio || 0) >= 0
                                ? "text-red-600"
                                : "text-green-600"
                            }`}
                          >
                            {formatPercent(position.pl_ratio || 0)}
                          </td>
                          <td className="px-4 py-3 text-center">
                            <div className="flex items-center justify-center gap-1">
                              <a
                                href={`/stock-detail?code=${position.stock_code}`}
                                className="text-[10px] px-1.5 py-1 rounded bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors font-medium"
                              >
                                🔍
                              </a>
                              <button
                                onClick={() => setTakeProfitTarget(position)}
                                className="text-[10px] px-1.5 py-1 rounded bg-amber-50 text-amber-700 hover:bg-amber-100 transition-colors font-medium"
                                title="设置止盈"
                              >
                                🎯
                              </button>
                              <button
                                onClick={async () => {
                                  const sellSignal = {
                                    stock_code: position.stock_code,
                                    stock_name: position.stock_name,
                                    signal_type: "sell",
                                    signal_price: position.current_price || 0,
                                    id: 0,
                                  } as TradeSignal;
                                  setSelectedStock(sellSignal);
                                  setTradeQuantity(position.qty || position.quantity || 0);
                                  setTradeType("sell");
                                  // 内联 pre-check + 弹窗（避免 React 闭包问题）
                                  setCheckingTrade(true);
                                  setPreCheckResult(null);
                                  try {
                                    const res = await fetch(`/api/pre-trade-check/${encodeURIComponent(position.stock_code)}`);
                                    const json = await res.json();
                                    if (json.success && json.data) setPreCheckResult(json.data);
                                  } catch { setPreCheckResult(null); }
                                  finally { setCheckingTrade(false); setShowConfirmModal(true); }
                                }}
                                className="text-[10px] px-1.5 py-1 rounded bg-green-50 text-green-700 hover:bg-green-100 transition-colors font-medium"
                                title="快速卖出"
                              >
                                📤卖出
                              </button>
                              <button
                                onClick={() =>
                                  setExpandedStock(
                                    expandedStock === position.stock_code
                                      ? null
                                      : position.stock_code
                                  )
                                }
                                className="text-xs text-blue-600 hover:text-blue-800 px-1.5 py-1 rounded hover:bg-blue-50 transition-colors"
                              >
                                {expandedStock === position.stock_code ? "收起" : "分仓"}
                              </button>
                            </div>
                          </td>
                        </tr>
                        {expandedStock === position.stock_code && (
                          <tr>
                            <td colSpan={8} className="px-4 py-3 bg-gray-50">
                              <LotDetailPanel
                                stockCode={position.stock_code}
                                currentPrice={position.current_price || 0}
                                onSetTakeProfit={() => setTakeProfitTarget(position)}
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
        </div>
      </div>

      {/* 交易确认对话框 */}
      <Modal
        isOpen={showConfirmModal}
        onClose={() => setShowConfirmModal(false)}
        title="交易确认"
      >
        <div className="space-y-4 mb-6">
          {/* 系统检查结果 */}
          {preCheckResult && (
            <div
              className={`rounded-lg p-4 border ${
                preCheckResult.verdict === "STOP"
                  ? "bg-red-50 border-red-300"
                  : preCheckResult.verdict === "CAUTION"
                  ? "bg-yellow-50 border-yellow-300"
                  : "bg-green-50 border-green-300"
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="text-lg">
                  {preCheckResult.verdict === "STOP"
                    ? "🚫"
                    : preCheckResult.verdict === "CAUTION"
                    ? "⚠️"
                    : "✅"}
                </span>
                <span
                  className={`font-bold ${
                    preCheckResult.verdict === "STOP"
                      ? "text-red-700"
                      : preCheckResult.verdict === "CAUTION"
                      ? "text-yellow-700"
                      : "text-green-700"
                  }`}
                >
                  系统检查：{preCheckResult.verdict} (评分{" "}
                  {preCheckResult.score})
                </span>
              </div>
              <p
                className={`text-sm ${
                  preCheckResult.verdict === "STOP"
                    ? "text-red-600"
                    : preCheckResult.verdict === "CAUTION"
                    ? "text-yellow-600"
                    : "text-green-600"
                }`}
              >
                {preCheckResult.verdict_reason}
              </p>

              {/* 检查项 */}
              {preCheckResult.checks?.length > 0 && (
                <div className="mt-3 space-y-1">
                  {preCheckResult.checks.map((c: any, i: number) => (
                    <div
                      key={i}
                      className="flex items-center justify-between text-xs"
                    >
                      <span className="text-gray-700">
                        {c.status === "GOOD"
                          ? "✅"
                          : c.status === "DANGER"
                          ? "❌"
                          : c.status === "WARNING"
                          ? "⚠️"
                          : "⚪"}{" "}
                        {c.name}
                      </span>
                      <span className="text-gray-500">{c.detail}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* 预警 */}
              {preCheckResult.warnings?.length > 0 && (
                <div className="mt-2 pt-2 border-t border-red-200">
                  {preCheckResult.warnings.map((w: string, i: number) => (
                    <div key={i} className="text-xs text-red-600">
                      {w}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 交易信息 */}
          <div className="space-y-2">
            <div className="flex justify-between">
              <span className="text-gray-600">股票代码:</span>
              <span className="font-medium">
                {selectedStock?.stock_code}
                {preCheckResult?.stock_name
                  ? ` (${preCheckResult.stock_name})`
                  : ""}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">交易类型:</span>
              <span
                className={`font-medium ${
                  tradeType === "buy" ? "text-red-600" : "text-green-600"
                }`}
              >
                {tradeType === "buy" ? "买入" : "卖出"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">交易数量:</span>
              <span className="font-medium">{tradeQuantity} 股</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">交易价格:</span>
              <span className="font-medium">
                {tradePrice ? formatPrice(tradePrice) : "市价"}
              </span>
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-3">
          <button
            onClick={() => setShowConfirmModal(false)}
            className="px-4 py-2 text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200"
          >
            取消
          </button>
          <button
            onClick={handleExecuteTrade}
            className={`px-4 py-2 text-white rounded-md ${
              preCheckResult?.verdict === "STOP"
                ? "bg-red-600 hover:bg-red-700"
                : "bg-blue-600 hover:bg-blue-700"
            }`}
          >
            {preCheckResult?.verdict === "STOP"
              ? "⚠️ 忽略警告，强制执行"
              : "确认交易"}
          </button>
        </div>
      </Modal>

      {/* 止盈设置对话框 */}
      {takeProfitTarget && (
        <TakeProfitSetup
          isOpen={!!takeProfitTarget}
          onClose={() => setTakeProfitTarget(null)}
          stockCode={takeProfitTarget.stock_code}
          stockName={takeProfitTarget.stock_name}
          currentPrice={takeProfitTarget.current_price || 0}
        />
      )}
    </div>
  );
}
