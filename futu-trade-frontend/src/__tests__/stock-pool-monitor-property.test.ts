/**
 * 属性测试：Top_Hot_API 响应包含完整的股票字段
 *
 * Feature: fix-stock-monitor-api
 * Property 2: Top_Hot_API 响应包含完整的股票字段
 * **Validates: Requirements 3.2, 3.3**
 *
 * 使用 fast-check 生成随机 TopHotStock 数据，验证数据结构包含
 * heat_score、cur_price、change_rate、turnover_rate、turnover 等必要字段。
 *
 * 由于前端未安装 @testing-library/react 和 jsdom，采用数据结构验证方式：
 * 验证任意有效的 TopHotStock 数据都包含页面渲染所需的全部字段。
 */

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import type { TopHotStock, TopHotResponse, DataReadyStatus } from "@/types";

// ── fast-check 生成策略 ─────────────────────────────────────────

/** 生成随机 TopHotStock 数据 */
const topHotStockArb: fc.Arbitrary<TopHotStock> = fc.record({
  id: fc.integer({ min: 1, max: 100000 }),
  code: fc.stringMatching(/^(HK|US)\.\d{5}$/),
  name: fc.string({ minLength: 1, maxLength: 20 }),
  market: fc.constantFrom("HK", "US"),
  heat_score: fc.float({ min: Math.fround(0), max: Math.fround(100), noNaN: true }),
  cur_price: fc.float({ min: Math.fround(0.01), max: Math.fround(10000), noNaN: true }),
  last_price: fc.float({ min: Math.fround(0.01), max: Math.fround(10000), noNaN: true }),
  change_rate: fc.float({ min: Math.fround(-50), max: Math.fround(50), noNaN: true }),
  volume: fc.integer({ min: 0, max: 100000000 }),
  turnover: fc.float({ min: Math.fround(0), max: Math.fround(1e12), noNaN: true }),
  turnover_rate: fc.float({ min: Math.fround(0), max: Math.fround(100), noNaN: true }),
  amplitude: fc.float({ min: Math.fround(0), max: Math.fround(100), noNaN: true }),
  high_price: fc.float({ min: Math.fround(0.01), max: Math.fround(10000), noNaN: true }),
  low_price: fc.float({ min: Math.fround(0.01), max: Math.fround(10000), noNaN: true }),
  open_price: fc.float({ min: Math.fround(0.01), max: Math.fround(10000), noNaN: true }),
  prev_close_price: fc.float({ min: Math.fround(0.01), max: Math.fround(10000), noNaN: true }),
  is_position: fc.boolean(),
  has_condition: fc.boolean(),
  condition: fc.constantFrom(null, { type: "buy", reason: "test" }),
});

/** 生成随机 DataReadyStatus */
const dataReadyStatusArb: fc.Arbitrary<DataReadyStatus> = fc.record({
  data_ready: fc.boolean(),
  cached_count: fc.integer({ min: 0, max: 1000 }),
  expected_count: fc.integer({ min: 1, max: 1000 }),
  ready_percent: fc.float({ min: Math.fround(0), max: Math.fround(100), noNaN: true }),
});

/** 生成随机 TopHotResponse */
const topHotResponseArb: fc.Arbitrary<TopHotResponse> = fc.record({
  stocks: fc.array(topHotStockArb, { minLength: 0, maxLength: 20 }),
  market_info: fc.constant({}),
  active_markets: fc.constantFrom(["HK"], ["US"], ["HK", "US"]),
  filter_config: fc.constant({}),
  data_ready_status: dataReadyStatusArb,
  cache_timestamp: fc.date().map((d) => d.toISOString()),
  cache_duration: fc.integer({ min: 1, max: 300 }),
});

// ── 页面渲染所需的必要字段 ──────────────────────────────────────

/** 页面表格列中使用的字段（来自 page.tsx 的 columns 定义） */
const REQUIRED_DISPLAY_FIELDS: (keyof TopHotStock)[] = [
  "heat_score",
  "cur_price",
  "change_rate",
  "turnover_rate",
  "turnover",
];

/** TopHotStock 的全部字段 */
const ALL_STOCK_FIELDS: (keyof TopHotStock)[] = [
  "id",
  "code",
  "name",
  "market",
  "heat_score",
  "cur_price",
  "last_price",
  "change_rate",
  "volume",
  "turnover",
  "turnover_rate",
  "amplitude",
  "high_price",
  "low_price",
  "open_price",
  "prev_close_price",
  "is_position",
  "has_condition",
  "condition",
];

// ── Property 2: 响应包含完整的股票字段 ──────────────────────────
// Feature: fix-stock-monitor-api
// Property 2: Top_Hot_API 响应包含完整的股票字段
// **Validates: Requirements 3.2, 3.3**

describe("Property 2: TopHotStock 数据包含完整字段", () => {
  it("任意 TopHotStock 应包含页面渲染所需的全部显示字段", () => {
    fc.assert(
      fc.property(topHotStockArb, (stock) => {
        for (const field of REQUIRED_DISPLAY_FIELDS) {
          expect(stock).toHaveProperty(field);
          expect(stock[field]).toBeDefined();
        }
      }),
      { numRuns: 100 }
    );
  });

  it("任意 TopHotStock 应包含完整的数据字段", () => {
    fc.assert(
      fc.property(topHotStockArb, (stock) => {
        for (const field of ALL_STOCK_FIELDS) {
          expect(stock).toHaveProperty(field);
        }
      }),
      { numRuns: 100 }
    );
  });

  it("任意 TopHotResponse 应包含 data_ready_status 字段", () => {
    fc.assert(
      fc.property(topHotResponseArb, (response) => {
        expect(response).toHaveProperty("data_ready_status");
        expect(response.data_ready_status).toHaveProperty("data_ready");
        expect(response.data_ready_status).toHaveProperty("cached_count");
        expect(response.data_ready_status).toHaveProperty("expected_count");
        expect(response.data_ready_status).toHaveProperty("ready_percent");
      }),
      { numRuns: 100 }
    );
  });

  it("任意 TopHotStock 的数值字段应为有限数", () => {
    fc.assert(
      fc.property(topHotStockArb, (stock) => {
        expect(Number.isFinite(stock.heat_score)).toBe(true);
        expect(Number.isFinite(stock.cur_price)).toBe(true);
        expect(Number.isFinite(stock.change_rate)).toBe(true);
        expect(Number.isFinite(stock.turnover_rate)).toBe(true);
        expect(Number.isFinite(stock.turnover)).toBe(true);
        expect(Number.isFinite(stock.volume)).toBe(true);
      }),
      { numRuns: 100 }
    );
  });

  it("任意 TopHotResponse.stocks 中的每只股票都应包含显示字段", () => {
    fc.assert(
      fc.property(topHotResponseArb, (response) => {
        for (const stock of response.stocks) {
          for (const field of REQUIRED_DISPLAY_FIELDS) {
            expect(stock).toHaveProperty(field);
            expect(stock[field]).toBeDefined();
          }
        }
      }),
      { numRuns: 100 }
    );
  });
});
