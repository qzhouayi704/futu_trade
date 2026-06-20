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

/** 强势股入场择时绿灯（盘中 30s 轮询，抓回调更及时） */
export function useEntryTiming() {
  return useQuery<EntryTimingData | null>({
    queryKey: ["entryTiming"],
    queryFn: async () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const r: any = await apiClient.get("/entry-timing/watch");
      return r?.success && r.data ? (r.data as EntryTimingData) : null;
    },
    staleTime: 15000,
    refetchInterval: 30000,
  });
}
