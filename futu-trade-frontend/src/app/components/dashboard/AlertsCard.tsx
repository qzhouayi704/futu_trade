// 5分钟预警卡片组件

"use client";

import { Card } from "@/components/common";
import { Alert } from "@/types/alert";
import { formatDistanceToNow } from "date-fns";
import { zhCN } from "date-fns/locale";

interface AlertsCardProps {
  alerts: Alert[];
  loading?: boolean;
}

export function AlertsCard({ alerts, loading = false }: AlertsCardProps) {
  // 按时间倒序排序，只显示最新5条
  const sortedAlerts = [...alerts]
    .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
    .slice(0, 5);

  // 获取预警级别对应的颜色
  const getLevelColor = (level: string) => {
    switch (level) {
      case "danger":
        return "bg-red-50 border-red-300 text-red-700";
      case "warning":
        return "bg-orange-50 border-orange-300 text-orange-700";
      case "info":
        return "bg-blue-50 border-blue-300 text-blue-700";
      default:
        return "bg-gray-50 border-gray-300 text-gray-700";
    }
  };

  // 获取预警类型图标
  const getAlertIcon = (type: string) => {
    if (type.includes("涨幅")) {
      return (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
        </svg>
      );
    }
    if (type.includes("跌幅")) {
      return (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 17h8m0 0V9m0 8l-8-8-4 4-6-6" />
        </svg>
      );
    }
    if (type.includes("振幅")) {
      return (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
        </svg>
      );
    }
    if (type.includes("成交量")) {
      return (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
      );
    }
    return null;
  };

  // 格式化相对时间
  const formatRelativeTime = (timestamp: string) => {
    try {
      return formatDistanceToNow(new Date(timestamp), {
        addSuffix: true,
        locale: zhCN,
      });
    } catch {
      return "刚刚";
    }
  };

  // 获取价格变化显示
  const getPriceChange = (alert: Alert) => {
    if (alert.type.includes("涨幅") && alert.rise_percent !== undefined) {
      return `+${alert.rise_percent.toFixed(2)}%`;
    }
    if (alert.type.includes("跌幅") && alert.fall_percent !== undefined) {
      return `${alert.fall_percent.toFixed(2)}%`;
    }
    if (alert.type.includes("振幅") && alert.amplitude !== undefined) {
      return `${alert.amplitude.toFixed(2)}%`;
    }
    if (alert.type.includes("成交量") && alert.volume_display) {
      return alert.volume_display;
    }
    return "";
  };

  return (
    <Card>
      <div className="p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <svg className="w-5 h-5 text-yellow-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            5分钟预警
          </h3>
          {sortedAlerts.length > 0 && (
            <span className="text-xs text-gray-500">
              {sortedAlerts.length} 条预警
            </span>
          )}
        </div>

        {loading ? (
          <div className="text-center py-8 text-gray-500">加载中...</div>
        ) : sortedAlerts.length === 0 ? (
          <div className="text-center py-8 text-gray-500">暂无预警</div>
        ) : (
          <div className="space-y-2">
            {sortedAlerts.map((alert, index) => (
              <div
                key={`${alert.stock_code}-${alert.timestamp}-${index}`}
                className={`p-3 rounded-lg border ${getLevelColor(alert.level)} transition-colors hover:shadow-md`}
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    {getAlertIcon(alert.type)}
                    <div>
                      <span className="font-medium">{alert.stock_name}</span>
                      <span className="text-xs ml-2 opacity-75">{alert.stock_code}</span>
                    </div>
                  </div>
                  <span className="text-sm font-bold">
                    {getPriceChange(alert)}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs opacity-75">
                  <span className="truncate mr-2">{alert.message}</span>
                  <span className="shrink-0">{formatRelativeTime(alert.timestamp)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
