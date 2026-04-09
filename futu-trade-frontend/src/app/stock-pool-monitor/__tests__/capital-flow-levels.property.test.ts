/**
 * 属性测试：资金流向分级数据提取
 *
 * Feature: capital-flow-dashboard, Property 4: 资金流向分级数据提取
 * **Validates: 4.2**
 *
 * 使用 fast-check 生成随机 CapitalFlowData，验证 extractFlowLevels 提取的
 * 分级数据结构正确、金额非负、主力净流入计算一致。
 */

import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import type { CapitalFlowData } from '@/types/enhanced-heat';
import { extractFlowLevels } from '../components/CapitalFlowDetail';

// 非负金额生成器
const amountArb = fc.double({ min: 0, max: 1e12, noNaN: true });

// CapitalFlowData 生成器：main_net_inflow 由超大单和大单计算得出
const capitalFlowDataArbitrary: fc.Arbitrary<CapitalFlowData> = fc
  .record({
    stock_code: fc.stringMatching(/^(HK|US)\.\d{5}$/),
    timestamp: fc.date().map((d) => d.toISOString()),
    super_large_inflow: amountArb,
    large_inflow: amountArb,
    medium_inflow: amountArb,
    small_inflow: amountArb,
    super_large_outflow: amountArb,
    large_outflow: amountArb,
    medium_outflow: amountArb,
    small_outflow: amountArb,
    net_inflow_ratio: fc.double({ min: -100, max: 100, noNaN: true }),
    big_order_buy_ratio: fc.double({ min: 0, max: 100, noNaN: true }),
    capital_score: fc.double({ min: 0, max: 100, noNaN: true }),
  })
  .map((r) => ({
    ...r,
    main_net_inflow:
      r.super_large_inflow + r.large_inflow - r.super_large_outflow - r.large_outflow,
  }));

describe('Property 4: 资金流向分级数据提取', () => {
  it('extractFlowLevels 应返回 4 个级别（超大单、大单、中单、小单）', () => {
    fc.assert(
      fc.property(capitalFlowDataArbitrary, (data) => {
        const levels = extractFlowLevels(data);
        expect(levels).toHaveLength(4);
        expect(levels.map((l) => l.name)).toEqual(['超大单', '大单', '中单', '小单']);
      }),
      { numRuns: 100 },
    );
  });

  it('每个级别的 inflow 和 outflow 均为非负数', () => {
    fc.assert(
      fc.property(capitalFlowDataArbitrary, (data) => {
        const levels = extractFlowLevels(data);
        for (const level of levels) {
          expect(level.inflow).toBeGreaterThanOrEqual(0);
          expect(level.outflow).toBeGreaterThanOrEqual(0);
        }
      }),
      { numRuns: 100 },
    );
  });

  it('主力净流入 = (超大单流入 + 大单流入) - (超大单流出 + 大单流出)', () => {
    fc.assert(
      fc.property(capitalFlowDataArbitrary, (data) => {
        const levels = extractFlowLevels(data);
        const mainNetInflow =
          levels[0].inflow + levels[1].inflow - levels[0].outflow - levels[1].outflow;
        expect(mainNetInflow).toBeCloseTo(data.main_net_inflow, 5);
      }),
      { numRuns: 100 },
    );
  });
});
