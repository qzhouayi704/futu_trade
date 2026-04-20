// Providers 组件 - 包装所有全局 Provider

"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SocketProvider } from "@/lib/socket";
import { ToastProvider } from "@/components/common";
import { useState } from "react";
import { useBackendReady } from "./hooks/useBackendReady";

export function Providers({ children }: { children: React.ReactNode }) {
  // 为每个客户端创建一个新的 QueryClient 实例
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000, // 1 分钟
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  const { ready, error } = useBackendReady();

  // 后端未就绪时显示加载界面，阻止所有 API 请求和 Socket.IO 连接
  if (!ready) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="text-center">
          {error ? (
            <>
              <div className="text-destructive text-lg font-semibold mb-2">
                {error}
              </div>
              <div className="text-muted-foreground text-sm">
                请确保后端服务已启动（端口 5001）
              </div>
            </>
          ) : (
            <>
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mx-auto mb-4" />
              <div className="text-muted-foreground">系统启动中，请稍候...</div>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <QueryClientProvider client={queryClient}>
      <SocketProvider>
        <ToastProvider>{children}</ToastProvider>
      </SocketProvider>
    </QueryClientProvider>
  );
}
