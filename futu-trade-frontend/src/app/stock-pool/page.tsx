// 股票池管理页面

"use client";

import { useState, useEffect } from "react";
import { Card, Button, Modal } from "@/components/common";
import { useStockPool } from "./hooks/useStockPool";
import { PlateTable } from "./components/PlateTable";
import { useToast } from "@/components/common/Toast";
import type { Plate, Stock } from "@/types";

export default function StockPoolPage() {
  const {
    plates,
    stocks,
    loading,
    error,
    loadPlates,
    loadStocks,
    addPlate,
    deletePlate,
    addStocks,
    deleteStock,
    initializeData,
    refreshData,
    resetData,
    initProgress,
    platesTotalCount,
    stocksTotalCount,
  } = useStockPool();

  const { showToast } = useToast();

  // 表单状态
  const [plateCode, setPlateCode] = useState("");
  const [stockCodes, setStockCodes] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  // 模态框状态
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{
    type: "plate" | "stock";
    id: number;
    name: string;
  } | null>(null);

  const [showInitModal, setShowInitModal] = useState(false);
  const [showResetModal, setShowResetModal] = useState(false);
  const [initOptions, setInitOptions] = useState({
    initPlates: true,
    initStocks: true,
    initKline: false,
    initHotStocks: false,
  });

  // 加载数据
  useEffect(() => {
    loadPlates();
    loadStocks(1, 200); // 加载更多股票以显示完整统计（后端限制最大200）
  }, [loadPlates, loadStocks]);

  // 处理添加板块
  const handleAddPlate = async () => {
    if (!plateCode.trim()) {
      showToast("warning", "提示", "请输入板块代码");
      return;
    }

    try {
      await addPlate(plateCode.trim());
      showToast("success", "成功", "板块添加成功");
      setPlateCode("");
      loadPlates();
    } catch (err: any) {
      showToast("error", "错误", err.message || "添加板块失败");
    }
  };

  // 处理删除板块
  const handleDeletePlate = (plateId: number, plateName: string) => {
    setDeleteTarget({ type: "plate", id: plateId, name: plateName });
    setShowDeleteModal(true);
  };

  // 确认删除
  const confirmDelete = async () => {
    if (!deleteTarget) return;

    setShowDeleteModal(false);

    try {
      if (deleteTarget.type === "plate") {
        await deletePlate(deleteTarget.id);
        showToast("success", "成功", "板块删除成功");
        loadPlates();
      } else {
        await deleteStock(deleteTarget.id);
        showToast("success", "成功", "股票删除成功");
        loadStocks();
      }
    } catch (err: any) {
      showToast("error", "错误", err.message || "删除失败");
    }

    setDeleteTarget(null);
  };

  // 处理添加股票
  const handleAddStocks = async () => {
    if (!stockCodes.trim()) {
      showToast("warning", "提示", "请输入股票代码");
      return;
    }

    const codes = stockCodes
      .split(",")
      .map((code) => code.trim())
      .filter((code) => code);

    if (codes.length === 0) {
      showToast("warning", "提示", "请输入有效的股票代码");
      return;
    }

    try {
      await addStocks(codes);
      showToast("success", "成功", `成功添加 ${codes.length} 只股票`);
      setStockCodes("");
      loadStocks();
    } catch (err: any) {
      showToast("error", "错误", err.message || "添加股票失败");
    }
  };

  // 处理删除股票
  const handleDeleteStock = (stockId: number, stockName: string) => {
    setDeleteTarget({ type: "stock", id: stockId, name: stockName });
    setShowDeleteModal(true);
  };

  // 处理初始化数据
  const handleInitialize = async () => {
    setShowInitModal(false);

    try {
      await initializeData(initOptions);
      showToast("success", "成功", "数据初始化完成");
      loadPlates();
      loadStocks();
    } catch (err: any) {
      showToast("error", "错误", err.message || "初始化失败");
    }
  };

  // 处理更新数据
  const handleRefreshData = async () => {
    try {
      await refreshData();
      showToast("success", "成功", "数据更新完成");
      loadPlates();
      loadStocks();
    } catch (err: any) {
      showToast("error", "错误", err.message || "更新失败");
    }
  };

  // 处理重置数据
  const handleResetData = async () => {
    setShowResetModal(false);

    try {
      await resetData();
      showToast("success", "成功", "数据重置完成");
      loadPlates();
      loadStocks();
    } catch (err: any) {
      showToast("error", "错误", err.message || "重置失败");
    }
  };

  // 筛选股票
  const filteredStocks = stocks.filter((stock) => {
    if (!searchQuery) return true;
    const query = searchQuery.toLowerCase();
    return (
      stock.code.toLowerCase().includes(query) ||
      stock.name.toLowerCase().includes(query)
    );
  });

  // 统计信息
  const stats = {
    totalPlates: platesTotalCount || plates.length,
    totalStocks: stocksTotalCount || stocks.length,
    manualStocks: stocks.filter((s) => s.is_manual).length,
    plateStocks: stocks.filter((s) => !s.is_manual).length,
  };

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      {/* 页面标题 */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <i className="fas fa-chart-pie text-blue-600"></i>
          股票池管理
        </h1>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <Card>
          <div className="text-center">
            <h3 className="text-3xl font-bold text-blue-600">{stats.totalPlates}</h3>
            <p className="text-gray-600 mt-1">目标板块数</p>
          </div>
        </Card>

        <Card>
          <div className="text-center">
            <h3 className="text-3xl font-bold text-green-600">{stats.totalStocks}</h3>
            <p className="text-gray-600 mt-1">目标股票数</p>
          </div>
        </Card>

        <Card>
          <div className="text-center">
            <h3 className="text-3xl font-bold text-yellow-600">{stats.manualStocks}</h3>
            <p className="text-gray-600 mt-1">自选股</p>
          </div>
        </Card>

        <Card>
          <div className="text-center">
            <h3 className="text-3xl font-bold text-purple-600">{stats.plateStocks}</h3>
            <p className="text-gray-600 mt-1">板块股票</p>
          </div>
        </Card>
      </div>

      {/* 主要内容区 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* 左侧：板块管理 */}
        <Card>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-medium text-gray-900 flex items-center gap-2">
              <i className="fas fa-layer-group text-blue-600"></i>
              板块管理
            </h2>
            <div className="flex gap-2">
              <Button
                variant="primary"
                size="sm"
                onClick={handleRefreshData}
                className="flex items-center gap-1"
              >
                <i className="fas fa-sync-alt"></i>
                更新数据
              </Button>
              <Button
                variant="danger"
                size="sm"
                onClick={() => setShowResetModal(true)}
                className="flex items-center gap-1"
              >
                <i className="fas fa-redo"></i>
                重置
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => loadPlates()}
                className="flex items-center gap-1"
              >
                <i className="fas fa-sync-alt"></i>
                刷新
              </Button>
            </div>
          </div>

          {/* 添加板块 */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              添加新板块
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={plateCode}
                onChange={(e) => setPlateCode(e.target.value)}
                onKeyPress={(e) => e.key === "Enter" && handleAddPlate()}
                placeholder="输入板块代码 (如: BK1027)"
                className="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <Button onClick={handleAddPlate} className="flex items-center gap-1">
                <i className="fas fa-plus"></i>
                添加
              </Button>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              支持港股(BK)和美股(SZ)板块代码
            </p>
          </div>

          {/* 板块表格 */}
          <PlateTable
            plates={plates}
            loading={loading}
            onDelete={handleDeletePlate}
            onRefresh={() => loadPlates()}
          />
        </Card>

        {/* 右侧：股票管理 */}
        <Card>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-medium text-gray-900 flex items-center gap-2">
              <i className="fas fa-list-alt text-green-600"></i>
              股票管理
            </h2>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => loadStocks()}
              className="flex items-center gap-1"
            >
              <i className="fas fa-sync-alt"></i>
              刷新
            </Button>
          </div>

          {/* 搜索和添加股票 */}
          <div className="space-y-3 mb-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                搜索股票
              </label>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="输入股票代码或名称"
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                添加股票
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={stockCodes}
                  onChange={(e) => setStockCodes(e.target.value)}
                  onKeyPress={(e) => e.key === "Enter" && handleAddStocks()}
                  placeholder="输入股票代码，多个用逗号分隔"
                  className="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <Button onClick={handleAddStocks} className="flex items-center gap-1">
                  <i className="fas fa-plus"></i>
                  添加
                </Button>
              </div>
            </div>
          </div>

          {/* 股票表格 */}
          <div className="overflow-x-auto max-h-96 overflow-y-auto border border-gray-200 rounded-lg">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    代码
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    名称
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    市场
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {loading ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-gray-500">
                      <i className="fas fa-spinner fa-spin mr-2"></i>
                      加载中...
                    </td>
                  </tr>
                ) : filteredStocks.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-gray-500">
                      暂无股票数据
                    </td>
                  </tr>
                ) : (
                  filteredStocks.map((stock) => (
                    <tr key={stock.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm text-gray-900">
                        {stock.code}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-900">
                        {stock.name}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-900">
                        {stock.market}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        <Button
                          variant="danger"
                          size="sm"
                          onClick={() => handleDeleteStock(stock.id, stock.name)}
                          className="flex items-center gap-1"
                        >
                          <i className="fas fa-trash"></i>
                          删除
                        </Button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      {/* 删除确认对话框 */}
      <Modal
        isOpen={showDeleteModal}
        onClose={() => setShowDeleteModal(false)}
        title="确认删除"
      >
        <p className="text-gray-700 mb-6">
          确定要删除{deleteTarget?.type === "plate" ? "板块" : "股票"} "
          {deleteTarget?.name}" 吗？
        </p>

        <div className="flex justify-end gap-3">
          <button
            onClick={() => setShowDeleteModal(false)}
            className="px-4 py-2 text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200"
          >
            取消
          </button>
          <button
            onClick={confirmDelete}
            className="px-4 py-2 text-white bg-red-600 rounded-md hover:bg-red-700"
          >
            确认删除
          </button>
        </div>
      </Modal>

      {/* 初始化数据对话框 */}
      <Modal
        isOpen={showInitModal}
        onClose={() => setShowInitModal(false)}
        title="初始化股票池数据"
      >
        <div className="space-y-4 mb-6">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={initOptions.initPlates}
              onChange={(e) =>
                setInitOptions({ ...initOptions, initPlates: e.target.checked })
              }
              className="w-4 h-4 text-blue-600 border-gray-300 rounded"
            />
            <span className="text-gray-700">初始化板块数据</span>
          </label>

          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={initOptions.initStocks}
              onChange={(e) =>
                setInitOptions({ ...initOptions, initStocks: e.target.checked })
              }
              className="w-4 h-4 text-blue-600 border-gray-300 rounded"
            />
            <span className="text-gray-700">初始化股票数据</span>
          </label>

          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={initOptions.initKline}
              onChange={(e) =>
                setInitOptions({ ...initOptions, initKline: e.target.checked })
              }
              className="w-4 h-4 text-blue-600 border-gray-300 rounded"
            />
            <span className="text-gray-700">初始化K线数据</span>
          </label>

          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={initOptions.initHotStocks}
              onChange={(e) =>
                setInitOptions({ ...initOptions, initHotStocks: e.target.checked })
              }
              className="w-4 h-4 text-blue-600 border-gray-300 rounded"
            />
            <span className="text-gray-700">初始化热门股数据</span>
          </label>
        </div>

        <div className="flex justify-end gap-3">
          <button
            onClick={() => setShowInitModal(false)}
            className="px-4 py-2 text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200"
          >
            取消
          </button>
          <button
            onClick={handleInitialize}
            className="px-4 py-2 text-white bg-blue-600 rounded-md hover:bg-blue-700"
          >
            开始初始化
          </button>
        </div>
      </Modal>

      {/* 重置确认对话框 */}
      <Modal
        isOpen={showResetModal}
        onClose={() => setShowResetModal(false)}
        title="确认重置数据"
      >
        <div className="space-y-4">
          <p className="text-gray-700">
            <strong className="text-red-600">警告：</strong>
            重置操作将清空所有板块和股票数据，包括手动添加的数据和交易信号。
          </p>
          <p className="text-gray-700">
            此操作不可恢复，确定要继续吗？
          </p>
        </div>

        <div className="flex justify-end gap-3 mt-6">
          <button
            onClick={() => setShowResetModal(false)}
            className="px-4 py-2 text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200"
          >
            取消
          </button>
          <button
            onClick={handleResetData}
            className="px-4 py-2 text-white bg-red-600 rounded-md hover:bg-red-700"
          >
            确认重置
          </button>
        </div>
      </Modal>
    </div>
  );
}
