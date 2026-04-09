// Table 组件

"use client";

import { ReactNode, useState, useMemo } from "react";

type SortOrder = "asc" | "desc" | null;

interface Column<T> {
  key: string;
  title: string;
  render?: (value: any, record: T, index: number) => ReactNode;
  width?: string;
  align?: "left" | "center" | "right";
  sortable?: boolean;
  sorter?: (a: T, b: T) => number;
}

interface TableProps<T> {
  columns: Column<T>[];
  data: T[];
  loading?: boolean;
  emptyText?: string;
  rowKey?: keyof T | ((record: T) => string | number);
  onRowClick?: (record: T, index: number) => void;
  defaultSortKey?: string;
  defaultSortOrder?: SortOrder;
}

export function Table<T extends Record<string, any>>({
  columns,
  data,
  loading = false,
  emptyText = "暂无数据",
  rowKey = "id",
  onRowClick,
  defaultSortKey,
  defaultSortOrder = null,
}: TableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(defaultSortKey || null);
  const [sortOrder, setSortOrder] = useState<SortOrder>(defaultSortOrder);

  const getRowKey = (record: T, index: number): string | number => {
    if (typeof rowKey === "function") {
      return rowKey(record);
    }
    return record[rowKey] ?? index;
  };

  const alignClasses = {
    left: "text-left",
    center: "text-center",
    right: "text-right",
  };

  // 处理列头点击排序
  const handleSort = (column: Column<T>) => {
    if (!column.sortable) return;

    if (sortKey === column.key) {
      // 同一列：null -> asc -> desc -> null
      if (sortOrder === null) {
        setSortOrder("asc");
      } else if (sortOrder === "asc") {
        setSortOrder("desc");
      } else {
        setSortKey(null);
        setSortOrder(null);
      }
    } else {
      // 不同列：重置为升序
      setSortKey(column.key);
      setSortOrder("asc");
    }
  };

  // 排序数据
  const sortedData = useMemo(() => {
    if (!sortKey || !sortOrder) return data;

    const column = columns.find((col) => col.key === sortKey);
    if (!column) return data;

    const sorted = [...data].sort((a, b) => {
      // 如果提供了自定义排序函数
      if (column.sorter) {
        return column.sorter(a, b);
      }

      // 默认排序逻辑
      const aValue = a[sortKey];
      const bValue = b[sortKey];

      // 处理 null/undefined
      if (aValue == null && bValue == null) return 0;
      if (aValue == null) return 1;
      if (bValue == null) return -1;

      // 数字比较
      if (typeof aValue === "number" && typeof bValue === "number") {
        return aValue - bValue;
      }

      // 字符串比较
      return String(aValue).localeCompare(String(bValue), "zh-CN");
    });

    return sortOrder === "desc" ? sorted.reverse() : sorted;
  }, [data, sortKey, sortOrder, columns]);

  // 渲染排序图标
  const renderSortIcon = (column: Column<T>) => {
    if (!column.sortable) return null;

    const isActive = sortKey === column.key;

    return (
      <span className="ml-1 inline-flex flex-col">
        <svg
          className={`w-3 h-3 -mb-1 ${
            isActive && sortOrder === "asc" ? "text-blue-600" : "text-gray-400"
          }`}
          fill="currentColor"
          viewBox="0 0 20 20"
        >
          <path d="M5 10l5-5 5 5H5z" />
        </svg>
        <svg
          className={`w-3 h-3 ${
            isActive && sortOrder === "desc" ? "text-blue-600" : "text-gray-400"
          }`}
          fill="currentColor"
          viewBox="0 0 20 20"
        >
          <path d="M15 10l-5 5-5-5h10z" />
        </svg>
      </span>
    );
  };

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                className={`px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider ${
                  alignClasses[column.align || "left"]
                } ${column.sortable ? "cursor-pointer select-none hover:bg-gray-100" : ""}`}
                style={{ width: column.width }}
                onClick={() => handleSort(column)}
              >
                <div className="flex items-center justify-between">
                  <span>{column.title}</span>
                  {renderSortIcon(column)}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200">
          {loading ? (
            <tr>
              <td colSpan={columns.length} className="px-6 py-4 text-center text-gray-500">
                <div className="flex items-center justify-center gap-2">
                  <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                      fill="none"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                  <span>加载中...</span>
                </div>
              </td>
            </tr>
          ) : sortedData.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-6 py-4 text-center text-gray-500">
                {emptyText}
              </td>
            </tr>
          ) : (
            sortedData.map((record, index) => (
              <tr
                key={getRowKey(record, index)}
                className={`hover:bg-gray-50 ${onRowClick ? "cursor-pointer" : ""}`}
                onClick={() => onRowClick?.(record, index)}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={`px-6 py-4 whitespace-nowrap text-sm text-gray-900 ${
                      alignClasses[column.align || "left"]
                    }`}
                  >
                    {column.render
                      ? column.render(record[column.key], record, index)
                      : (record[column.key] ?? '-')}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
