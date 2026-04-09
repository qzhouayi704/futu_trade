// 活跃个股加载骨架屏

import { PageSkeleton, SkeletonTable } from "@/components/common";

export default function HighTurnoverLoading() {
  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <PageSkeleton title="活跃个股">
        <SkeletonTable rows={10} cols={6} />
      </PageSkeleton>
    </div>
  );
}
