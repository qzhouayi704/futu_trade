// 热点新闻加载骨架屏

import { PageSkeleton, SkeletonCard } from "@/components/common";

export default function NewsLoading() {
  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <PageSkeleton title="热点新闻">
        <div className="space-y-4">
          <SkeletonCard lines={2} />
          <SkeletonCard lines={2} />
          <SkeletonCard lines={2} />
        </div>
      </PageSkeleton>
    </div>
  );
}
