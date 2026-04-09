// 自动交易加载骨架屏

import { PageSkeleton, SkeletonCard } from "@/components/common";

export default function TradingLoading() {
  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <PageSkeleton title="自动交易">
        <div className="space-y-6">
          <SkeletonCard lines={3} />
          <SkeletonCard lines={4} />
        </div>
      </PageSkeleton>
    </div>
  );
}
