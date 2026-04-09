/**
 * 属性测试：SignalPanel VWAP 超限时买入按钮禁用
 *
 * Feature: intraday-scalping-engine
 * Property 23: VWAP 超限时买入按钮禁用
 * **Validates: Requirements 16.4, 16.6**
 *
 * 测试策略：直接测试导出的 isVwapDisabled 纯函数，
 * 无需 jsdom 或 React 渲染环境。
 */

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { isVwapDisabled } from "@/app/enhanced-heat/components/scalping/SignalPanel";
import type { VwapExtensionAlertData } from "@/types/scalping";

// ==================== fast-check 生成策略 ====================

/** 生成随机股票代码 */
const stockCodeArb = fc.stringMatching(/^(HK|US)\.\d{5}$/);

/** 生成随机 ISO 时间戳 */
const timestampArb = fc
  .integer({ min: 1577836800000, max: 1924905600000 })
  .map((ms) => new Date(ms).toISOString());

/** 生成有效的 VwapExtensionAlertData */
const vwapExtensionArb: fc.Arbitrary<VwapExtensionAlertData> = fc.record({
  stock_code: stockCodeArb,
  current_price: fc.float({ min: Math.fround(0.01), max: Math.fround(10000), noNaN: true }),
  vwap_value: fc.float({ min: Math.fround(0.01), max: Math.fround(10000), noNaN: true }),
  deviation_percent: fc.float({ min: Math.fround(0.01), max: Math.fround(100), noNaN: true }),
  dynamic_threshold: fc.float({ min: Math.fround(0.01), max: Math.fround(50), noNaN: true }),
  timestamp: timestampArb,
});

// ── Property 23: VWAP 超限时买入按钮禁用 ──────────────────────────
// Feature: intraday-scalping-engine
// Property 23: VWAP 超限时买入按钮禁用
// **Validates: Requirements 16.4, 16.6**

describe("Property 23: VWAP 超限时买入按钮禁用", () => {
  it("对于任意有效的 VwapExtensionAlertData，isVwapDisabled 应返回 true（按钮禁用）", () => {
    fc.assert(
      fc.property(vwapExtensionArb, (alertData) => {
        // VWAP 超限状态下，买入按钮应被禁用
        expect(isVwapDisabled(alertData)).toBe(true);
      }),
      { numRuns: 100 },
    );
  });

  it("当 vwapExtension 为 null 时（VWAP_EXTENSION_CLEAR 后），isVwapDisabled 应返回 false（按钮可用）", () => {
    // VWAP 恢复正常后，vwapExtension 被置为 null，按钮应恢复可用
    expect(isVwapDisabled(null)).toBe(false);
  });

  it("对于任意 VWAP 超限→恢复的状态转换序列，按钮状态应正确切换", () => {
    fc.assert(
      fc.property(
        // 生成一系列 VWAP 状态变化：true 表示超限（有 alert），false 表示恢复（null）
        fc.array(fc.boolean(), { minLength: 1, maxLength: 50 }),
        vwapExtensionArb,
        (stateSequence, sampleAlert) => {
          for (const isExtended of stateSequence) {
            const vwapExtension = isExtended ? sampleAlert : null;
            const disabled = isVwapDisabled(vwapExtension);

            if (isExtended) {
              // 超限状态 → 按钮禁用
              expect(disabled).toBe(true);
            } else {
              // 恢复正常（VWAP_EXTENSION_CLEAR 后 vwapExtension 为 null）→ 按钮可用
              expect(disabled).toBe(false);
            }
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  it("isVwapDisabled 的返回值与 vwapExtension 是否为 null 严格等价", () => {
    fc.assert(
      fc.property(
        fc.oneof(
          vwapExtensionArb.map((a) => a as VwapExtensionAlertData | null),
          fc.constant(null as VwapExtensionAlertData | null),
        ),
        (vwapExtension) => {
          // 核心不变量：disabled === (vwapExtension !== null)
          expect(isVwapDisabled(vwapExtension)).toBe(vwapExtension !== null);
        },
      ),
      { numRuns: 100 },
    );
  });
});
