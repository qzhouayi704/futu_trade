// 持仓做T助手 API — 高抛低吸两腿状态机（先告警·后半自动）

import apiClient from "./client";
import type { ApiResponse } from "@/types";

export interface TLeg {
  id: number;
  stock_code: string;
  stock_name: string;
  trade_date: string;
  state: string; // IDLE/SELL_PENDING/SOLD_WAITING_BUYBACK/BUY_PENDING/COMPLETED/EXPIRED
  mode: string; // alert/semi/full
  original_qty: number;
  sold_qty: number;
  sold_price: number | null;
  sold_time: string | null;
  sell_reason: string | null;
  target_buyback_price: number | null;
  bought_price: number | null;
  bought_time: string | null;
  buy_reason: string | null;
  peak_after_sell: number | null;
  trough_after_sell: number | null;
  realized_pnl: number | null;
}

export interface TTradeStatus {
  trade_date: string;
  enabled: boolean;
  mode: string;
  config: Record<string, number>;
  realized_pnl_today: number;
  legs: TLeg[];
  by_code: Record<string, TLeg>;
}

export const tTradeApi = {
  getStatus: (): Promise<ApiResponse<TTradeStatus>> =>
    apiClient.get("/trading/t-trade/status"),
  getConfig: (): Promise<ApiResponse> => apiClient.get("/trading/t-trade/config"),
  setConfig: (body: { enabled?: boolean; mode?: string }): Promise<ApiResponse> =>
    apiClient.post("/trading/t-trade/config", body),
  // Phase 2：半自动一键确认 / 取消
  confirm: (legId: number): Promise<ApiResponse> =>
    apiClient.post("/trading/t-trade/confirm", { leg_id: legId }),
  cancel: (legId: number): Promise<ApiResponse> =>
    apiClient.post("/trading/t-trade/cancel", { leg_id: legId }),
};
