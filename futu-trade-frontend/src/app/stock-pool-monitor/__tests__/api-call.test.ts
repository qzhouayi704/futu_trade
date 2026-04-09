/**
 * 股票池监控页面 API 调用单元测试
 *
 * 通过源码分析验证页面加载时调用 getTopHotStocks 而非 getStockPool，
 * 以及 market/search 参数正确传递。
 *
 * **Validates: Requirements 3.1, 3.4**
 */

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';

// 页面组件源码
const PAGE_SOURCE = readFileSync(
  resolve(__dirname, '../page.tsx'),
  'utf-8'
);

// API 客户端源码
const API_SOURCE = readFileSync(
  resolve(__dirname, '../../../lib/api/stock.ts'),
  'utf-8'
);

describe('股票池监控页面 API 调用验证', () => {
  it('页面应调用 getTopHotStocks 而非 getStockPool', () => {
    expect(PAGE_SOURCE).toContain('getTopHotStocks');
    expect(PAGE_SOURCE).not.toMatch(/stockApi\.getStockPool\s*\(/);
  });

  it('getTopHotStocks 调用应传递筛选参数对象', () => {
    expect(PAGE_SOURCE).toMatch(/getTopHotStocks\s*\(\s*params\s*\)/);
  });

  it('页面应构建包含 market 和 search 的参数对象', () => {
    expect(PAGE_SOURCE).toContain('params.market');
    expect(PAGE_SOURCE).toContain('params.search');
  });

  it('页面应处理 data_ready_status 数据就绪状态', () => {
    expect(PAGE_SOURCE).toContain('data_ready_status');
  });
});

describe('stockApi.getTopHotStocks 方法签名验证', () => {
  it('API 客户端应定义 getTopHotStocks 方法', () => {
    expect(API_SOURCE).toContain('getTopHotStocks');
  });

  it('getTopHotStocks 应调用 /stocks/top-hot 端点', () => {
    expect(API_SOURCE).toContain('/stocks/top-hot');
  });

  it('getTopHotStocks 参数应支持 market 和 search', () => {
    // 验证方法签名中包含 market 和 search 参数
    expect(API_SOURCE).toMatch(/getTopHotStocks.*market/s);
    expect(API_SOURCE).toMatch(/getTopHotStocks.*search/s);
  });

  it('getTopHotStocks 返回类型应为 TopHotResponse', () => {
    expect(API_SOURCE).toContain('TopHotResponse');
  });
});
