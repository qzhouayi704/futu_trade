// 入场择时（实验·只读）— 强势股低吸择时绿灯
// 数据来自后端 /api/entry-timing/watch；纯展示，不参与下单。

import { useQuery } from "@tanstack/react-query";
import apiClient from "@/lib/api/client";

export interface EntryTimingItem {
  stock_code: string;
  stock_name: string;
  gain_today: number; // 今日涨幅(现价/前收-1) %
  light: "green" | "red" | "neutral";
  label: string;
  reason: string;
  mom5: number | null; // 近5分钟涨跌 %
  ofi15: number | null; // 近15分钟主动买卖单流 [-1,1]
  pos_range: number | null; // 日内价位 [0,1]
  last_price: number | null;
  stale: boolean;
}

export interface EntryTimingData {
  as_of: string;
  market_open: boolean;
  pool_size: number;
  experimental: boolean;
  items: EntryTimingItem[];
}

/** 强势股入场择时绿灯（盘中 15s 轮询，抓回调更及时） */
export function useEntryTiming() {
  return useQuery<EntryTimingData | null>({
    queryKey: ["entryTiming"],
    queryFn: async () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const r: any = await apiClient.get("/entry-timing/watch");
      return r?.success && r.data ? (r.data as EntryTimingData) : null;
    },
    staleTime: 7500,
    refetchInterval: 15000,
  });
}

// 历史：某日全部 🟢/🔴 触发 + 每条事后走势（复盘 / 真实命中率）
export interface EntryTimingHistoryItem {
  time: string; // HH:MM 触发时刻
  stock_code: string;
  stock_name: string;
  light: "green" | "red";
  label: string;
  reason: string;
  trigger_price: number | null;
  gain_today: number | null;
  mom5: number | null;
  ofi15: number | null;
  pos_range: number | null;
  ret_30m: number | null; // 触发后+30min 相对触发价 %
  ret_last: number | null; // 至今/收盘 相对触发价 %
  max_up: number | null; // 触发后最高 相对触发价 %
  max_dn: number | null; // 触发后最低 相对触发价 %
  last_price: number | null;
}

export interface EntryTimingHistoryData {
  trade_date: string;
  count: number;
  green_count: number;
  red_count: number;
  experimental: boolean;
  items: EntryTimingHistoryItem[];
}

/** 入场择时历史（某日全部信号 + 事后走势）；date 为空=今日 */
export function useEntryTimingHistory(date?: string) {
  return useQuery<EntryTimingHistoryData | null>({
    queryKey: ["entryTimingHistory", date ?? "today"],
    queryFn: async () => {
      const qs = date ? `?date=${encodeURIComponent(date)}` : "";
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const r: any = await apiClient.get(`/entry-timing/history${qs}`);
      return r?.success && r.data ? (r.data as EntryTimingHistoryData) : null;
    },
    staleTime: 30000,
    refetchInterval: 60000,
  });
}
