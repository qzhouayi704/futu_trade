// 未订阅股票加载骨架屏

import { PageSkeleton, SkeletonTable } from "@/components/common";

export default function UnsubscribedStocksLoading() {
  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <PageSkeleton title="未订阅股票">
        <SkeletonTable rows={8} cols={5} />
      </PageSkeleton>
    </div>
  );
}
