// Dashboard API Hooks - 使用 React Query

import { useQuery } from "@tanstack/react-query";
import { systemApi, stockApi, tradeApi, strategyApi } from "@/lib/api";
import type { Stats, PlateStrength, HighTurnoverStock } from "@/types/stock";

export function useSystemStatus() {
  return useQuery({
    queryKey: ["systemStatus"],
    queryFn: async () => {
      const r = await systemApi.getStatus();
      return r.success && r.data ? r.data : null;
    },
    staleTime: 30000,
    refetchInterval: 30000,
  });
}

export function useStats() {
  return useQuery({
    queryKey: ["stats"],
    queryFn: async () => {
      const [h, p] = await Promise.all([
        systemApi.getMonitorHealth(),
        tradeApi.getPositions(),
      ]);
      if (h.success && h.data) {
        return {
          stockPoolCount: h.data.stock_pool?.total_count || 0,
          subscribedCount: h.data.subscription?.subscribed_count || 0,
          hotStockCount: 0,
          positionCount: p.data?.length || 0,
        } as Stats;
      }
      return null;
    },
    staleTime: 60000,
  });
}

export function usePlateStrength() {
  return useQuery({
    queryKey: ["plateStrength"],
    queryFn: async () => {
      const r = await strategyApi.getPlateStrength();
      return r.success && r.data ? (r.data.plates as PlateStrength[]) || [] : [];
    },
    staleTime: 300000,
  });
}


export function useHotStocks(limit: number = 5) {
  return useQuery({
    queryKey: ["hotStocks", limit],
    queryFn: async () => {
      const r = await stockApi.getTopHotStocks({ limit });
      if (!r.success || !r.data) return [];
      return (r.data.stocks || []).map((s) => ({
        stock_code: s.code,
        stock_name: s.name,
        market: s.market,
        current_price: s.cur_price,
        change_pct: s.change_rate,
        heat_score: s.heat_score,
        turnover_rate: s.turnover_rate,
        volume: s.volume,
      }));
    },
    staleTime: 300000,
  });
}

export function usePositions() {
  return useQuery({
    queryKey: ["positions"],
    queryFn: async () => {
      try {
        const r = await tradeApi.getPositionsStandalone();
        if (r.success && r.data?.positions) {
          return r.data.positions.map((p) => ({
            stock_code: p.stock_code,
            stock_name: p.stock_name,
            quantity: p.qty,
            avg_price: p.cost_price,
            current_price: p.nominal_price,
            market_value: p.market_val,
            profit_loss: p.pl_val,
            profit_loss_pct: p.pl_ratio,
          }));
        }
      } catch {
        try {
          const f = await tradeApi.getPositions();
          if (f.success && f.data) {
            return f.data.map((p) => ({
              stock_code: p.stock_code,
              stock_name: p.stock_name,
              quantity: p.qty || p.quantity || 0,
              avg_price: p.cost_price,
              current_price: p.current_price || 0,
              market_value: p.market_value,
              profit_loss: p.pl_val,
              profit_loss_pct: p.pl_ratio,
            }));
          }
        } catch { /* ignore */ }
      }
      return [];
    },
    staleTime: 30000,
    retry: 1,
  });
}

export function useHighTurnoverStocks(limit: number = 5) {
  return useQuery<HighTurnoverStock[]>({
    queryKey: ["highTurnoverStocks", limit],
    queryFn: async () => {
      const r = await stockApi.getHighTurnoverStocks({ limit });
      return r.success && r.data ? r.data.stocks || [] : [];
    },
    staleTime: 60000,
  });
}
