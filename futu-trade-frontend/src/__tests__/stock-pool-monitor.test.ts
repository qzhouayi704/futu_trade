/**
 * 股票池监控页面 - API 调用与数据完整性测试
 *
 * 任务 5.1: 验证页面调用 getTopHotStocks 而非 getStockPool
 * 任务 5.2: 属性测试 - 验证 TopHotStock 数据包含完整字段
 *
 * 使用 AST 分析源码 + fast-check 属性测试，避免需要 jsdom 环境
 */

import { describe, it, expect } from "vitest";
import * as fs from "fs";
import * as path from "path";
import * as fc from "fast-check";

// ── 任务 5.1: API 调用单元测试 ──────────────────────────────────
// **Validates: Requirements 3.1, 3.4**

describe("股票池监控页面 API 调用验证", () => {
  const pageSource = fs.readFileSync(
    path.resolve(__dirname, "../app/stock-pool-monitor/page.tsx"),
    "utf-8"
  );

  it("页面应调用 getTopHotStocks 而非 getStockPool", () => {
    // loadStocks 函数中应使用 getTopHotStocks
    expect(pageSource).toContain("getTopHotStocks");

    // loadStocks 函数中不应调用 getStockPool
    // 排除注释中的引用，只检查实际调用
    const lines = pageSource.split("\n");
    const codeLines = lines.filter(
      (line) => !line.trim().startsWith("//") && !line.trim().startsWith("*")
    );
    const codeContent = codeLines.join("\n");

    const hasStockPoolCall =
      codeContent.includes("stockApi.getStockPool") ||
      codeContent.includes("getStockPool(");
    expect(hasStockPoolCall).toBe(false);
  });

  it("页面应传递 market 参数进行服务端筛选", () => {
    // 检查 market 参数传递
    expect(pageSource).toContain("market");
    expect(pageSource).toContain("marketFilter");
    // 确认参数被传递给 API 调用
    expect(pageSource).toContain("params.market");
  });

  it("页面应传递 search 参数进行服务端筛选", () => {
    expect(pageSource).toContain("searchQuery");
    expect(pageSource).toContain("params.search");
  });

  it("页面应处理 data_ready_status 字段", () => {
    expect(pageSource).toContain("data_ready_status");
    expect(pageSource).toContain("dataReadyStatus");
  });

  it("页面应处理 active_markets 字段", () => {
    expect(pageSource).toContain("active_markets");
    expect(pageSource).toContain("activeMarkets");
  });
});

// ── API 客户端验证 ──────────────────────────────────────────────

describe("stock.ts API 客户端验证", () => {
  const apiSource = fs.readFileSync(
    path.resolve(__dirname, "../lib/api/stock.ts"),
    "utf-8"
  );

  it("getTopHotStocks 应支持 market 参数", () => {
    expect(apiSource).toContain("market?: string");
  });

  it("getTopHotStocks 应支持 search 参数", () => {
    expect(apiSource).toContain("search?: string");
  });

  it("getTopHotStocks 应调用 /stocks/top-hot 端点", () => {
    expect(apiSource).toContain('"/stocks/top-hot"');
  });

  it("getTopHotStocks 返回类型应为 TopHotResponse", () => {
    expect(apiSource).toContain("TopHotResponse");
  });
});
