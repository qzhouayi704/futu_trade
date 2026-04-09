// 未订阅股票页面

"use client";

import { useState, useEffect } from "react";
import { Card, Button } from "@/components/common";
import { stockApi } from "@/lib/api";
import { useToast } from "@/components/common/Toast";
import { formatPrice, formatPercent, formatVolume } from "@/lib/utils";

interface UnsubscribedStock {
  id: number;
  code: string;
  name: string;
  market: string;
  plate_name?: string;
  plate_names?: string[];
  is_active: boolean | null;
  turnover_rate: number | null;
  turnover_amount: number | null;
  activity_check_date: string | null;
  inactive_reason: string | null;
}

interface StatsData {
  subscribed_count: number;
  total_in_pool: number;
  unsubscribed_count: number;
  active_count: number;
  inactive_count: number;
  unchecked_count: number;
  market_counts: Record<string, number>;
}

export default function UnsubscribedStocksPage() {
  const { showToast } = useToast();

  const [stocks, setStocks] = useState<UnsubscribedStock[]>([]);
  const [loading, setLoading] = useState(true);
  const [resetting, setResetting] = useState(false);
  const [stats, setStats] = useState<StatsData | null>(null);
  const [marketFilter, setMarketFilter] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [pageSize] = useState(50);

  // 加载未订阅股票数据
  const loadUnsubscribedStocks = async (page: number = 1) => {
    setLoading(true);

    try {
      const response = await stockApi.getUnsubscribedStocks({
        market: marketFilter || undefined,
        search: searchKeyword || undefined,
        page,
        limit: pageSize,
      });

      if (response.success && response.data) {
        setStocks(response.data);

        // 从 meta 对象中获取分页信息
        if (response.meta) {
          setCurrentPage(response.meta.page || 1);
          setTotalPages(response.meta.total_pages || 1);
        } else {
          setCurrentPage(1);
          setTotalPages(1);
        }

        // 设置统计信息
        if (response.extra) {
          setStats(response.extra as StatsData);
        }
      } else {
        throw new Error(response.message || "加载未订阅股票失败");
      }
    } catch (err: any) {
      showToast("error", "错误", err.message || "加载未订阅股票失败");
    } finally {
      setLoading(false);
    }
  };

  // 重置活跃度筛选记录
  const handleResetActivity = async () => {
    if (!confirm("确定要清空今日活跃度筛选记录吗？系统将立即重新筛选并更新订阅列表。")) {
      return;
    }

    setResetting(true);
    try {
      const response = await stockApi.resetActivityRecords();
      if (response.success) {
        const deleted = response.data?.deleted_count || 0;
        showToast("success", "成功", `已清空 ${deleted} 条记录，正在后台重新筛选活跃度并更新订阅`);
        // 延迟刷新，给后台筛选和重新订阅足够的时间
        setTimeout(() => {
          loadUnsubscribedStocks(1);
        }, 5000);
      } else {
        throw new Error(response.message || "重置失败");
      }
    } catch (err: any) {
      showToast("error", "错误", err.message || "重置活跃度记录失败");
    } finally {
      setResetting(false);
    }
  };

  // 初始化加载
  useEffect(() => {
    loadUnsubscribedStocks(1);
  }, [marketFilter, searchKeyword]);

  // 获取活跃度状态标签
  const getActivityBadge = (stock: UnsubscribedStock) => {
    if (stock.is_active === null) {
      return (
        <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
          未检查
        </span>
      );
    } else if (stock.is_active) {
      return (
        <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">
          <i className="fas fa-check-circle mr-1"></i>
          活跃
        </span>
      );
    } else {
      return (
        <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-red-100 text-red-800">
          <i className="fas fa-times-circle mr-1"></i>
          不活跃
        </span>
      );
    }
  };

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <i className="fas fa-eye-slash text-gray-600"></i>
          未订阅股票
        </h1>

        <div className="flex items-center gap-2">
          <Button
            onClick={handleResetActivity}
            loading={resetting}
            variant="secondary"
            className="flex items-center gap-1 text-orange-600 border-orange-300 hover:bg-orange-50"
          >
            <i className="fas fa-redo"></i>
            重新筛选活跃度
          </Button>

          <Button
            onClick={() => loadUnsubscribedStocks(currentPage)}
            loading={loading}
            className="flex items-center gap-1"
          >
            <i className="fas fa-sync-alt"></i>
            刷新数据
          </Button>
        </div>
      </div>

      {/* 统计卡片 */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
          <Card className="bg-gradient-to-br from-blue-500 to-blue-600 text-white">
            <div className="text-center">
              <div className="text-sm opacity-90 mb-1">已订阅股票</div>
              <div className="text-3xl font-bold">{stats.subscribed_count}</div>
            </div>
          </Card>

          <Card className="bg-gradient-to-br from-orange-500 to-red-500 text-white">
            <div className="text-center">
              <div className="text-sm opacity-90 mb-1">未订阅股票</div>
              <div className="text-3xl font-bold">{stats.unsubscribed_count}</div>
            </div>
          </Card>

          <Card>
            <div className="text-center">
              <div className="text-sm text-gray-600 mb-1">不活跃股票</div>
              <div className="text-3xl font-bold text-red-600">
                {stats.inactive_count}
              </div>
            </div>
          </Card>

          <Card>
            <div className="text-center">
              <div className="text-sm text-gray-600 mb-1">股票池总数</div>
              <div className="text-3xl font-bold text-gray-900">
                {stats.total_in_pool}
              </div>
            </div>
          </Card>
        </div>
      )}

      {/* 提示信息 */}
      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-6 flex items-start gap-3">
        <i className="fas fa-info-circle text-yellow-600 mt-0.5"></i>
        <div className="text-sm text-yellow-800">
          <p className="font-medium mb-1">关于未订阅股票</p>
          <p>
            这些股票在股票池中但未被订阅行情，主要原因是不满足活跃度筛选条件（换手率 &lt; 0.3% 或 成交额 &lt; 1000万）。
            你可以在配置页面调整活跃度筛选参数，或者增加市场订阅限制来订阅更多股票。
          </p>
        </div>
      </div>

      {/* 主要内容 */}
      <Card>
        {/* 筛选栏 */}
        <div className="flex flex-col gap-4 mb-6">
          {/* 第一行：搜索框 */}
          <div className="flex items-center gap-3">
            <div className="flex-1 relative">
              <input
                type="text"
                value={searchKeyword}
                onChange={(e) => {
                  setSearchKeyword(e.target.value);
                  setCurrentPage(1);
                }}
                placeholder="搜索股票代码或名称..."
                className="w-full px-4 py-2 pl-10 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <i className="fas fa-search absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"></i>
              {searchKeyword && (
                <button
                  onClick={() => {
                    setSearchKeyword("");
                    setCurrentPage(1);
                  }}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                >
                  <i className="fas fa-times"></i>
                </button>
              )}
            </div>
          </div>

          {/* 第二行：市场筛选和统计信息 */}
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div className="flex items-center gap-3">
              <label className="text-sm font-medium text-gray-700">市场筛选:</label>
              <select
                value={marketFilter}
                onChange={(e) => {
                  setMarketFilter(e.target.value);
                  setCurrentPage(1);
                }}
                className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">所有市场</option>
                <option value="HK">港股</option>
                <option value="US">美股</option>
              </select>
              {(marketFilter || searchKeyword) && (
                <Button
                  variant="secondary"
                  onClick={() => {
                    setMarketFilter("");
                    setSearchKeyword("");
                    setCurrentPage(1);
                  }}
                >
                  清除筛选
                </Button>
              )}
            </div>

            {stats && (
              <div className="text-sm text-gray-600">
                显示 {(currentPage - 1) * pageSize + 1} - {Math.min(currentPage * pageSize, stats.unsubscribed_count)} / 共 {stats.unsubscribed_count} 只
              </div>
            )}
          </div>
        </div>

        {/* 股票表格 */}
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  #
                </th>
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
                  所属板块
                </th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                  活跃度状态
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                  换手率
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                  成交额
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  未订阅原因
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {loading ? (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-gray-500">
                    <i className="fas fa-spinner fa-spin mr-2"></i>
                    加载中...
                  </td>
                </tr>
              ) : stocks.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-gray-500">
                    <i className="fas fa-check-circle text-green-600 text-2xl mb-2"></i>
                    <p>太好了！所有股票都已订阅</p>
                  </td>
                </tr>
              ) : (
                stocks.map((stock, index) => (
                  <tr key={stock.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm text-gray-900">
                      {(currentPage - 1) * pageSize + index + 1}
                    </td>
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">
                      {stock.code}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-900">
                      {stock.name}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-900">
                      <span
                        className={`inline-flex items-center px-2 py-1 rounded text-xs font-medium ${
                          stock.market === "HK"
                            ? "bg-blue-100 text-blue-800"
                            : "bg-purple-100 text-purple-800"
                        }`}
                      >
                        {stock.market}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-900">
                      {stock.plate_names && stock.plate_names.length > 0
                        ? stock.plate_names.join(", ")
                        : stock.plate_name || "-"}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {getActivityBadge(stock)}
                    </td>
                    <td className="px-4 py-3 text-sm text-right text-gray-900">
                      {stock.turnover_rate !== null
                        ? formatPercent(stock.turnover_rate)
                        : "-"}
                    </td>
                    <td className="px-4 py-3 text-sm text-right text-gray-900">
                      {stock.turnover_amount !== null
                        ? formatVolume(stock.turnover_amount)
                        : "-"}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {stock.inactive_reason || "-"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* 分页 */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between mt-6 pt-4 border-t border-gray-200">
            <Button
              variant="secondary"
              onClick={() => loadUnsubscribedStocks(currentPage - 1)}
              disabled={currentPage === 1 || loading}
            >
              <i className="fas fa-chevron-left mr-1"></i>
              上一页
            </Button>

            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-600">
                第 {currentPage} / {totalPages} 页
              </span>
            </div>

            <Button
              variant="secondary"
              onClick={() => loadUnsubscribedStocks(currentPage + 1)}
              disabled={currentPage === totalPages || loading}
            >
              下一页
              <i className="fas fa-chevron-right ml-1"></i>
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
