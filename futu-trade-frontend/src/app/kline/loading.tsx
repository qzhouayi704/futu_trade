// K线页面加载骨架屏

import { PageSkeleton, SkeletonChart } from "@/components/common";

export default function KlineLoading() {
  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <PageSkeleton title="K线图表">
        <SkeletonChart height={600} />
      </PageSkeleton>
    </div>
  );
}
