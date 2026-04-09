/**
 * 属性测试：成交量分布条宽度比例
 *
 * Feature: intraday-scalping-engine
 * Property 11: 成交量分布条宽度比例
 * **Validates: Requirements 8.5**
 *
 * 测试策略：
 * - 直接导入 calculateBarWidth 工具函数进行纯逻辑验证
 * - 不需要 jsdom 或 React 渲染，纯数据驱动
 * - 验证宽度比例公式：width = (volume / maxVolume) × maxWidth
 * - 验证边界条件：volume=0、maxVolume<=0、maxWidth<=0
 * - 验证排序不变量：成交量越大，条宽度越大
 */

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { calculateBarWidth } from "@/app/enhanced-heat/components/scalping/PocOverlay";

// ==================== fast-check 生成策略 ====================

/** 正整数成交量 */
const positiveVolumeArb = fc.integer({ min: 1, max: 10_000_000 });

/** 正浮点数最大宽度（像素） */
const positiveMaxWidthArb = fc.float({
  min: Math.fround(1),
  max: Math.fround(2000),
  noNaN: true,
});

/** 生成一组成交量分布数据（至少 2 个档位） */
const volumeProfileArb = fc.array(positiveVolumeArb, {
  minLength: 2,
  maxLength: 50,
});

// ── Property 11: 成交量分布条宽度比例 ──────────────────────────
// Feature: intraday-scalping-engine
// Property 11: 成交量分布条宽度比例
// **Validates: Requirements 8.5**

describe("Property 11: 成交量分布条宽度比例", () => {
  // ── 核心公式：width = (volume / maxVolume) × maxWidth ──
  it("对于任意正成交量，条宽度应等于 (volume / maxVolume) × maxWidth", () => {
    fc.assert(
      fc.property(
        positiveVolumeArb,
        positiveVolumeArb,
        positiveMaxWidthArb,
        (volume, maxVolumeBase, maxWidth) => {
          // 确保 maxVolume >= volume，避免比例超过 1
          const maxVolume = Math.max(volume, maxVolumeBase);
          const result = calculateBarWidth(volume, maxVolume, maxWidth);
          const expected = (volume / maxVolume) * maxWidth;
          expect(result).toBeCloseTo(expected, 5);
        },
      ),
      { numRuns: 100 },
    );
  });

  // ── 最大档位的条宽度应等于最大宽度 ──
  it("当 volume 等于 maxVolume 时，条宽度应等于 maxWidth", () => {
    fc.assert(
      fc.property(
        positiveVolumeArb,
        positiveMaxWidthArb,
        (volume, maxWidth) => {
          const result = calculateBarWidth(volume, volume, maxWidth);
          expect(result).toBeCloseTo(maxWidth, 5);
        },
      ),
      { numRuns: 100 },
    );
  });

  // ── 所有条宽度应 >= 0 且 <= maxWidth ──
  it("对于任意正成交量，条宽度应在 [0, maxWidth] 范围内", () => {
    fc.assert(
      fc.property(
        positiveVolumeArb,
        positiveVolumeArb,
        positiveMaxWidthArb,
        (volume, maxVolumeBase, maxWidth) => {
          const maxVolume = Math.max(volume, maxVolumeBase);
          const result = calculateBarWidth(volume, maxVolume, maxWidth);
          expect(result).toBeGreaterThanOrEqual(0);
          expect(result).toBeLessThanOrEqual(maxWidth + 0.001); // 浮点容差
        },
      ),
      { numRuns: 100 },
    );
  });

  // ── volume = 0 时宽度应为 0 ──
  it("当 volume 为 0 时，条宽度应为 0", () => {
    fc.assert(
      fc.property(
        positiveVolumeArb,
        positiveMaxWidthArb,
        (maxVolume, maxWidth) => {
          const result = calculateBarWidth(0, maxVolume, maxWidth);
          expect(result).toBe(0);
        },
      ),
      { numRuns: 100 },
    );
  });

  // ── maxVolume <= 0 时宽度应为 0 ──
  it("当 maxVolume <= 0 时，条宽度应为 0", () => {
    fc.assert(
      fc.property(
        positiveVolumeArb,
        fc.integer({ min: -1000, max: 0 }),
        positiveMaxWidthArb,
        (volume, maxVolume, maxWidth) => {
          const result = calculateBarWidth(volume, maxVolume, maxWidth);
          expect(result).toBe(0);
        },
      ),
      { numRuns: 100 },
    );
  });

  // ── maxWidth <= 0 时宽度应为 0 ──
  it("当 maxWidth <= 0 时，条宽度应为 0", () => {
    fc.assert(
      fc.property(
        positiveVolumeArb,
        positiveVolumeArb,
        fc.float({ min: Math.fround(-1000), max: Math.fround(0), noNaN: true }),
        (volume, maxVolume, maxWidth) => {
          const result = calculateBarWidth(volume, maxVolume, maxWidth);
          expect(result).toBe(0);
        },
      ),
      { numRuns: 100 },
    );
  });

  // ── 成交量分布数据中，宽度应按成交量比例排序 ──
  it("对于一组成交量分布数据，宽度应按成交量单调递增", () => {
    fc.assert(
      fc.property(
        volumeProfileArb,
        positiveMaxWidthArb,
        (volumes, maxWidth) => {
          const maxVolume = Math.max(...volumes);
          const widths = volumes.map((v) =>
            calculateBarWidth(v, maxVolume, maxWidth),
          );

          // 按成交量排序后，对应的宽度也应单调递增
          const sorted = volumes
            .map((v, i) => ({ volume: v, width: widths[i] }))
            .sort((a, b) => a.volume - b.volume);

          for (let i = 1; i < sorted.length; i++) {
            if (sorted[i].volume > sorted[i - 1].volume) {
              expect(sorted[i].width).toBeGreaterThanOrEqual(
                sorted[i - 1].width - 0.001, // 浮点容差
              );
            } else if (sorted[i].volume === sorted[i - 1].volume) {
              expect(sorted[i].width).toBeCloseTo(sorted[i - 1].width, 5);
            }
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
