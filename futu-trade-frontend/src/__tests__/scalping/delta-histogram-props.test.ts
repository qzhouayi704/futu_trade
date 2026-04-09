/**
 * 属性测试：DeltaHistogram 颜色映射
 *
 * Feature: intraday-scalping-engine
 * Property 10: Delta 颜色映射
 * **Validates: Requirements 7.2, 7.3, 7.4**
 *
 * 测试策略：
 * - 直接导入 getDeltaColor 工具函数进行纯逻辑验证
 * - 重新实现 isExtremeDelta 内部函数，验证极值检测逻辑
 * - 不需要 jsdom 或 React 渲染，纯数据驱动
 */

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { getDeltaColor } from "@/app/enhanced-heat/components/scalping/DeltaHistogram";
import type { DeltaUpdateData } from "@/types/scalping";

// ==================== 颜色常量（与组件保持一致） ====================

const COLOR_POSITIVE = "#26a69a";
const COLOR_NEGATIVE = "#ef5350";
const COLOR_EXTREME_POSITIVE = "#00e676";
const COLOR_EXTREME_NEGATIVE = "#ff1744";

// ==================== 极值检测参数 ====================

const EXTREME_LOOKBACK = 20;
const EXTREME_MULTIPLIER = 2;

// ==================== 重新实现 isExtremeDelta（与组件内部逻辑一致） ====================

/**
 * 判断当前 delta 是否为极值柱
 * 计算最近 lookback 个周期的 |delta| 均值，
 * 当前 |delta| 超过该均值 × multiplier 时为极值。
 */
function isExtremeDelta(
  currentIndex: number,
  deltaData: DeltaUpdateData[],
  lookback: number = EXTREME_LOOKBACK,
  multiplier: number = EXTREME_MULTIPLIER,
): boolean {
  const start = Math.max(0, currentIndex - lookback);
  const end = currentIndex;
  if (start >= end) return false;
  let sum = 0;
  for (let i = start; i < end; i++) {
    sum += Math.abs(deltaData[i].delta);
  }
  const avg = sum / (end - start);
  if (avg === 0) return false;
  return Math.abs(deltaData[currentIndex].delta) > avg * multiplier;
}

// ==================== fast-check 生成策略 ====================

/** 生成随机股票代码 */
const stockCodeArb = fc.stringMatching(/^(HK|US)\.\d{5}$/);

/** 生成随机 ISO 时间戳 */
const timestampArb = fc
  .integer({ min: 1577836800000, max: 1924905600000 })
  .map((ms) => new Date(ms).toISOString());

/** 生成非零 delta 值（排除 0，因为 0 不属于正或负） */
const nonZeroDeltaArb = fc.oneof(
  fc.float({ min: Math.fround(0.01), max: Math.fround(100000), noNaN: true }),
  fc.float({ min: Math.fround(-100000), max: Math.fround(-0.01), noNaN: true }),
);

/** 生成正 delta 值 */
const positiveDeltaArb = fc.float({ min: Math.fround(0.01), max: Math.fround(100000), noNaN: true });

/** 生成负 delta 值 */
const negativeDeltaArb = fc.float({ min: Math.fround(-100000), max: Math.fround(-0.01), noNaN: true });

/** 生成 DeltaUpdateData */
const deltaUpdateArb = (deltaArb: fc.Arbitrary<number>): fc.Arbitrary<DeltaUpdateData> =>
  fc.record({
    stock_code: stockCodeArb,
    delta: deltaArb,
    volume: fc.integer({ min: 100, max: 1000000 }),
    timestamp: timestampArb,
    period_seconds: fc.constantFrom(10, 60),
  });

// ── Property 10: Delta 颜色映射 ──────────────────────────────
// Feature: intraday-scalping-engine
// Property 10: Delta 颜色映射
// **Validates: Requirements 7.2, 7.3, 7.4**

describe("Property 10: Delta 颜色映射", () => {
  // ── 7.2: 正 delta → 绿色 ──
  it("对于任意正 delta 值且非极值，颜色应为正常绿色 (#26a69a)", () => {
    fc.assert(
      fc.property(positiveDeltaArb, (delta) => {
        const color = getDeltaColor(delta, false);
        expect(color).toBe(COLOR_POSITIVE);
      }),
      { numRuns: 100 },
    );
  });

  // ── 7.3: 负 delta → 红色 ──
  it("对于任意负 delta 值且非极值，颜色应为正常红色 (#ef5350)", () => {
    fc.assert(
      fc.property(negativeDeltaArb, (delta) => {
        const color = getDeltaColor(delta, false);
        expect(color).toBe(COLOR_NEGATIVE);
      }),
      { numRuns: 100 },
    );
  });

  // ── 7.4: 正极值 → 高亮绿色 ──
  it("对于任意正 delta 值且为极值，颜色应为极值绿色 (#00e676)", () => {
    fc.assert(
      fc.property(positiveDeltaArb, (delta) => {
        const color = getDeltaColor(delta, true);
        expect(color).toBe(COLOR_EXTREME_POSITIVE);
      }),
      { numRuns: 100 },
    );
  });

  // ── 7.4: 负极值 → 高亮红色 ──
  it("对于任意负 delta 值且为极值，颜色应为极值红色 (#ff1744)", () => {
    fc.assert(
      fc.property(negativeDeltaArb, (delta) => {
        const color = getDeltaColor(delta, true);
        expect(color).toBe(COLOR_EXTREME_NEGATIVE);
      }),
      { numRuns: 100 },
    );
  });

  // ── 颜色映射完备性：正/负 × 极值/非极值 = 4 种组合 ──
  it("对于任意非零 delta 值和任意极值标记，颜色应为四种之一", () => {
    fc.assert(
      fc.property(nonZeroDeltaArb, fc.boolean(), (delta, extreme) => {
        const color = getDeltaColor(delta, extreme);
        const validColors = [
          COLOR_POSITIVE,
          COLOR_NEGATIVE,
          COLOR_EXTREME_POSITIVE,
          COLOR_EXTREME_NEGATIVE,
        ];
        expect(validColors).toContain(color);
      }),
      { numRuns: 100 },
    );
  });

  // ── 极值检测：|delta| > 近 20 周期均值 × 2 时为极值 ──
  it("当 |delta| 超过近 20 周期 |delta| 均值的 2 倍时，应被标记为极值", () => {
    fc.assert(
      fc.property(
        // 生成 20 个小 delta 值作为历史数据
        fc.array(
          deltaUpdateArb(fc.float({ min: Math.fround(1), max: Math.fround(10), noNaN: true })),
          { minLength: 20, maxLength: 20 },
        ),
        // 生成一个大 delta 值作为当前值（确保超过均值 × 2）
        fc.float({ min: Math.fround(1), max: Math.fround(10), noNaN: true }),
        (historyData, baseValue) => {
          // 计算历史均值
          const avgDelta = historyData.reduce((s, d) => s + Math.abs(d.delta), 0) / historyData.length;
          // 构造一个超过均值 × 2 的极值 delta
          const extremeDelta = avgDelta * EXTREME_MULTIPLIER + baseValue;
          const currentItem: DeltaUpdateData = {
            stock_code: "US.00001",
            delta: extremeDelta,
            volume: 1000,
            timestamp: new Date().toISOString(),
            period_seconds: 10,
          };
          const allData = [...historyData, currentItem];
          const result = isExtremeDelta(allData.length - 1, allData);
          expect(result).toBe(true);
        },
      ),
      { numRuns: 100 },
    );
  });

  // ── 非极值：|delta| <= 近 20 周期均值 × 2 时不为极值 ──
  it("当 |delta| 不超过近 20 周期 |delta| 均值的 2 倍时，不应被标记为极值", () => {
    fc.assert(
      fc.property(
        // 生成 20 个正 delta 值作为历史数据（确保均值 > 0）
        fc.array(
          deltaUpdateArb(fc.float({ min: Math.fround(10), max: Math.fround(100), noNaN: true })),
          { minLength: 20, maxLength: 20 },
        ),
        // 生成一个 0~1 之间的比例因子
        fc.float({ min: Math.fround(0.01), max: Math.fround(0.99), noNaN: true }),
        (historyData, ratio) => {
          // 计算历史均值
          const avgDelta = historyData.reduce((s, d) => s + Math.abs(d.delta), 0) / historyData.length;
          // 构造一个不超过均值 × 2 的非极值 delta
          const nonExtremeDelta = avgDelta * EXTREME_MULTIPLIER * ratio;
          const currentItem: DeltaUpdateData = {
            stock_code: "US.00001",
            delta: nonExtremeDelta,
            volume: 1000,
            timestamp: new Date().toISOString(),
            period_seconds: 10,
          };
          const allData = [...historyData, currentItem];
          const result = isExtremeDelta(allData.length - 1, allData);
          expect(result).toBe(false);
        },
      ),
      { numRuns: 100 },
    );
  });

  // ── 首个元素（无历史数据）不应被标记为极值 ──
  it("首个元素（无历史数据）不应被标记为极值", () => {
    fc.assert(
      fc.property(deltaUpdateArb(nonZeroDeltaArb), (item) => {
        const result = isExtremeDelta(0, [item]);
        expect(result).toBe(false);
      }),
      { numRuns: 100 },
    );
  });

  // ── 极值检测与颜色映射端到端一致性 ──
  it("极值检测结果应正确驱动颜色映射", () => {
    fc.assert(
      fc.property(
        // 生成 20~40 个 delta 数据
        fc.array(deltaUpdateArb(nonZeroDeltaArb), { minLength: 21, maxLength: 40 }),
        (deltaData) => {
          // 对最后一个元素进行极值检测和颜色映射
          const lastIndex = deltaData.length - 1;
          const lastDelta = deltaData[lastIndex].delta;
          const extreme = isExtremeDelta(lastIndex, deltaData);
          const color = getDeltaColor(lastDelta, extreme);

          if (lastDelta > 0) {
            if (extreme) {
              expect(color).toBe(COLOR_EXTREME_POSITIVE);
            } else {
              expect(color).toBe(COLOR_POSITIVE);
            }
          } else {
            if (extreme) {
              expect(color).toBe(COLOR_EXTREME_NEGATIVE);
            } else {
              expect(color).toBe(COLOR_NEGATIVE);
            }
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
