// 活跃个股页面 - 按换手率排序的股票排行榜（集成成交分析）

"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { Card, Button, Loading } from "@/components/common";
import { stockApi } from "@/lib/api";
import { useToast } from "@/components/common/Toast";
import { useTickerAutoRefresh } from "./hooks/useTickerAutoRefresh";
import HighTurnoverFilters from "./components/HighTurnoverFilters";
import HighTurnoverTable from "./components/HighTurnoverTable";
import ScalpingDetailModal from "./components/ScalpingDetailModal";
import type { SortField, SortDirection } from "./components/HighTurnoverTable";
import type { HighTurnoverStock } from "@/types/stock";

/** 成交方向筛选类型 */
type DirectionFilter = "all" | "bullish" | "bearish" | "neutral";

export default function HighTurnoverPage() {
  const { showToast } = useToast();

  // 数据状态
  const [stocks, setStocks] = useState<HighTurnoverStock[]>([]);
  const [updateTime, setUpdateTime] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [tickerLoading, setTickerLoading] = useState(false);

  // 筛选状态
  const [marketFilter, setMarketFilter] = useState("all");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [directionFilter, setDirectionFilter] = useState<DirectionFilter>("all");

  // 排序状态（默认按换手率降序）
  const [sortField, setSortField] = useState<SortField>("turnover_rate");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

  // 详情面板
  const [selectedStock, setSelectedStock] = useState<HighTurnoverStock | null>(null);

  // 加载数据（含成交分析）
  const loadData = useCallback(async (isRefresh = false) => {
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setTickerLoading(true);

    try {
      const response = await stockApi.getHighTurnoverStocks({
        limit: 50,
        include_ticker_analysis: true,
      });
      if (response.success && response.data) {
        setStocks(response.data.stocks || []);
        setUpdateTime(response.data.update_time || "");
      } else {
        showToast("warning", "提示", response.message || "暂无活跃个股数据");
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "加载活跃个股数据失败";
      showToast("error", "错误", message);
      // 成交分析批量请求失败时，尝试不带分析数据加载
      try {
        const fallback = await stockApi.getHighTurnoverStocks({ limit: 200 });
        if (fallback.success && fallback.data) {
          setStocks(fallback.data.stocks || []);
          setUpdateTime(fallback.data.update_time || "");
          showToast("warning", "提示", "成交分析数据加载失败");
        }
      } catch {
        // 完全失败，保持原有错误提示
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
      setTickerLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // 自动刷新回调（静默刷新，不显示 loading 状态）
  const handleAutoRefresh = useCallback(async () => {
    const response = await stockApi.getHighTurnoverStocks({
      limit: 50,
      include_ticker_analysis: true,
    });
    if (response.success && response.data) {
      setStocks(response.data.stocks || []);
      setUpdateTime(response.data.update_time || "");
    } else {
      throw new Error(response.message || "刷新失败");
    }
  }, []);

  // 集成自动刷新 hook（10 秒间隔）
  const { paused: autoRefreshPaused, resume: resumeAutoRefresh } = useTickerAutoRefresh({
    interval: 10000,
    enabled: !loading,
    onRefresh: handleAutoRefresh,
    maxConsecutiveFailures: 3,
    onPaused: () => {
      showToast("warning", "提示", "自动刷新已暂停，请手动刷新");
    },
  });

  // 行点击：展开/关闭详情面板
  const handleRowClick = useCallback((stock: HighTurnoverStock) => {
    setSelectedStock((prev) => (prev?.code === stock.code ? null : stock));
  }, []);

  const closePanel = useCallback(() => {
    setSelectedStock(null);
  }, []);

  // 排序切换处理
  const handleSortChange = useCallback((field: SortField) => {
    if (field === sortField) {
      setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDirection("desc");
    }
  }, [sortField]);

  // 客户端筛选 + 排序
  const displayStocks = useMemo(() => {
    let filtered = stocks;

    // 市场筛选
    if (marketFilter !== "all") {
      filtered = filtered.filter((s) => s.market === marketFilter);
    }

    // 搜索过滤（按代码或名称，不区分大小写）
    if (searchKeyword.trim()) {
      const keyword = searchKeyword.trim().toLowerCase();
      filtered = filtered.filter(
        (s) =>
          s.code.toLowerCase().includes(keyword) ||
          s.name.toLowerCase().includes(keyword)
      );
    }

    // 成交方向筛选
    if (directionFilter !== "all") {
      filtered = filtered.filter((s) => {
        const bias = s.ticker_summary?.bias;
        if (!bias) return false;
        switch (directionFilter) {
          case "bullish":
            return bias === "bullish" || bias === "strong_bullish";
          case "bearish":
            return bias === "bearish";
          case "neutral":
            return bias === "neutral";
          default:
            return true;
        }
      });
    }

    // 排序
    const sorted = [...filtered].sort((a, b) => {
      let aVal: number;
      let bVal: number;

      if (sortField === "score") {
        aVal = a.ticker_summary?.score ?? 0;
        bVal = b.ticker_summary?.score ?? 0;
      } else if (sortField === "buy_sell_ratio") {
        aVal = a.ticker_summary?.buy_sell_ratio ?? 0;
        bVal = b.ticker_summary?.buy_sell_ratio ?? 0;
      } else if (sortField === "big_order_pct") {
        aVal = a.ticker_summary?.big_order_pct ?? 0;
        bVal = b.ticker_summary?.big_order_pct ?? 0;
      } else {
        aVal = a[sortField] as number;
        bVal = b[sortField] as number;
      }

      return sortDirection === "asc" ? aVal - bVal : bVal - aVal;
    });

    // 重新计算排名
    return sorted.map((s, i) => ({ ...s, rank: i + 1 }));
  }, [stocks, marketFilter, searchKeyword, directionFilter, sortField, sortDirection]);

  // 统计偏多股票数量（bias 为 bullish 或 strong_bullish）
  const bullishCount = useMemo(() => {
    return stocks.filter((s) => {
      const bias = s.ticker_summary?.bias;
      return bias === "bullish" || bias === "strong_bullish";
    }).length;
  }, [stocks]);

  // 格式化更新时间
  const formattedUpdateTime = useMemo(() => {
    if (!updateTime) return "";
    try {
      return new Date(updateTime).toLocaleString("zh-CN");
    } catch {
      return updateTime;
    }
  }, [updateTime]);

  if (loading) {
    return <Loading fullScreen />;
  }

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      {/* 页面标题 */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <i className="fas fa-exchange-alt text-orange-600" />
            活跃个股
            {bullishCount > 0 && (
              <span className="text-sm font-medium text-red-600 bg-red-50 px-2 py-0.5 rounded">
                偏多 {bullishCount} 只
              </span>
            )}
          </h1>
          <p className="text-gray-600 mt-1">
            按换手率排序的交易活跃股票排行榜
            {formattedUpdateTime && (
              <span className="ml-2 text-xs text-gray-400">
                更新于 {formattedUpdateTime}
              </span>
            )}
            {autoRefreshPaused && (
              <span className="ml-2 text-xs text-amber-600">
                （自动刷新已暂停）
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {autoRefreshPaused && (
            <Button
              size="sm"
              variant="secondary"
              onClick={resumeAutoRefresh}
              className="flex items-center gap-1 text-amber-600"
            >
              <i className="fas fa-play" />
              恢复刷新
            </Button>
          )}
          <Button
            size="sm"
            variant="secondary"
            loading={refreshing}
            onClick={() => loadData(true)}
            className="flex items-center gap-1"
          >
            <i className="fas fa-sync-alt" />
            刷新
          </Button>
        </div>
      </div>

      {/* 筛选栏 */}
      <Card className="mb-6">
        <HighTurnoverFilters
          marketFilter={marketFilter}
          searchKeyword={searchKeyword}
          directionFilter={directionFilter}
          onMarketChange={setMarketFilter}
          onSearchChange={setSearchKeyword}
          onDirectionChange={setDirectionFilter}
        />
      </Card>

      {/* 股票表格 */}
      <Card>
        <HighTurnoverTable
          stocks={displayStocks}
          sortField={sortField}
          sortDirection={sortDirection}
          onSortChange={handleSortChange}
          tickerLoading={tickerLoading}
          onRowClick={handleRowClick}
        />
      </Card>

      {/* Scalping 详情面板 */}
      {selectedStock && (
        <ScalpingDetailModal stock={selectedStock} onClose={closePanel} />
      )}
    </div>
  );
}
