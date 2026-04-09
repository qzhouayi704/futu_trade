// 持仓订单加载骨架屏

import { PageSkeleton, SkeletonTable } from "@/components/common";

export default function PositionsLoading() {
  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <PageSkeleton title="持仓订单">
        <SkeletonTable rows={8} cols={7} />
      </PageSkeleton>
    </div>
  );
}
