// WebSocket → React Query 缓存同步
// 把实时推送写进共享缓存，替代各组件各自的 socket 监听 + setState，
// 保留推送低延迟的同时让所有消费同一 queryKey 的组件一起更新。

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSocket } from "@/lib/socket";
import type { SniperSignal } from "@/types/trade";

export function useSocketQuerySync() {
  const { socket } = useSocket();
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!socket) return;

    const onSniperSignal = (data: SniperSignal) => {
      queryClient.setQueryData<SniperSignal[]>(["sniperSignals"], (prev) => {
        const updated = [data, ...(prev ?? [])];
        const seen = new Set<string>();
        return updated.filter((s) => {
          const key = `${s.stock_code}:${s.signal_type}:${s.time}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });
      });
    };

    socket.on("sniper_signal", onSniperSignal);
    return () => {
      socket.off("sniper_signal", onSniperSignal);
    };
  }, [socket, queryClient]);
}
