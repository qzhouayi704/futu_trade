// 板块表格组件

"use client";

import { useState } from "react";
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
  const [typeFilter, setTypeFilter] = useState<string>("");

  // 筛选板块
  const filteredPlates = plates.filter((plate) => {
    if (marketFilter && !plate.plate_code.startsWith(marketFilter)) {
      return false;
    }
    // 可以根据需要添加更多筛选逻辑
    return true;
  });

  return (
    <div>
      {/* 筛选器 */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            市场筛选
          </label>
          <select
            value={marketFilter}
            onChange={(e) => setMarketFilter(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">所有市场</option>
            <option value="HK">港股</option>
            <option value="US">美股</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            类型筛选
          </label>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">所有类型</option>
            <option value="target">目标板块</option>
            <option value="normal">普通板块</option>
          </select>
        </div>
      </div>

      {/* 表格 */}
      <div className="overflow-x-auto max-h-96 overflow-y-auto border border-gray-200 rounded-lg">
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
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                股票数
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
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
                <tr key={plate.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm text-gray-900">
                    {plate.plate_code}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-900">
                    {plate.plate_name}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-900">
                    {plate.plate_code.startsWith("HK") ? "港股" : "美股"}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-900">
                    {plate.stock_count || 0}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => onDelete(plate.id, plate.plate_name)}
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
    </div>
  );
}
