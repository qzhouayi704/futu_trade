// 交易条件加载骨架屏

import { PageSkeleton, SkeletonCard } from "@/components/common";

export default function ConditionsLoading() {
  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <PageSkeleton title="交易条件">
        <div className="space-y-6">
          <SkeletonCard lines={3} />
          <SkeletonCard lines={4} />
        </div>
      </PageSkeleton>
    </div>
  );
}
