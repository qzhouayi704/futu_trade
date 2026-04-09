// 板块热度排行页面

"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { Card, Button, Loading } from "@/components/common";
import { strategyApi } from "@/lib/api";
import { useToast } from "@/components/common/Toast";
import { formatPercent } from "@/lib/utils";
import type { PlateStrength } from "@/types/stock";
import { MarketHeatPanel } from "../enhanced-heat/components/MarketHeatPanel";
import { ScreeningResult } from "../enhanced-heat/components/ScreeningResult";

interface LeaderStock {
  stock_code: string;
  stock_name: string;
  change_pct: number;
  cur_price: number;
}

interface PlateData extends PlateStrength {
  leader_stocks?: LeaderStock[];
}

export default function PlatesPage() {
  const { showToast } = useToast();

  const [plates, setPlates] = useState<PlateData[]>([]);
  const [loading, setLoading] = useState(true);
  const [marketFilter, setMarketFilter] = useState<string>("all");
  const [sortBy, setSortBy] = useState<"strength" | "ratio" | "change">("strength");
  const [expandedPlates, setExpandedPlates] = useState<Set<string>>(new Set());

  // 加载板块数据
  useEffect(() => {
    loadPlates();
  }, []);

  const loadPlates = async () => {
    setLoading(true);
    try {
      const response = await strategyApi.getPlateStrength();
      if (response.success && response.data) {
        setPlates(response.data.plates || []);
      } else {
        showToast("warning", "提示", response.message || "暂无板块数据");
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "加载板块数据失败";
      showToast("error", "错误", message);
    } finally {
      setLoading(false);
    }
  };

  // 切换展开/收起
  const toggleExpand = (plateCode: string) => {
    setExpandedPlates((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(plateCode)) {
        newSet.delete(plateCode);
      } else {
        newSet.add(plateCode);
      }
      return newSet;
    });
  };

  // 筛选和排序
  const filteredAndSortedPlates = plates
    .filter((plate) => {
      if (marketFilter === "all") return true;
      return plate.market === marketFilter;
    })
    .sort((a, b) => {
      switch (sortBy) {
        case "strength":
          return (b.strength_score ?? 0) - (a.strength_score ?? 0);
        case "ratio":
          return (b.up_stock_ratio ?? 0) - (a.up_stock_ratio ?? 0);
        case "change":
          return (b.avg_change_pct ?? 0) - (a.avg_change_pct ?? 0);
        default:
          return 0;
      }
    });

  if (loading) {
    return <Loading fullScreen />;
  }

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      {/* 页面标题 */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <i className="fas fa-fire text-orange-600"></i>
          板块热度排行
        </h1>
        <p className="text-gray-600 mt-1">实时板块强势度分析与龙头股票追踪</p>
      </div>

      {/* 筛选和排序 */}
      <Card className="mb-6">
        <div className="flex flex-wrap items-center gap-4">
          {/* 市场筛选 */}
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-700">市场：</span>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant={marketFilter === "all" ? "primary" : "secondary"}
                onClick={() => setMarketFilter("all")}
              >
                全部
              </Button>
              <Button
                size="sm"
                variant={marketFilter === "HK" ? "primary" : "secondary"}
                onClick={() => setMarketFilter("HK")}
              >
                港股
              </Button>
              <Button
                size="sm"
                variant={marketFilter === "US" ? "primary" : "secondary"}
                onClick={() => setMarketFilter("US")}
              >
                美股
              </Button>
            </div>
          </div>

          {/* 排序方式 */}
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-700">排序：</span>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant={sortBy === "strength" ? "primary" : "secondary"}
                onClick={() => setSortBy("strength")}
              >
                强势分
              </Button>
              <Button
                size="sm"
                variant={sortBy === "ratio" ? "primary" : "secondary"}
                onClick={() => setSortBy("ratio")}
              >
                上涨比例
              </Button>
              <Button
                size="sm"
                variant={sortBy === "change" ? "primary" : "secondary"}
                onClick={() => setSortBy("change")}
              >
                平均涨幅
              </Button>
            </div>
          </div>

          {/* 刷新按钮 */}
          <Button
            size="sm"
            variant="secondary"
            onClick={loadPlates}
            className="ml-auto flex items-center gap-1"
          >
            <i className="fas fa-sync-alt"></i>
            刷新
          </Button>
        </div>
      </Card>

      {/* 市场热度概览 */}
      <MarketHeatPanel />

      {/* 板块列表 */}
      <Card>
        {filteredAndSortedPlates.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            <i className="fas fa-inbox text-4xl mb-4"></i>
            <p>暂无板块数据</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    板块代码
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                    板块名称
                  </th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                    市场
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    强势分
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    上涨比例
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                    平均涨幅
                  </th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                    龙头数量
                  </th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {filteredAndSortedPlates.map((plate) => {
                  const isExpanded = expandedPlates.has(plate.plate_code);
                  const hasLeaders = plate.leader_stocks && plate.leader_stocks.length > 0;

                  return (
                    <React.Fragment key={plate.plate_code}>
                      {/* 主行 */}
                      <tr className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-sm text-gray-900">
                          {plate.plate_code}
                        </td>
                        <td className="px-4 py-3 text-sm">
                          <Link
                            href={`/plate/${plate.plate_code}`}
                            className="text-blue-600 hover:text-blue-800 hover:underline font-medium"
                          >
                            {plate.plate_name}
                          </Link>
                        </td>
                        <td className="px-4 py-3 text-sm text-center">
                          <span
                            className={`px-2 py-1 rounded text-xs font-medium ${
                              plate.market === "HK"
                                ? "bg-blue-100 text-blue-800"
                                : "bg-purple-100 text-purple-800"
                            }`}
                          >
                            {plate.market}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-right font-semibold text-orange-600">
                          {(plate.strength_score ?? 0).toFixed(2)}
                        </td>
                        <td className="px-4 py-3 text-sm text-right">
                          {formatPercent((plate.up_stock_ratio ?? 0) * 100)}
                        </td>
                        <td className="px-4 py-3 text-sm text-right">
                          <span
                            className={
                              (plate.avg_change_pct ?? 0) >= 0
                                ? "text-red-600"
                                : "text-green-600"
                            }
                          >
                            {formatPercent(plate.avg_change_pct ?? 0)}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-center">
                          <span className="px-2 py-1 bg-yellow-100 text-yellow-800 rounded text-xs font-medium">
                            {plate.leader_count}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-center">
                          {hasLeaders && (
                            <button
                              onClick={() => toggleExpand(plate.plate_code)}
                              className="text-blue-600 hover:text-blue-800 flex items-center gap-1 mx-auto"
                            >
                              <i
                                className={`fas fa-chevron-${
                                  isExpanded ? "up" : "down"
                                }`}
                              ></i>
                              <span className="text-xs">
                                {isExpanded ? "收起" : "展开"}
                              </span>
                            </button>
                          )}
                        </td>
                      </tr>

                      {/* 展开行 - 龙头股票 */}
                      {isExpanded && hasLeaders && (
                        <tr>
                          <td colSpan={8} className="px-4 py-3 bg-gray-50">
                            <div className="pl-8">
                              <h4 className="text-sm font-medium text-gray-700 mb-2">
                                龙头股票：
                              </h4>
                              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                {plate.leader_stocks?.map((stock) => (
                                  <Link
                                    key={stock.stock_code}
                                    href={`/kline?code=${stock.stock_code}`}
                                    className="block p-3 bg-white border border-gray-200 rounded-lg hover:border-blue-300 hover:shadow-sm transition-all"
                                  >
                                    <div className="flex items-center justify-between">
                                      <div>
                                        <div className="text-sm font-medium text-gray-900">
                                          {stock.stock_name}
                                        </div>
                                        <div className="text-xs text-gray-500">
                                          {stock.stock_code}
                                        </div>
                                      </div>
                                      <div className="text-right">
                                        <div
                                          className={`text-sm font-semibold ${
                                            stock.change_pct >= 0
                                              ? "text-red-600"
                                              : "text-green-600"
                                          }`}
                                        >
                                          {formatPercent(stock.change_pct)}
                                        </div>
                                        <div className="text-xs text-gray-600">
                                          ¥{stock.cur_price.toFixed(2)}
                                        </div>
                                      </div>
                                    </div>
                                  </Link>
                                ))}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* 三级筛选结果 */}
      <ScreeningResult />
    </div>
  );
}
