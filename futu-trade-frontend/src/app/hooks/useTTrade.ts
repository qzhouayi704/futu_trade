// 持仓做T助手 — React Query 钩子（状态轮询；半自动确认/取消留待 Phase 2）

import { useQuery } from "@tanstack/react-query";
import { tTradeApi, type TTradeStatus } from "@/lib/api/t-trade";

/** 当日做T状态（开关/模式 + 每股最新腿 + 已实现盈亏），约10s轮询 */
export function useTTradeStatus() {
  return useQuery<TTradeStatus | null>({
    queryKey: ["tTradeStatus"],
    queryFn: async () => {
      const r = await tTradeApi.getStatus();
      return r.success && r.data ? r.data : null;
    },
    staleTime: 10000,
    refetchInterval: 10000,
  });
}
