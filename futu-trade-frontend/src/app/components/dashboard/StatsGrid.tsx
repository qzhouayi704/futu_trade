// 统计指标网格组件

"use client";

import { Card } from "@/components/common";

interface StatsData {
  stockPoolCount: number;
  subscribedCount: number;
  hotStockCount: number;
  positionCount: number;
}

interface StatsGridProps {
  stats: StatsData | null;
  className?: string;
}

export function StatsGrid({ stats, className = "" }: StatsGridProps) {
  const statItems = [
    {
      label: "股票池总数",
      value: stats?.stockPoolCount || 0,
      icon: (
        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>
      ),
      gradient: "from-blue-500 to-blue-600",
    },
    {
      label: "已订阅股票",
      value: stats?.subscribedCount || 0,
      icon: (
        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
        </svg>
      ),
      gradient: "from-purple-500 to-purple-600",
    },
    {
      label: "热门股票",
      value: stats?.hotStockCount || 0,
      icon: (
        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.879 16.121A3 3 0 1012.015 11L11 14H9c0 .768.293 1.536.879 2.121z" />
        </svg>
      ),
      gradient: "from-orange-500 to-orange-600",
    },
    {
      label: "持仓数量",
      value: stats?.positionCount || 0,
      icon: (
        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
        </svg>
      ),
      gradient: "from-green-500 to-green-600",
    },
  ];

  return (
    <div className={`grid grid-cols-2 lg:grid-cols-4 gap-4 ${className}`}>
      {statItems.map((item, index) => (
        <Card key={index} className={`bg-gradient-to-br ${item.gradient} text-white`}>
          <div className="p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm opacity-90">{item.label}</span>
              <div className="opacity-80">{item.icon}</div>
            </div>
            <div className="text-3xl font-bold">{item.value}</div>
          </div>
        </Card>
      ))}
    </div>
  );
}
