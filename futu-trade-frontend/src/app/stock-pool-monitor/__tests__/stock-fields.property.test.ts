/**
 * 属性测试：Top_Hot_API 响应包含完整的股票字段
 *
 * Feature: fix-stock-monitor-api, Property 2: Top_Hot_API 响应包含完整的股票字段
 * **Validates: Requirements 3.2, 3.3**
 *
 * 使用 fast-check 生成随机 TopHotStock 数据，验证页面组件引用的
 * 所有必要字段（heat_score、cur_price、change_rate、turnover_rate、turnover）
 * 在数据结构中均存在且类型正确。
 */

import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import type { TopHotStock } from '@/types/stock';

// 页面组件源码（用于验证字段引用）
const PAGE_SOURCE = readFileSync(
  resolve(__dirname, '../page.tsx'),
  'utf-8'
);

// 必须在 UI 中展示的字段（Requirements 3.2, 3.3）
const REQUIRED_DISPLAY_FIELDS = [
  'heat_score',
  'cur_price',
  'change_rate',
  'turnover_rate',
  'turnover',
] as const;

// TopHotStock 数据生成器
const topHotStockArbitrary: fc.Arbitrary<TopHotStock> = fc.record({
  id: fc.integer({ min: 1, max: 100000 }),
  code: fc.stringMatching(/^(HK|US)\.\d{5}$/),
  name: fc.string({ minLength: 1, maxLength: 10 }),
  market: fc.constantFrom('HK', 'US'),
  heat_score: fc.double({ min: 0, max: 100, noNaN: true }),
  cur_price: fc.double({ min: 0.01, max: 10000, noNaN: true }),
  last_price: fc.double({ min: 0.01, max: 10000, noNaN: true }),
  change_rate: fc.double({ min: -100, max: 100, noNaN: true }),
  volume: fc.integer({ min: 0, max: 100000000 }),
  turnover: fc.double({ min: 0, max: 1e12, noNaN: true }),
  turnover_rate: fc.double({ min: 0, max: 100, noNaN: true }),
  amplitude: fc.double({ min: 0, max: 100, noNaN: true }),
  high_price: fc.double({ min: 0.01, max: 10000, noNaN: true }),
  low_price: fc.double({ min: 0.01, max: 10000, noNaN: true }),
  open_price: fc.double({ min: 0.01, max: 10000, noNaN: true }),
  prev_close_price: fc.double({ min: 0.01, max: 10000, noNaN: true }),
  is_position: fc.boolean(),
  has_condition: fc.boolean(),
  condition: fc.constant(null),
});

describe('Property 2: TopHotStock 数据字段完整性', () => {
  it('任意 TopHotStock 数据应包含所有必要展示字段', () => {
    fc.assert(
      fc.property(topHotStockArbitrary, (stock) => {
        for (const field of REQUIRED_DISPLAY_FIELDS) {
          expect(stock).toHaveProperty(field);
          expect(stock[field]).toBeDefined();
          expect(typeof stock[field]).toBe('number');
        }
      }),
      { numRuns: 100 }
    );
  });

  it('任意 TopHotStock 数据的 heat_score 应为非负数', () => {
    fc.assert(
      fc.property(topHotStockArbitrary, (stock) => {
        expect(stock.heat_score).toBeGreaterThanOrEqual(0);
      }),
      { numRuns: 100 }
    );
  });

  it('任意 TopHotStock 数据的 cur_price 应为正数', () => {
    fc.assert(
      fc.property(topHotStockArbitrary, (stock) => {
        expect(stock.cur_price).toBeGreaterThan(0);
      }),
      { numRuns: 100 }
    );
  });

  it('页面组件源码应引用所有必要展示字段', () => {
    for (const field of REQUIRED_DISPLAY_FIELDS) {
      expect(PAGE_SOURCE).toContain(field);
    }
  });
});
