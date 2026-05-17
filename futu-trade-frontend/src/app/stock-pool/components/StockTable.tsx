// 股票表格组件 - 支持分页、实时行情、搜索、删除

"use client";

import { useMemo } from "react";
import { Button } from "@/components/common";
import { formatPrice, formatPercent, formatVolume } from "@/lib/utils";
import type { Stock } from "@/types";

interface StockTableProps {
  stocks: Stock[];
  loading: boolean;
  searchQuery: string;
  totalCount: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  onDelete: (stockId: number, stockName: string) => void;
}

export function StockTable({
  stocks,
  loading,
  searchQuery,
  totalCount,
  page,
  pageSize,
  onPageChange,
  onDelete,
}: StockTableProps) {
  // 本地搜索筛选（若后端未筛选）
  const filteredStocks = useMemo(() => {
    if (!searchQuery) return stocks;
    const query = searchQuery.toLowerCase();
    return stocks.filter(
      (stock) =>
        stock.code.toLowerCase().includes(query) ||
        stock.name.toLowerCase().includes(query)
    );
  }, [stocks, searchQuery]);

  const totalPages = Math.ceil(totalCount / pageSize);

  return (
    <div>
      {/* 表格 */}
      <div className="overflow-x-auto border border-gray-200 rounded-lg">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
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
                所属板块
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                来源
              </th>
              <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                操作
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {loading ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                  <i className="fas fa-spinner fa-spin mr-2"></i>
                  加载中...
                </td>
              </tr>
            ) : filteredStocks.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                  暂无股票数据
                </td>
              </tr>
            ) : (
              filteredStocks.map((stock) => (
                <tr key={stock.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 text-sm font-medium text-blue-600">
                    {stock.code}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-900">
                    {stock.name || "-"}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                        stock.market === "HK"
                          ? "bg-red-100 text-red-700"
                          : "bg-blue-100 text-blue-700"
                      }`}
                    >
                      {stock.market === "HK" ? "港股" : stock.market === "US" ? "美股" : stock.market}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {(stock as any).plate_name || (stock as any).plate_names?.join(", ") || "-"}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                        stock.is_manual
                          ? "bg-yellow-100 text-yellow-700"
                          : "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {stock.is_manual ? "自选" : "板块"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-center">
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => onDelete(stock.id, stock.name)}
                      className="flex items-center gap-1 mx-auto"
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

      {/* 分页 */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4 px-2">
          <span className="text-sm text-gray-600">
            共 {totalCount} 只股票，第 {page}/{totalPages} 页
          </span>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={page <= 1}
              onClick={() => onPageChange(page - 1)}
            >
              上一页
            </Button>
            {/* 页码按钮 */}
            {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
              let pageNum: number;
              if (totalPages <= 5) {
                pageNum = i + 1;
              } else if (page <= 3) {
                pageNum = i + 1;
              } else if (page >= totalPages - 2) {
                pageNum = totalPages - 4 + i;
              } else {
                pageNum = page - 2 + i;
              }
              return (
                <Button
                  key={pageNum}
                  variant={pageNum === page ? "primary" : "secondary"}
                  size="sm"
                  onClick={() => onPageChange(pageNum)}
                >
                  {pageNum}
                </Button>
              );
            })}
            <Button
              variant="secondary"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => onPageChange(page + 1)}
            >
              下一页
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
