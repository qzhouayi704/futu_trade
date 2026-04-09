// 系统状态卡片组件

"use client";

import { Card } from "@/components/common";
import { Button } from "@/components/common";
import type { SystemStatus } from "@/types/stock";

interface SystemStatusCardProps {
  status: SystemStatus | null;
  isConnected: boolean;
  onStartMonitor?: () => void;
  onStopMonitor?: () => void;
  loading?: boolean;
}

export function SystemStatusCard({
  status,
  isConnected,
  onStartMonitor,
  onStopMonitor,
  loading = false,
}: SystemStatusCardProps) {
  const isRunning = status?.is_running || false;
  const futuConnected = status?.futu_connected || false;

  return (
    <Card>
      <div className="p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <svg className="w-5 h-5 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          系统状态
        </h3>

        <div className="space-y-4">
          {/* 运行状态 */}
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-600">监控状态</span>
            <div className="flex items-center gap-2">
              <span
                className={`w-2 h-2 rounded-full ${
                  isRunning ? "bg-green-500" : "bg-gray-400"
                }`}
              ></span>
              <span
                className={`text-sm font-medium ${
                  isRunning ? "text-green-600" : "text-gray-600"
                }`}
              >
                {isRunning ? "运行中" : "已停止"}
              </span>
            </div>
          </div>

          {/* 富途 API 连接 */}
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-600">富途 API</span>
            <div className="flex items-center gap-2">
              <span
                className={`w-2 h-2 rounded-full ${
                  futuConnected ? "bg-green-500" : "bg-red-500"
                }`}
              ></span>
              <span
                className={`text-sm font-medium ${
                  futuConnected ? "text-green-600" : "text-red-600"
                }`}
              >
                {futuConnected ? "已连接" : "未连接"}
              </span>
            </div>
          </div>

          {/* WebSocket 连接 */}
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-600">实时连接</span>
            <div className="flex items-center gap-2">
              <span
                className={`w-2 h-2 rounded-full ${
                  isConnected ? "bg-green-500" : "bg-gray-400"
                }`}
              ></span>
              <span
                className={`text-sm font-medium ${
                  isConnected ? "text-green-600" : "text-gray-600"
                }`}
              >
                {isConnected ? "已连接" : "未连接"}
              </span>
            </div>
          </div>

          {/* 操作按钮 */}
          <div className="pt-2 border-t border-gray-200">
            {isRunning ? (
              <Button
                variant="danger"
                size="sm"
                onClick={onStopMonitor}
                disabled={loading}
                className="w-full"
              >
                停止监控
              </Button>
            ) : (
              <Button
                variant="primary"
                size="sm"
                onClick={onStartMonitor}
                disabled={loading}
                className="w-full"
              >
                启动监控
              </Button>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}
