// 系统配置加载骨架屏

import { PageSkeleton, SkeletonCard } from "@/components/common";

export default function ConfigLoading() {
  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <PageSkeleton title="系统配置">
        <div className="space-y-6">
          <SkeletonCard lines={4} />
          <SkeletonCard lines={4} />
        </div>
      </PageSkeleton>
    </div>
  );
}
