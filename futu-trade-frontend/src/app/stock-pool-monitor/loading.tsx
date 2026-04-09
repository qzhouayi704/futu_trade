// 股票池监控加载骨架屏

import { PageSkeleton, SkeletonCard } from "@/components/common";

export default function StockPoolMonitorLoading() {
  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <PageSkeleton title="股票池监控">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <SkeletonCard lines={4} />
          <SkeletonCard lines={4} />
        </div>
      </PageSkeleton>
    </div>
  );
}
