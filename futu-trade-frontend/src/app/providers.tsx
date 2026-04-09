// Providers 组件 - 包装所有全局 Provider

"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SocketProvider } from "@/lib/socket";
import { ToastProvider } from "@/components/common";
import { useState } from "react";

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

  return (
    <QueryClientProvider client={queryClient}>
      <SocketProvider>
        <ToastProvider>{children}</ToastProvider>
      </SocketProvider>
    </QueryClientProvider>
  );
}
