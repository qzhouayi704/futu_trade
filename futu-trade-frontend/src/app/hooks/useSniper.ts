// Sniper / 盘口 / 持仓教练 — 共享 React Query 钩子
// 多个组件共用同一 queryKey → RQ 自动去重网络请求（修复 /sniper/signals 重复拉取）

import { useQuery } from "@tanstack/react-query";
import { sniperApi } from "@/lib/api/sniper";
import apiClient from "@/lib/api/client";
import type { SniperSignal } from "@/types/trade";

/** 今日全部狙击信号（DailyPickCard + UnifiedSignalFeed 共用 → 去重为一次请求） */
export function useSniperSignals() {
  return useQuery<SniperSignal[]>({
    queryKey: ["sniperSignals"],
    queryFn: async () => {
      const r = await sniperApi.getSignals();
      return r.success && Array.isArray(r.data) ? (r.data as SniperSignal[]) : [];
    },
    staleTime: 60000,
    refetchInterval: 180000,
  });
}

/** TOP 机会/风险排行榜 */
export function useSniperRanking() {
  return useQuery({
    queryKey: ["sniperRanking"],
    queryFn: async () => {
      const r = await sniperApi.getRanking();
      return r.success && r.data ? r.data : null;
    },
    staleTime: 120000,
    refetchInterval: 180000,
  });
}

/** 批量盘口判定(追高/洗盘)；codes 为空时不请求 */
export function useSniperTapeVerdicts(codes: string) {
  return useQuery<Record<string, unknown>>({
    queryKey: ["sniperTapeVerdicts", codes],
    queryFn: async () => {
      if (!codes) return {};
      const r = await sniperApi.getTapeVerdicts(codes);
      return r.success && r.data ? (r.data as Record<string, unknown>) : {};
    },
    enabled: !!codes,
    staleTime: 30000,
    refetchInterval: 60000,
  });
}

/** 持仓教练卡（纪律：今日交易计数/成本买高/洗盘别割） */
export function usePositionsCoach() {
  return useQuery<Record<string, unknown>[]>({
    queryKey: ["positionsCoach"],
    queryFn: async () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const r: any = await apiClient.get("/trading/positions/coach");
      return r?.success && Array.isArray(r.data) ? r.data : [];
    },
    staleTime: 15000,
    refetchInterval: 15000,
  });
}
