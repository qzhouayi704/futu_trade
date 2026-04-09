import type { CandleData, MADataPoint } from '@/types/kline';

/**
 * 计算简单移动平均线 (SMA)
 * @param data - K线数据数组
 * @param period - 窗口大小
 * @returns MA 数据点数组（长度 = data.length - period + 1）
 *
 * 性质：
 * - 当 data.length < period 时返回空数组
 * - 每个 MA 值 >= 窗口内最小值，<= 窗口内最大值
 * - 返回数组长度 = max(0, data.length - period + 1)
 */
export function calculateMA(
  data: CandleData[],
  period: number
): MADataPoint[] {
  if (data.length < period || period < 1) {
    return [];
  }

  const result: MADataPoint[] = [];

  for (let i = period - 1; i < data.length; i++) {
    let sum = 0;
    for (let j = 0; j < period; j++) {
      sum += data[i - j].close;
    }
    const avg = sum / period;

    result.push({
      time: data[i].time,
      value: avg,
    });
  }

  return result;
}

/**
 * 批量计算多条 MA 均线
 * @param data - K线数据数组
 * @param periods - 周期数组，如 [5, 10, 20, 60]
 * @returns 多条 MA 均线的映射表
 */
export function calculateMultipleMA(
  data: CandleData[],
  periods: number[]
): Record<number, MADataPoint[]> {
  const result: Record<number, MADataPoint[]> = {};

  for (const period of periods) {
    result[period] = calculateMA(data, period);
  }

  return result;
}
