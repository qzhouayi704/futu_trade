// 股票池监控页面

"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { Card, Button, Table } from "@/components/common";
import { stockApi } from "@/lib/api";
import { useSocket } from "@/lib/socket";
import { useToast } from "@/components/common/Toast";
import { formatPrice, formatPercent, formatVolume, formatTime } from "@/lib/utils";
import type { TopHotStock, DataReadyStatus } from "@/types";
import DetailDrawer from "./components/DetailDrawer";

interface StockDisplay extends TopHotStock {
  // 实时报价覆盖字段
  last_price_rt?: number;
  change_rate_rt?: number;
  turnover_rate_rt?: number;
  volume_rt?: number;
  turnover_rt?: number;
}

export default function StockPoolMonitorPage() {
  const { socket, isConnected } = useSocket();
  const { showToast } = useToast();

  const [stocks, setStocks] = useState<StockDisplay[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdateTime, setLastUpdateTime] = useState<Date | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [marketFilter, setMarketFilter] = useState("");
  const [dataReadyStatus, setDataReadyStatus] = useState<DataReadyStatus | null>(null);
  const [activeMarkets, setActiveMarkets] = useState<string[]>([]);
  const [selectedStock, setSelectedStock] = useState<StockDisplay | null>(null);

  // 加载股票数据（从 Top Hot API 获取热度排序的股票）
  const loadStocks = useCallback(async () => {
    setLoading(true);

    try {
      const params: { market?: string; search?: string } = {};
      if (marketFilter) params.market = marketFilter;
      if (searchQuery) params.search = searchQuery;

      const response = await stockApi.getTopHotStocks(params);

      if (response.success && response.data) {
        setStocks(response.data.stocks || []);
        setDataReadyStatus(response.data.data_ready_status || null);
        setActiveMarkets(response.data.active_markets || []);
        setLastUpdateTime(new Date());
      } else {
        throw new Error(response.message || "加载股票数据失败");
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "加载股票数据失败";
      showToast("error", "错误", message);
    } finally {
      setLoading(false);
    }
  }, [marketFilter, searchQuery, showToast]);

  // 初始化加载 & 筛选条件变化时重新加载
  useEffect(() => {
    loadStocks();
  }, [loadStocks]);

  // 监听实时报价更新
  useEffect(() => {
    if (!socket) return;

    const handleQuotesUpdate = (data: unknown) => {
      const quotesData = data as { quotes?: unknown[] };
      if (quotesData.quotes) {
        setStocks((prevStocks) => {
          const quotesMap = new Map(
            quotesData.quotes!
              .filter((q: unknown) => {
                const quote = q as Record<string, unknown>;
                return quote?.code;
              })
              .map((q: unknown) => {
                const quote = q as Record<string, unknown>;
                return [quote.code as string, quote];
              })
          );

          return prevStocks.map((stock) => {
            const quote = quotesMap.get(stock.code);
            if (quote) {
              return {
                ...stock,
                last_price_rt: (quote.last_price as number) || (quote.cur_price as number),
                change_rate_rt: (quote.change_rate as number) || (quote.change_percent as number),
                turnover_rate_rt: quote.turnover_rate as number | undefined,
                volume_rt: quote.volume as number | undefined,
                turnover_rt: (quote.turnover as number) || (quote.amount as number),
              };
            }
            return stock;
          });
        });

        setLastUpdateTime(new Date());
      }
    };

    socket.on("quotes_update", handleQuotesUpdate);

    return () => {
      socket.off("quotes_update", handleQuotesUpdate);
    };
  }, [socket]);

  // 获取显示用的价格（优先使用实时数据）
  const getDisplayPrice = (stock: StockDisplay) => stock.last_price_rt ?? stock.cur_price;
  const getDisplayChangeRate = (stock: StockDisplay) => stock.change_rate_rt ?? stock.change_rate;
  const getDisplayTurnoverRate = (stock: StockDisplay) => stock.turnover_rate_rt ?? stock.turnover_rate;
  const getDisplayVolume = (stock: StockDisplay) => stock.volume_rt ?? stock.volume;
  const getDisplayTurnover = (stock: StockDisplay) => stock.turnover_rt ?? stock.turnover;

  // 统计信息
  const stats = useMemo(() => ({
    totalCount: stocks.length,
  }), [stocks]);

  // 行点击：展开/关闭 Detail_Panel
  const handleRowClick = useCallback((stock: StockDisplay) => {
    if (selectedStock?.code === stock.code) {
      setSelectedStock(null);
      return;
    }
    setSelectedStock(stock);
  }, [selectedStock]);

  const closePanel = useCallback(() => {
    setSelectedStock(null);
  }, []);

  // 定义表格列
  const columns = useMemo(() => [
    {
      key: "index",
      title: "#",
      width: "60px",
      render: (_: unknown, __: unknown, index: number) => index + 1,
    },
    {
      key: "code",
      title: "代码",
      width: "120px",
      sortable: true,
      render: (value: string) => (
        <span className="font-medium">{value}</span>
      ),
    },
    {
      key: "name",
      title: "名称",
      width: "150px",
      sortable: true,
      render: (value: string, record: StockDisplay) => (
        <span className="flex items-center gap-1">
          {value}
          {record.is_position && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-100 text-purple-700" title="持仓股票">
              持仓
            </span>
          )}
        </span>
      ),
    },
    {
      key: "market",
      title: "市场",
      width: "80px",
      sortable: true,
    },
    {
      key: "cur_price",
      title: "当前价",
      align: "right" as const,
      width: "100px",
      sortable: true,
      sorter: (a: StockDisplay, b: StockDisplay) => getDisplayPrice(a) - getDisplayPrice(b),
      render: (_: unknown, record: StockDisplay) => {
        const price = getDisplayPrice(record);
        const changeRate = getDisplayChangeRate(record);
        const colorClass = changeRate > 0
          ? "text-red-600"
          : changeRate < 0
            ? "text-green-600"
            : "text-gray-900";

        return (
          <span className={`font-medium ${colorClass}`}>
            {price ? formatPrice(price) : "-"}
          </span>
        );
      },
    },
    {
      key: "change_rate",
      title: "涨跌幅",
      align: "right" as const,
      width: "100px",
      sortable: true,
      sorter: (a: StockDisplay, b: StockDisplay) =>
        getDisplayChangeRate(a) - getDisplayChangeRate(b),
      render: (_: unknown, record: StockDisplay) => {
        const value = getDisplayChangeRate(record);
        if (!value) return "-";
        const colorClass = value > 0
          ? "text-red-600"
          : value < 0
            ? "text-green-600"
            : "text-gray-900";

        return (
          <span className={`font-medium ${colorClass}`}>
            {value > 0 ? "+" : ""}{formatPercent(value)}
          </span>
        );
      },
    },
    {
      key: "turnover_rate",
      title: "换手率",
      align: "right" as const,
      width: "100px",
      sortable: true,
      sorter: (a: StockDisplay, b: StockDisplay) =>
        getDisplayTurnoverRate(a) - getDisplayTurnoverRate(b),
      render: (_: unknown, record: StockDisplay) => {
        const value = getDisplayTurnoverRate(record);
        return value ? formatPercent(value) : "-";
      },
    },
    {
      key: "turnover",
      title: "成交额",
      align: "right" as const,
      width: "120px",
      sortable: true,
      sorter: (a: StockDisplay, b: StockDisplay) =>
        getDisplayTurnover(a) - getDisplayTurnover(b),
      render: (_: unknown, record: StockDisplay) => {
        const value = getDisplayTurnover(record);
        return value ? formatVolume(value) : "-";
      },
    },
    {
      key: "heat_score",
      title: "热度分",
      align: "right" as const,
      width: "100px",
      sortable: true,
      sorter: (a: StockDisplay, b: StockDisplay) =>
        (a.heat_score || 0) - (b.heat_score || 0),
      render: (value: number | undefined) => {
        if (!value) return "-";

        return (
          <span
            className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${value >= 80
                ? "bg-red-100 text-red-800"
                : value >= 60
                  ? "bg-orange-100 text-orange-800"
                  : "bg-gray-100 text-gray-800"
              }`}
          >
            {value.toFixed(1)}
          </span>
        );
      },
    },
    {
      key: "capital_flow_summary",
      title: "主力净流入",
      align: "right" as const,
      width: "120px",
      sortable: true,
      sorter: (a: StockDisplay, b: StockDisplay) =>
        (a.capital_flow_summary?.main_net_inflow || 0) - (b.capital_flow_summary?.main_net_inflow || 0),
      render: (_: unknown, record: StockDisplay) => {
        const summary = record.capital_flow_summary;
        if (!summary) return "-";
        const value = summary.main_net_inflow;
        const colorClass = value > 0 ? "text-red-600" : value < 0 ? "text-green-600" : "text-gray-500";
        const display = Math.abs(value) >= 10000
          ? `${(value / 10000).toFixed(1)}万`
          : value.toFixed(0);
        return <span className={`font-medium ${colorClass}`}>{value > 0 ? "+" : ""}{display}</span>;
      },
    },
    {
      key: "big_order_ratio",
      title: "大单买卖比",
      align: "right" as const,
      width: "100px",
      sortable: true,
      sorter: (a: StockDisplay, b: StockDisplay) =>
        (a.capital_flow_summary?.big_order_buy_ratio || 0) - (b.capital_flow_summary?.big_order_buy_ratio || 0),
      render: (_: unknown, record: StockDisplay) => {
        const summary = record.capital_flow_summary;
        if (!summary) return "-";
        const ratio = summary.big_order_buy_ratio;
        const pct = (ratio * 100).toFixed(1);
        const colorClass = ratio > 0.55 ? "text-red-600" : ratio < 0.45 ? "text-green-600" : "text-gray-500";
        return <span className={colorClass}>{pct}%</span>;
      },
    },
    {
      key: "capital_signal",
      title: "资金信号",
      align: "center" as const,
      width: "80px",
      sortable: true,
      sorter: (a: StockDisplay, b: StockDisplay) => {
        const order = { bullish: 2, neutral: 1, bearish: 0 };
        return (order[a.capital_signal || "neutral"] || 1) - (order[b.capital_signal || "neutral"] || 1);
      },
      render: (value: string | undefined) => {
        if (!value || value === "neutral") {
          return <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">中性</span>;
        }
        if (value === "bullish") {
          return <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">多</span>;
        }
        return <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">空</span>;
      },
    },
  ], []);

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <i className="fas fa-fire text-red-600"></i>
          股票池监控
        </h1>

        <div className="flex items-center gap-4">
          {lastUpdateTime && (
            <span className="text-sm text-gray-600">
              最后更新: {formatTime(lastUpdateTime)}
            </span>
          )}
          <Button
            onClick={loadStocks}
            loading={loading}
            className="flex items-center gap-1"
          >
            <i className="fas fa-sync-alt"></i>
            刷新数据
          </Button>
        </div>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <Card>
          <div className="text-center">
            <div className="text-sm text-gray-600 mb-1">实时连接</div>
            <div className="text-2xl font-bold">
              {isConnected ? (
                <span className="text-green-600 flex items-center justify-center gap-1">
                  <i className="fas fa-check-circle"></i>
                  已连接
                </span>
              ) : (
                <span className="text-red-600 flex items-center justify-center gap-1">
                  <i className="fas fa-times-circle"></i>
                  未连接
                </span>
              )}
            </div>
          </div>
        </Card>

        <Card>
          <div className="text-center">
            <div className="text-sm text-gray-600 mb-1">热门股票数</div>
            <div className="text-3xl font-bold text-blue-600">
              {stats.totalCount}
            </div>
          </div>
        </Card>

        <Card>
          <div className="text-center">
            <div className="text-sm text-gray-600 mb-1">数据就绪</div>
            <div className="text-2xl font-bold">
              {dataReadyStatus ? (
                dataReadyStatus.data_ready ? (
                  <span className="text-green-600 flex items-center justify-center gap-1">
                    <i className="fas fa-check-circle"></i>
                    100%
                  </span>
                ) : (
                  <span className="text-orange-600">
                    {dataReadyStatus.ready_percent.toFixed(0)}%
                  </span>
                )
              ) : (
                <span className="text-gray-400">-</span>
              )}
            </div>
          </div>
        </Card>
      </div>

      {/* 数据未就绪提示 */}
      {dataReadyStatus && !dataReadyStatus.data_ready && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-6 flex items-start gap-3">
          <i className="fas fa-exclamation-triangle text-yellow-600 mt-0.5"></i>
          <p className="text-sm text-yellow-800">
            数据加载中，已缓存 {dataReadyStatus.cached_count}/{dataReadyStatus.expected_count} 只股票报价（{dataReadyStatus.ready_percent.toFixed(0)}%）。部分股票数据可能不完整，请稍后刷新。
          </p>
        </div>
      )}

      {/* 主要内容 */}
      <Card>
        {/* 搜索和筛选 */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-6">
          <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <i className="fas fa-chart-line text-blue-600"></i>
            热门股票列表
          </h3>

          <div className="flex gap-3">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索股票代码或名称..."
              className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <select
              value={marketFilter}
              onChange={(e) => setMarketFilter(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">所有市场</option>
              {activeMarkets.map((m) => (
                <option key={m} value={m}>{m === "HK" ? "港股" : m === "US" ? "美股" : m}</option>
              ))}
            </select>
            {(searchQuery || marketFilter) && (
              <Button
                variant="secondary"
                onClick={() => {
                  setSearchQuery("");
                  setMarketFilter("");
                }}
              >
                清除筛选
              </Button>
            )}
          </div>
        </div>

        {/* 股票表格 */}
        <Table
          columns={columns}
          data={stocks}
          loading={loading}
          emptyText="暂无股票数据"
          rowKey="id"
          defaultSortKey="heat_score"
          defaultSortOrder="desc"
          onRowClick={handleRowClick}
        />
      </Card>

      {/* Detail Panel 抽屉 */}
      <DetailDrawer stock={selectedStock} onClose={closePanel} />
    </div>
  );
}
