// 板块热度加载骨架屏

import { PageSkeleton, SkeletonTable } from "@/components/common";

export default function PlatesLoading() {
  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <PageSkeleton title="板块热度">
        <SkeletonTable rows={8} cols={5} />
      </PageSkeleton>
    </div>
  );
}
