import type {
  RawKlineRow,
  CandleData,
  VolumeData,
  BackendTradePoint,
  TradeMarker,
} from '@/types/kline';

/**
 * 将后端 K线数组转换为 LWC CandleData
 * 后端格式: [date, open, close, low, high, volume]
 * LWC 格式: { time, open, high, low, close }
 */
export function transformKlineData(raw: RawKlineRow[]): CandleData[] {
  return raw.map(([date, open, close, low, high]) => ({
    time: date,
    open,
    high,
    low,
    close,
  }));
}

/**
 * 将后端 K线数组转换为 LWC VolumeData
 * 涨（close >= open）用红色，跌（close < open）用绿色
 */
export function transformVolumeData(raw: RawKlineRow[]): VolumeData[] {
  return raw.map(([date, open, close, _low, _high, volume]) => ({
    time: date,
    value: volume,
    color: close >= open ? '#ef4444' : '#22c55e', // 涨红跌绿
  }));
}

/**
 * 将后端 TradePoint 转换为 LWC SeriesMarker
 */
export function transformTradePoints(points: BackendTradePoint[]): TradeMarker[] {
  return points.map((point) => ({
    time: point.date,
    position: point.type === 'buy' ? 'belowBar' : 'aboveBar',
    color: point.type === 'buy' ? '#22c55e' : '#ef4444',
    shape: point.type === 'buy' ? 'arrowUp' : 'arrowDown',
    text: point.text || (point.type === 'buy' ? '买' : '卖'),
  }));
}
