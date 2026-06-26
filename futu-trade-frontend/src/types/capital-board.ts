// 主力资金看板（Capital Board）类型 — 对齐后端 /api/capital-board/ranking

/** 行内并入的 Sniper 信号（精简） */
export interface CapitalBoardSniperSig {
  signal_type: string;   // mega_buy / accel_in / reversal_bull / mega_sell ...
  strength: number;      // 0-100，仅 mega_buy 有意义
  tier: string;          // opportunity / pulse / reference / watch
  time: string;          // HH:MM
  is_red: boolean;
  emoji: string;
}

/** 看板一行（一只股票的资金态 + 股价态 + 跨源确认） */
export interface CapitalBoardRow {
  stock_code: string;
  stock_name: string;
  last_price: number;
  intraday_pct: number;
  net_amount: number | null;          // 累计净额(逐笔)或净流入(富途)，元
  strength_mult: number | null;       // 力度倍数(相对自身)，仅逐笔口径有
  strength: string;                   // 强 / 中 / 弱
  direction: string;                  // inflow / outflow / pullback / distribution / flat
  big_buy_count: number;
  big_sell_count: number;
  big_order_threshold: number;        // 该股自适应大单门槛，元
  flow_source: string | null;         // tick(逐笔·主) / cache(富途·兜底)
  sniper_signals: CapitalBoardSniperSig[];
  is_resonance: boolean;              // 资金流入 + Sniper 买入共振
  held: boolean;
  sniper_only: boolean;               // 未达大单门槛、仅靠 Sniper 入榜
}

export interface CapitalBoardData {
  ranking: CapitalBoardRow[];
  pool_size: number;
  big_order_count: number;
  flow_source: string;                // 本次榜单主口径 tick / cache / none
}
