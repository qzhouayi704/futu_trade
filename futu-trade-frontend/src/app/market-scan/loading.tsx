// 市场扫描加载骨架屏

import { PageSkeleton, SkeletonTable } from "@/components/common";

export default function Loading() {
  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <PageSkeleton title="目标股票">
        <SkeletonTable rows={10} cols={9} />
      </PageSkeleton>
    </div>
  );
}
