// 骨架屏组件库
// 基于 Tailwind CSS v4 的 animate-pulse 实现加载占位动画

import { ReactNode } from "react";

// ============================================================
// 类型定义
// ============================================================

/** 单行骨架屏属性 */
interface SkeletonLineProps {
  className?: string;
}

/** 卡片骨架屏属性 */
interface SkeletonCardProps {
  /** 占位行数，默认 3 */
  lines?: number;
  /** 是否显示标题占位，默认 true */
  hasHeader?: boolean;
  className?: string;
}

/** 表格骨架屏属性 */
interface SkeletonTableProps {
  /** 行数，默认 5 */
  rows?: number;
  /** 列数，默认 4 */
  cols?: number;
}

/** 图表骨架屏属性 */
interface SkeletonChartProps {
  /** 图表高度（px），默认 300 */
  height?: number;
}

/** 页面级骨架屏属性 */
interface PageSkeletonProps {
  /** 页面标题 */
  title?: string;
  /** 自定义内容区骨架 */
  children?: ReactNode;
}

// ============================================================
// 组件实现
// ============================================================

/** 单行骨架屏 — 最基础的构建块 */
export function SkeletonLine({ className = "" }: SkeletonLineProps) {
  return (
    <div
      className={`h-4 bg-gray-200 rounded animate-pulse ${className}`}
    />
  );
}

/** 卡片骨架屏 — 模拟 Card 组件的加载状态 */
export function SkeletonCard({
  lines = 3,
  hasHeader = true,
  className = "",
}: SkeletonCardProps) {
  return (
    <div
      className={`bg-white rounded-lg shadow-md overflow-hidden ${className}`}
    >
      {/* 标题区域 */}
      {hasHeader && (
        <div className="px-6 py-4 border-b border-gray-200">
          <div className="h-5 w-1/3 bg-gray-200 rounded animate-pulse" />
        </div>
      )}

      {/* 内容区域 */}
      <div className="p-6 space-y-3">
        {Array.from({ length: lines }, (_, i) => (
          <SkeletonLine
            key={i}
            className={i === lines - 1 ? "w-2/3" : "w-full"}
          />
        ))}
      </div>
    </div>
  );
}

/** 表格骨架屏 — 模拟 Table 组件的加载状态 */
export function SkeletonTable({ rows = 5, cols = 4 }: SkeletonTableProps) {
  return (
    <div className="bg-white rounded-lg shadow-md overflow-hidden">
      {/* 表头 */}
      <div className="px-6 py-3 border-b border-gray-200 flex gap-4">
        {Array.from({ length: cols }, (_, i) => (
          <div
            key={i}
            className="h-4 bg-gray-300 rounded animate-pulse flex-1"
          />
        ))}
      </div>

      {/* 表体行 */}
      {Array.from({ length: rows }, (_, rowIdx) => (
        <div
          key={rowIdx}
          className="px-6 py-3 border-b border-gray-100 flex gap-4"
        >
          {Array.from({ length: cols }, (_, colIdx) => (
            <div
              key={colIdx}
              className="h-4 bg-gray-200 rounded animate-pulse flex-1"
            />
          ))}
        </div>
      ))}
    </div>
  );
}

/** 图表骨架屏 — 模拟图表区域的加载状态 */
export function SkeletonChart({ height = 300 }: SkeletonChartProps) {
  return (
    <div className="bg-white rounded-lg shadow-md overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-200">
        <div className="h-5 w-1/4 bg-gray-200 rounded animate-pulse" />
      </div>
      <div className="p-6">
        <div
          className="bg-gray-200 rounded animate-pulse w-full"
          style={{ height: `${height}px` }}
        />
      </div>
    </div>
  );
}

/** 页面级骨架屏 — 标题 + 内容区的通用页面加载状态 */
export function PageSkeleton({ title, children }: PageSkeletonProps) {
  return (
    <div className="space-y-6">
      {/* 页面标题区 */}
      <div className="flex items-center justify-between">
        {title ? (
          <h1 className="text-2xl font-bold text-gray-900">{title}</h1>
        ) : (
          <div className="h-8 w-48 bg-gray-200 rounded animate-pulse" />
        )}
      </div>

      {/* 内容区：优先使用自定义子元素，否则渲染默认骨架 */}
      {children ?? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <SkeletonCard lines={4} />
          <SkeletonCard lines={4} />
          <SkeletonCard lines={3} className="md:col-span-2" />
        </div>
      )}
    </div>
  );
}
