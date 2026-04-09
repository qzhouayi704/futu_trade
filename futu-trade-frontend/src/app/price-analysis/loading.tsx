// 价格位置分析加载骨架屏

import { PageSkeleton, SkeletonCard } from "@/components/common";

export default function PriceAnalysisLoading() {
  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <PageSkeleton title="价格位置分析">
        <div className="space-y-6">
          <SkeletonCard lines={3} />
          <SkeletonCard lines={5} />
        </div>
      </PageSkeleton>
    </div>
  );
}
