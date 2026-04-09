// Socket.IO 事件类型定义

import type { Position } from './trade';
import type {
  DeltaUpdateData,
  MomentumIgnitionData,
  PriceLevelData,
  PocUpdateData,
  ScalpingSignalData,
  TrapAlertData,
  FakeBreakoutAlertData,
  TrueBreakoutConfirmData,
  FakeLiquidityAlertData,
  VwapExtensionAlertData,
  VwapExtensionClearData,
  StopLossAlertData,
  TickOutlierData,
} from './scalping';

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

  // Scalping 事件
  delta_update: (data: DeltaUpdateData) => void;
  momentum_ignition: (data: MomentumIgnitionData) => void;
  price_level_create: (data: PriceLevelData) => void;
  price_level_remove: (data: PriceLevelData) => void;
  price_level_break: (data: PriceLevelData) => void;
  poc_update: (data: PocUpdateData) => void;
  scalping_signal: (data: ScalpingSignalData) => void;
  trap_alert: (data: TrapAlertData) => void;
  fake_breakout_alert: (data: FakeBreakoutAlertData) => void;
  true_breakout_confirm: (data: TrueBreakoutConfirmData) => void;
  fake_liquidity_alert: (data: FakeLiquidityAlertData) => void;
  vwap_extension_alert: (data: VwapExtensionAlertData) => void;
  vwap_extension_clear: (data: VwapExtensionClearData) => void;
  stop_loss_alert: (data: StopLossAlertData) => void;
  tick_outlier: (data: TickOutlierData) => void;
}
