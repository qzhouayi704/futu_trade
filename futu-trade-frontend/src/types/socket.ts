// Socket.IO 事件类型定义

import type { Position } from './trade';

export interface QuoteData {
  code: string;
  name?: string;
  stock_code?: string;
  stock_name?: string;
  current_price?: number;
  last_price?: number;
  change_percent?: number;
  change_rate?: number;
  change_pct?: number;
  change_val?: number;
  volume?: number;
  turnover_rate?: number;
  update_time?: string;
}

export interface SignalData {
  id: number;
  stock_id: number;
  stock_code: string;
  stock_name: string;
  signal_type: string;
  signal_price: number;
  target_price?: number;
  stop_loss_price?: number;
  condition_text?: string;
  is_executed: boolean;
  executed_time?: string;
  created_at: string;
  strategy_id?: number;
  strategy_name?: string;
}

export interface ConditionData {
  id: number;
  name: string;
  description?: string;
  is_active: boolean;
  created_at: string;
}

export interface SocketEvents {
  // 客户端事件
  connect: () => void;
  disconnect: () => void;
  request_update: () => void;

  // 服务端事件
  status: (data: { connected: boolean }) => void;
  signals_update: (data: { signals: SignalData[] }) => void;
  positions_update: (data: { positions: Position[] }) => void;
  quotes_update: (data: { quotes: QuoteData[] }) => void;
  conditions_update: (data: { conditions: ConditionData[] }) => void;
  monitor_status: (data: { is_running: boolean }) => void;
  system_status: (data: { is_running: boolean; market?: string }) => void;
}
