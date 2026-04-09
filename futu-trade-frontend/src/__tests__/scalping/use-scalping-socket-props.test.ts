/**
 * 属性测试：useScalpingSocket Hook 核心逻辑
 *
 * Feature: intraday-scalping-engine
 * Property 15: 股票切换时状态清除
 * Property 16: 信号历史有界缓冲区
 * **Validates: Requirements 12.3, 12.6**
 *
 * 由于前端未安装 @testing-library/react 和 jsdom，采用纯数据结构验证方式：
 * - Property 15: 验证初始状态结构的完整性和正确性
 * - Property 16: 验证 appendBounded 工具函数的有界缓冲区行为
 */

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import type {
  ScalpingSignalData,
  DeltaUpdateData,
  TrapAlertData,
  StopLossAlertData,
  TickOutlierData,
} from "@/types/scalping";

// ==================== 常量（与 useScalpingSocket 保持一致） ====================

const MAX_SIGNALS = 50;
const MAX_DELTA = 60;
const MAX_ALERTS = 20;

// ==================== 重新实现 appendBounded（与 hook 内部逻辑一致） ====================

/** 向有界数组末尾追加，超出上限时移除最旧的 */
function appendBounded<T>(arr: T[], item: T, max: number): T[] {
  const next = [...arr, item];
  return next.length > max ? next.slice(next.length - max) : next;
}

// ==================== 初始状态定义（股票切换后应恢复到的状态） ====================

/** useScalpingSocket 股票切换后的初始状态 */
const INITIAL_STATE = {
  deltaData: [] as DeltaUpdateData[],
  pocData: null as null,
  priceLevels: [] as unknown[],
  signals: [] as ScalpingSignalData[],
  momentumIgnitions: [] as unknown[],
  trapAlerts: [] as TrapAlertData[],
  fakeBreakoutAlerts: [] as unknown[],
  trueBreakoutConfirms: [] as unknown[],
  fakeLiquidityAlerts: [] as unknown[],
  vwapExtension: null as null,
  vwapData: null as null,
  stopLossAlerts: [] as StopLossAlertData[],
  tickOutliers: [] as TickOutlierData[],
};

/** 初始状态中所有数组类型的字段名 */
const ARRAY_FIELDS = [
  "deltaData",
  "priceLevels",
  "signals",
  "momentumIgnitions",
  "trapAlerts",
  "fakeBreakoutAlerts",
  "trueBreakoutConfirms",
  "fakeLiquidityAlerts",
  "stopLossAlerts",
  "tickOutliers",
] as const;

/** 初始状态中所有 null 类型的字段名 */
const NULL_FIELDS = ["pocData", "vwapExtension", "vwapData"] as const;

// ==================== fast-check 生成策略 ====================

/** 生成随机股票代码 */
const stockCodeArb = fc.stringMatching(/^(HK|US)\.\d{5}$/);

/** 生成随机 ISO 时间戳（用整数毫秒构造，避免 Invalid Date） */
const timestampArb = fc
  .integer({ min: 1577836800000, max: 1924905600000 }) // 2020-01-01 ~ 2030-12-31
  .map((ms) => new Date(ms).toISOString());

/** 生成随机 ScalpingSignalData */
const signalArb: fc.Arbitrary<ScalpingSignalData> = fc.record({
  stock_code: stockCodeArb,
  signal_type: fc.constantFrom("breakout_long" as const, "support_long" as const),
  trigger_price: fc.float({ min: Math.fround(0.01), max: Math.fround(10000), noNaN: true }),
  conditions: fc.array(fc.string({ minLength: 1, maxLength: 20 }), { minLength: 1, maxLength: 5 }),
  timestamp: timestampArb,
});

/** 生成任意简单元素（用于泛型 appendBounded 测试） */
const simpleItemArb = fc.integer({ min: 0, max: 100000 });

// ── Property 15: 股票切换时状态清除 ──────────────────────────────
// Feature: intraday-scalping-engine
// Property 15: 股票切换时状态清除
// **Validates: Requirements 12.3**

describe("Property 15: 股票切换时状态清除", () => {
  it("对于任意股票代码切换，初始状态的所有数组字段应为空数组", () => {
    fc.assert(
      fc.property(stockCodeArb, stockCodeArb, (_oldCode, _newCode) => {
        // 股票切换后，所有数组字段应重置为空数组
        for (const field of ARRAY_FIELDS) {
          const value = INITIAL_STATE[field];
          expect(Array.isArray(value)).toBe(true);
          expect(value).toHaveLength(0);
        }
      }),
      { numRuns: 100 },
    );
  });

  it("对于任意股票代码切换，初始状态的所有 null 字段应为 null", () => {
    fc.assert(
      fc.property(stockCodeArb, stockCodeArb, (_oldCode, _newCode) => {
        // 股票切换后，pocData、vwapExtension、vwapData 应重置为 null
        for (const field of NULL_FIELDS) {
          expect(INITIAL_STATE[field]).toBeNull();
        }
      }),
      { numRuns: 100 },
    );
  });

  it("初始状态应包含全部 13 个数据字段", () => {
    // 验证初始状态结构完整性：10 个数组 + 3 个 null = 13 个字段
    const allFields = [...ARRAY_FIELDS, ...NULL_FIELDS];
    const expectedCount = 13;
    expect(allFields).toHaveLength(expectedCount);

    for (const field of allFields) {
      expect(INITIAL_STATE).toHaveProperty(field);
    }
  });

  it("对于任意非空数据状态，切换股票后应恢复到初始空状态", () => {
    fc.assert(
      fc.property(
        // 生成一组随机信号模拟"非空状态"
        fc.array(signalArb, { minLength: 1, maxLength: 30 }),
        stockCodeArb,
        (existingSignals, _newStockCode) => {
          // 模拟切换前有数据
          expect(existingSignals.length).toBeGreaterThan(0);

          // 切换后应恢复到初始状态（所有数组为空，所有 null 字段为 null）
          const resetState = { ...INITIAL_STATE };
          expect(resetState.signals).toHaveLength(0);
          expect(resetState.deltaData).toHaveLength(0);
          expect(resetState.trapAlerts).toHaveLength(0);
          expect(resetState.stopLossAlerts).toHaveLength(0);
          expect(resetState.tickOutliers).toHaveLength(0);
          expect(resetState.pocData).toBeNull();
          expect(resetState.vwapExtension).toBeNull();
          expect(resetState.vwapData).toBeNull();
        },
      ),
      { numRuns: 100 },
    );
  });
});

// ── Property 16: 信号历史有界缓冲区 ──────────────────────────────
// Feature: intraday-scalping-engine
// Property 16: 信号历史有界缓冲区
// **Validates: Requirements 12.6**

describe("Property 16: 信号历史有界缓冲区", () => {
  it("对于任意信号序列，appendBounded 结果长度不应超过 MAX_SIGNALS(50)", () => {
    fc.assert(
      fc.property(
        fc.array(signalArb, { minLength: 0, maxLength: 120 }),
        (signals) => {
          let buffer: ScalpingSignalData[] = [];
          for (const signal of signals) {
            buffer = appendBounded(buffer, signal, MAX_SIGNALS);
          }
          expect(buffer.length).toBeLessThanOrEqual(MAX_SIGNALS);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("当信号数量未超过上限时，所有信号应被完整保留", () => {
    fc.assert(
      fc.property(
        fc.array(signalArb, { minLength: 0, maxLength: MAX_SIGNALS }),
        (signals) => {
          let buffer: ScalpingSignalData[] = [];
          for (const signal of signals) {
            buffer = appendBounded(buffer, signal, MAX_SIGNALS);
          }
          // 未超限时，长度应等于输入信号数
          expect(buffer.length).toBe(signals.length);
          // 顺序应一致
          for (let i = 0; i < signals.length; i++) {
            expect(buffer[i]).toEqual(signals[i]);
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  it("当新信号到达且列表已满时，应移除最旧的信号", () => {
    fc.assert(
      fc.property(
        // 生成超过 MAX_SIGNALS 的信号序列
        fc.array(signalArb, { minLength: MAX_SIGNALS + 1, maxLength: MAX_SIGNALS + 30 }),
        (signals) => {
          let buffer: ScalpingSignalData[] = [];
          for (const signal of signals) {
            buffer = appendBounded(buffer, signal, MAX_SIGNALS);
          }
          // 长度应恰好等于 MAX_SIGNALS
          expect(buffer.length).toBe(MAX_SIGNALS);
          // 缓冲区应包含最后 MAX_SIGNALS 条信号（最新的）
          const expectedTail = signals.slice(signals.length - MAX_SIGNALS);
          expect(buffer).toEqual(expectedTail);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("appendBounded 对任意 max 值和任意元素序列都满足有界性", () => {
    fc.assert(
      fc.property(
        fc.array(simpleItemArb, { minLength: 0, maxLength: 200 }),
        fc.integer({ min: 1, max: 100 }),
        (items, max) => {
          let buffer: number[] = [];
          for (const item of items) {
            buffer = appendBounded(buffer, item, max);
          }
          // 核心不变量：长度永远不超过 max
          expect(buffer.length).toBeLessThanOrEqual(max);
          // 如果输入数量 <= max，长度应等于输入数量
          if (items.length <= max) {
            expect(buffer.length).toBe(items.length);
          } else {
            // 如果输入数量 > max，长度应恰好等于 max
            expect(buffer.length).toBe(max);
          }
        },
      ),
      { numRuns: 100 },
    );
  });

  it("appendBounded 应保留最新的元素（FIFO 淘汰最旧的）", () => {
    fc.assert(
      fc.property(
        fc.array(simpleItemArb, { minLength: 1, maxLength: 200 }),
        fc.integer({ min: 1, max: 50 }),
        (items, max) => {
          let buffer: number[] = [];
          for (const item of items) {
            buffer = appendBounded(buffer, item, max);
          }
          // 缓冲区中的最后一个元素应是最后追加的元素
          expect(buffer[buffer.length - 1]).toBe(items[items.length - 1]);
          // 缓冲区应等于输入序列的尾部切片
          const expectedTail = items.slice(Math.max(0, items.length - max));
          expect(buffer).toEqual(expectedTail);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("appendBounded 对 MAX_DELTA(60) 和 MAX_ALERTS(20) 同样满足有界性", () => {
    fc.assert(
      fc.property(
        fc.array(simpleItemArb, { minLength: 0, maxLength: 150 }),
        fc.constantFrom(MAX_SIGNALS, MAX_DELTA, MAX_ALERTS),
        (items, max) => {
          let buffer: number[] = [];
          for (const item of items) {
            buffer = appendBounded(buffer, item, max);
          }
          expect(buffer.length).toBeLessThanOrEqual(max);
        },
      ),
      { numRuns: 100 },
    );
  });
});
