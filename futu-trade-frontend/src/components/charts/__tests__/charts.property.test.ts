import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { transformKlineData, transformVolumeData, transformTradePoints } from '../transforms';
import { calculateMA } from '../indicators';
import type { RawKlineRow, BackendTradePoint, CandleData } from '@/types/kline';

// 生成有效的日期字符串（YYYY-MM-DD 格式）
const dateArbitrary = fc
  .tuple(
    fc.integer({ min: 2020, max: 2025 }),
    fc.integer({ min: 1, max: 12 }),
    fc.integer({ min: 1, max: 28 }) // 使用 28 避免月份天数问题
  )
  .map(([year, month, day]) =>
    `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
  );

// 生成有效的价格数字（排除 NaN、Infinity）
const priceArbitrary = fc.double({ min: 1, max: 1000, noNaN: true });

// 生成有效的成交量数字
const volumeArbitrary = fc.double({ min: 0, max: 1000000, noNaN: true });

/**
 * 属性 P1：K线数据转换保持数据完整性
 * 验证需求：1.2
 */
describe('transformKlineData - Property P1: 数据完整性', () => {
  it('应保持数组长度不变', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.tuple(
            dateArbitrary,
            priceArbitrary,
            priceArbitrary,
            priceArbitrary,
            priceArbitrary,
            volumeArbitrary
          )
        ),
        (rawData) => {
          const result = transformKlineData(rawData as RawKlineRow[]);
          expect(result.length).toBe(rawData.length);
        }
      )
    );
  });

  it('应正确映射所有字段', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.tuple(
            dateArbitrary,
            priceArbitrary,
            priceArbitrary,
            priceArbitrary,
            priceArbitrary,
            volumeArbitrary
          ),
          { minLength: 1 }
        ),
        (rawData) => {
          const result = transformKlineData(rawData as RawKlineRow[]);

          result.forEach((candle, i) => {
            const [date, open, close, low, high] = rawData[i];
            expect(candle.time).toBe(date);
            expect(candle.open).toBe(open);
            expect(candle.close).toBe(close);
            expect(candle.low).toBe(low);
            expect(candle.high).toBe(high);
          });
        }
      )
    );
  });
});

/**
 * 属性 P2：成交量数据转换涨跌颜色正确
 * 验证需求：1.3, 1.4
 */
describe('transformVolumeData - Property P2: 涨跌颜色', () => {
  it('应保持数组长度不变', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.tuple(
            dateArbitrary,
            priceArbitrary,
            priceArbitrary,
            priceArbitrary,
            priceArbitrary,
            volumeArbitrary
          )
        ),
        (rawData) => {
          const result = transformVolumeData(rawData as RawKlineRow[]);
          expect(result.length).toBe(rawData.length);
        }
      )
    );
  });

  it('涨（close >= open）应为红色，跌（close < open）应为绿色', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.tuple(
            dateArbitrary,
            priceArbitrary,
            priceArbitrary,
            priceArbitrary,
            priceArbitrary,
            volumeArbitrary
          ),
          { minLength: 1 }
        ),
        (rawData) => {
          const result = transformVolumeData(rawData as RawKlineRow[]);

          result.forEach((volume, i) => {
            const [_date, open, close] = rawData[i];
            if (close >= open) {
              expect(volume.color).toBe('#ef4444'); // 涨红
            } else {
              expect(volume.color).toBe('#22c55e'); // 跌绿
            }
          });
        }
      )
    );
  });
});

/**
 * 属性 P3：MA 均线计算值在窗口范围内
 * 验证需求：2.1, 2.3
 */
describe('calculateMA - Property P3: MA 值范围', () => {
  it('当数据长度小于周期时应返回空数组', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            time: dateArbitrary,
            open: priceArbitrary,
            high: priceArbitrary,
            low: priceArbitrary,
            close: priceArbitrary,
          }),
          { maxLength: 10 }
        ),
        fc.integer({ min: 11, max: 200 }),
        (data, period) => {
          const result = calculateMA(data as CandleData[], period);
          expect(result.length).toBe(0);
        }
      )
    );
  });

  it('返回数组长度应为 data.length - period + 1', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            time: dateArbitrary,
            open: priceArbitrary,
            high: priceArbitrary,
            low: priceArbitrary,
            close: priceArbitrary,
          }),
          { minLength: 5, maxLength: 100 }
        ),
        fc.integer({ min: 1, max: 5 }),
        (data, period) => {
          const result = calculateMA(data as CandleData[], period);
          const expectedLength = Math.max(0, data.length - period + 1);
          expect(result.length).toBe(expectedLength);
        }
      )
    );
  });

  it('每个 MA 值应在对应窗口的最小值和最大值之间', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            time: dateArbitrary,
            open: priceArbitrary,
            high: priceArbitrary,
            low: priceArbitrary,
            close: priceArbitrary,
          }),
          { minLength: 10, maxLength: 50 }
        ),
        fc.integer({ min: 2, max: 10 }),
        (data, period) => {
          const result = calculateMA(data as CandleData[], period);

          result.forEach((ma, i) => {
            const windowStart = i;
            const windowEnd = i + period;
            const windowCloses = data.slice(windowStart, windowEnd).map(d => d.close);
            const min = Math.min(...windowCloses);
            const max = Math.max(...windowCloses);

            expect(ma.value).toBeGreaterThanOrEqual(min);
            expect(ma.value).toBeLessThanOrEqual(max);
          });
        }
      )
    );
  });
});

/**
 * 属性 P4：交易点标记转换方向正确
 * 验证需求：3.4
 */
describe('transformTradePoints - Property P4: 交易点方向', () => {
  it('买入信号应为 belowBar 和 arrowUp', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            date: dateArbitrary,
            type: fc.constant('buy' as const),
            price: priceArbitrary,
            text: fc.option(fc.string(), { nil: undefined }),
          }),
          { minLength: 1 }
        ),
        (points) => {
          const result = transformTradePoints(points as BackendTradePoint[]);

          result.forEach((marker) => {
            expect(marker.position).toBe('belowBar');
            expect(marker.shape).toBe('arrowUp');
          });
        }
      )
    );
  });

  it('卖出信号应为 aboveBar 和 arrowDown', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            date: dateArbitrary,
            type: fc.constant('sell' as const),
            price: priceArbitrary,
            text: fc.option(fc.string(), { nil: undefined }),
          }),
          { minLength: 1 }
        ),
        (points) => {
          const result = transformTradePoints(points as BackendTradePoint[]);

          result.forEach((marker) => {
            expect(marker.position).toBe('aboveBar');
            expect(marker.shape).toBe('arrowDown');
          });
        }
      )
    );
  });

  it('输出数量应等于输入数量', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            date: dateArbitrary,
            type: fc.oneof(fc.constant('buy' as const), fc.constant('sell' as const)),
            price: priceArbitrary,
            text: fc.option(fc.string(), { nil: undefined }),
          })
        ),
        (points) => {
          const result = transformTradePoints(points as BackendTradePoint[]);
          expect(result.length).toBe(points.length);
        }
      )
    );
  });
});
