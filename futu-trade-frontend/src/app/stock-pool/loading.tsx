// 股票池管理加载骨架屏

import { PageSkeleton, SkeletonTable } from "@/components/common";

export default function StockPoolLoading() {
  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <PageSkeleton title="股票池管理">
        <SkeletonTable rows={10} cols={5} />
      </PageSkeleton>
    </div>
  );
}
