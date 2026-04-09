/** 后端返回的原始 K线数据（数组格式） */
export type RawKlineRow = [string, number, number, number, number, number];
// [date, open, close, low, high, volume]

/** LWC 蜡烛图数据 */
export interface CandleData {
  time: string;   // 'YYYY-MM-DD'
  open: number;
  high: number;
  low: number;
  close: number;
}

/** LWC 成交量数据 */
export interface VolumeData {
  time: string;
  value: number;
  color: string;  // 涨红跌绿
}

/** MA 均线数据点 */
export interface MADataPoint {
  time: string;
  value: number;
}

/** MA 均线配置 */
export interface MAConfig {
  period: number;
  color: string;
  label: string;
}

/** 后端交易买卖点数据 */
export interface BackendTradePoint {
  date: string;
  type: 'buy' | 'sell';
  price: number;
  text?: string;
}

/** 交易买卖点标记 */
export interface TradeMarker {
  time: string;
  position: 'aboveBar' | 'belowBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown';
  text: string;
}

/** KlineChart 组件 Props */
export interface KlineChartProps {
  stockCode: string;
  period?: 'day' | 'week' | 'month';
  height?: number;
  showVolume?: boolean;
  showMA?: boolean;
  showTradePoints?: boolean;
  enableRealtime?: boolean;
  className?: string;
}

/** MiniKlineChart 组件 Props */
export interface MiniKlineChartProps {
  stockCode: string;
  height?: number;
  className?: string;
}
