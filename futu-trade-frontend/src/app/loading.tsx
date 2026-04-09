// Dashboard 首页加载骨架屏

import { SkeletonCard } from "@/components/common";

export default function DashboardLoading() {
  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <div className="h-8 w-48 bg-gray-200 rounded animate-pulse mb-6" />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        <SkeletonCard lines={3} />
        <SkeletonCard lines={2} className="lg:col-span-2" />
      </div>
      <SkeletonCard lines={2} className="mb-6" />
      <SkeletonCard lines={3} className="mb-6" />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <SkeletonCard lines={4} />
        <SkeletonCard lines={4} />
      </div>
      <SkeletonCard lines={3} className="mb-6" />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SkeletonCard lines={4} />
        <SkeletonCard lines={4} />
      </div>
    </div>
  );
}
