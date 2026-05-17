// 板块表格组件 — 修复市场筛选和市场显示逻辑

"use client";

import { useState, useMemo } from "react";
import { Button } from "@/components/common";
import type { Plate } from "@/types";

interface PlateTableProps {
  plates: Plate[];
  loading: boolean;
  onDelete: (plateId: number, plateName: string) => void;
  onRefresh: () => void;
}

export function PlateTable({ plates, loading, onDelete, onRefresh }: PlateTableProps) {
  const [marketFilter, setMarketFilter] = useState<string>("");

  // 从板块数据中提取可用市场列表
  const availableMarkets = useMemo(() => {
    const markets = new Set<string>();
    plates.forEach((plate) => {
      if (plate.market) markets.add(plate.market);
    });
    return Array.from(markets);
  }, [plates]);

  // 筛选板块 — 使用后端返回的 market 字段（修复 P7）
  const filteredPlates = useMemo(() => {
    return plates.filter((plate) => {
      if (marketFilter && plate.market !== marketFilter) {
        return false;
      }
      return true;
    });
  }, [plates, marketFilter]);

  return (
    <div>
      {/* 筛选器 */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-1">
          市场筛选
        </label>
        <select
          value={marketFilter}
          onChange={(e) => setMarketFilter(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">所有市场</option>
          {availableMarkets.map((m) => (
            <option key={m} value={m}>
              {m === "HK" ? "港股" : m === "US" ? "美股" : m}
            </option>
          ))}
        </select>
      </div>

      {/* 表格 */}
      <div className="overflow-x-auto max-h-[500px] overflow-y-auto border border-gray-200 rounded-lg">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                代码
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                名称
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                市场
              </th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                股票数
              </th>
              <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                操作
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {loading ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-gray-500">
                  <i className="fas fa-spinner fa-spin mr-2"></i>
                  加载中...
                </td>
              </tr>
            ) : filteredPlates.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-gray-500">
                  暂无板块数据
                </td>
              </tr>
            ) : (
              filteredPlates.map((plate) => (
                <tr key={plate.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 text-sm font-medium text-blue-600">
                    {plate.plate_code}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-900">
                    {plate.plate_name}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {/* 修复 P13: 使用后端返回的 market 字段 */}
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                        plate.market === "HK"
                          ? "bg-red-100 text-red-700"
                          : "bg-blue-100 text-blue-700"
                      }`}
                    >
                      {plate.market === "HK" ? "港股" : plate.market === "US" ? "美股" : plate.market}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-right text-gray-900 font-medium">
                    {plate.stock_count || 0}
                  </td>
                  <td className="px-4 py-3 text-sm text-center">
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => onDelete(plate.id, plate.plate_name)}
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

      {/* 统计 */}
      <div className="mt-3 text-sm text-gray-500">
        共 {filteredPlates.length} 个板块
        {marketFilter && ` (已筛选: ${marketFilter === "HK" ? "港股" : "美股"})`}
      </div>
    </div>
  );
}
