import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { V2AlertPerformance, V2AlertPerformanceItem, V2AlertPeriodResult } from "@/lib/api/v2";
import { TodaySignals } from "../TodaySignals";
import { marketDateKey, signalClock, sortTodaySignals, todaySignalRow, todaySignalSummary } from "../today-signal-metrics";

const state = vi.hoisted(() => ({
  data: undefined as V2AlertPerformance | undefined,
  isError: false,
  isLoading: false,
  options: {} as { queryKey?: unknown[]; staleTime?: number; refetchInterval?: number; refetchIntervalInBackground?: boolean },
}));
vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: typeof state.options) => {
    state.options = options;
    return { data: state.data, isError: state.isError, isLoading: state.isLoading, isFetching: false, refetch: vi.fn() };
  },
}));

const pending: V2AlertPeriodResult = {
  status: "PENDING", trading_day: null, close_return_pct: null,
  max_return_pct: null, max_drawdown_pct: null,
};
const metric = {
  completed_count: 0, win_count: 0, win_ratio: null, mean_return_pct: null,
  opportunity_count: 0, reached_1_5_count: 0, reached_1_5_ratio: null,
  mean_max_return_pct: null, mean_max_drawdown_pct: null,
};

function signal(overrides: Partial<V2AlertPerformanceItem> = {}): V2AlertPerformanceItem {
  return {
    event_id: "fixture", event_type: "CANDIDATE_ENTERED", stock_code: "HK.TEST", stock_name: "界面测试",
    signal_time: "2026-09-07T09:40:00+08:00", last_alert_time: "2026-09-07T09:50:00+08:00",
    signal_date: "2026-09-07", signal_price: 100, reason_code: "FIRST_STRONG_INFLOW_WATCH", strategy_version: "test-v1",
    action: "CANDIDATE", direction: "BUY", risk_result: "NOT_REQUIRED", entry_stage: "WATCHING", max_stage: "CONFIRMED",
    stage_points: {
      WATCHING: { time: "2026-09-07T09:40:00+08:00", price: 100, reason_code: "FIRST_STRONG_INFLOW_WATCH" },
      CONFIRMED: { time: "2026-09-07T09:50:00+08:00", price: 101, reason_code: "FAST_15M_MULTI_INFLOW_CONFIRMED" },
    },
    delivered_at: null, alert_count: 2, completed_horizon: 0,
    same_day: {
      status: "LIVE", trading_day: "2026-09-07", close_return_pct: null, latest_return_pct: 2.5,
      max_return_pct: 5, max_drawdown_pct: -0.5, source: "TICKER_DATA", intraday_covered: true,
      observed_from: "2026-09-07T09:40:30+08:00", observed_through: "2026-09-07T10:00:00+08:00", coverage: "OBSERVED",
    },
    periods: { "1": pending, "3": pending, "5": pending, "10": pending },
    ...overrides,
  };
}

function performance(items: V2AlertPerformanceItem[]): V2AlertPerformance {
  return {
    trade_date: "2026-09-07", as_of: "2026-09-07T10:02:00+08:00", scope: "candidates", count: items.length,
    available_kline_through: null, intraday_coverage_count: items.length,
    excluded: { total: 0, by_reason: {} }, summary_by_strategy_version: {},
    summary: { alert_count: items.length, same_day: metric, periods: { "1": metric, "3": metric, "5": metric, "10": metric } },
    items,
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-07T10:02:00+08:00"));
  state.data = performance([signal()]);
  state.isError = false;
  state.isLoading = false;
});
afterEach(() => vi.useRealTimers());

describe("今日信号统计口径", () => {
  it("keeps buy-side stock returns unchanged", () => {
    expect(todaySignalRow(signal())).toMatchObject({ change: 2.5, high: 5, low: -0.5 });
  });

  it("restores sell-side price direction and swaps the extrema", () => {
    expect(todaySignalRow(signal({ direction: "SELL", action: "SELL" }))).toMatchObject({ change: -2.5, high: 0.5, low: -5 });
  });

  it("uses finalized close rather than the last intraday observation", () => {
    const item = signal();
    Object.assign(item.same_day, { status: "READY", close_return_pct: -1, latest_return_pct: 2.5 });
    expect(todaySignalRow(item).change).toBe(-1);
  });

  it("does not substitute a premature closing return for missing live data", () => {
    const item = signal();
    Object.assign(item.same_day, { latest_return_pct: null, close_return_pct: 3, max_return_pct: NaN, max_drawdown_pct: Infinity });
    expect(todaySignalRow(item)).toMatchObject({ change: null, high: null, low: null });
  });

  it("excludes missing quotes, keeps flat prices and separates sells", () => {
    const up = signal();
    const flat = signal({ event_id: "flat", same_day: { ...up.same_day, latest_return_pct: 0 } });
    const missing = signal({ event_id: "missing", same_day: pending });
    const sell = signal({ event_id: "sell", direction: "SELL", action: "SELL" });
    const summary = todaySignalSummary([up, flat, missing, sell].map(todaySignalRow));
    expect(summary).toMatchObject({ count: 4, observed: 3, settled: 0, paths: 2, reached3: 2, reached5: 2 });
    expect(summary.buys).toEqual({ count: 2, up: 1, down: 0, flat: 1, mean: 1.25 });
    expect(summary.sells).toEqual({ count: 1, up: 0, down: 1, flat: 0, mean: -2.5 });
  });

  it("does not invent averages for an empty sample", () => {
    expect(todaySignalSummary([])).toMatchObject({ count: 0, buys: { mean: null }, sells: { mean: null }, reached5: 0 });
  });

  it("sorts the entire day, keeps missing returns last and does not mutate input", () => {
    const early = todaySignalRow(signal());
    const late = todaySignalRow(signal({ event_id: "late", signal_time: "2026-09-07T11:00:00+08:00", same_day: { ...signal().same_day, latest_return_pct: -1 } }));
    const missing = todaySignalRow(signal({ event_id: "missing", same_day: pending }));
    const rows = [early, late, missing];
    expect(sortTodaySignals(rows, "latest")[0]).toBe(late);
    expect(sortTodaySignals(rows, "earliest")[0]).toBe(early);
    expect(sortTodaySignals(rows, "strongest")).toEqual([early, late, missing]);
    expect(sortTodaySignals(rows, "weakest")).toEqual([late, early, missing]);
    expect(rows).toEqual([early, late, missing]);
  });

  it("uses Hong Kong date and time even across UTC midnight", () => {
    expect(marketDateKey(new Date("2026-09-07T16:01:00Z"))).toBe("2026-09-08");
    expect(signalClock("2026-09-07T01:40:00Z")).toBe("09:40");
    expect(signalClock("2026-09-07 09:40:00")).toBe("09:40");
    expect(signalClock("invalid")).toBe("--");
  });
});

describe("驾驶舱今日信号展示", () => {
  const render = () => renderToStaticMarkup(createElement(TodaySignals));

  it("shows Chinese scopes, baseline and visible performance without claiming a win rate", () => {
    const html = render();
    for (const label of ["今日信号表现", "候选池", "资金观察", "买点确认", "正式预警", "09:40", "100.000", "+2.50%", "行情截至", "10:00", "盘中未结算", "阶段记录", "非实盘盈亏"]) expect(html).toContain(label);
    expect(html).toContain("站内跟踪，非送达预警");
    expect(html).not.toContain("胜率");
    expect(html).not.toContain("WATCHING");
  });

  it("shares the review query and only polls once per minute in foreground", () => {
    render();
    expect(state.options).toMatchObject({ queryKey: ["v2", "alert-performance", "2026-09-07", "candidates"], staleTime: 45_000, refetchInterval: 60_000, refetchIntervalInBackground: false });
  });

  it("warns about a sell followed by a rally without inverting the visible price return", () => {
    const item = signal({ direction: "SELL", action: "SELL", delivered_at: "2026-09-07T09:40:02+08:00" });
    item.same_day.latest_return_pct = -3;
    state.data = performance([item]);
    const html = render();
    expect(html).toContain("卖出后反涨");
    expect(html).toContain("+3.00%");
    expect(html).toContain("已送达");
  });

  it("shows missing and partial data explicitly", () => {
    const missing = signal({ event_id: "missing", same_day: pending });
    const partial = signal();
    partial.same_day.status = "PARTIAL";
    partial.same_day.observed_through = null;
    state.data = performance([missing, partial]);
    const html = render();
    expect(html).toContain("等待行情");
    expect(html).toContain("缺少信号后路径");
    expect(html).toContain("待补收盘");
    expect(html).toContain("采样时间未提供");
  });

  it("shows query failure instead of asserting there were no signals", () => {
    state.isError = true;
    state.data = undefined;
    const html = render();
    expect(html).toContain("今日信号读取失败");
    expect(html).not.toContain("暂无信号记录");
  });

  it("marks retained data as stale when a refresh fails", () => {
    state.isError = true;
    expect(render()).toContain("下方保留上次成功数据，非最新结果");
  });

  it("never shows yesterday's data as today or a different scope's data", () => {
    state.data!.trade_date = "2026-09-06";
    expect(render()).not.toContain("界面测试");
    state.data!.trade_date = "2026-09-07";
    state.data!.scope = "alerts";
    expect(render()).not.toContain("界面测试");
  });

  it("retains different strategy versions and all daily records", () => {
    state.data = performance(Array.from({ length: 65 }, (_, index) => signal({
      event_id: `sample-${index}`, stock_name: `样本${index}`, strategy_version: index % 2 ? "test-v1" : "test-v2",
    })));
    const html = render();
    expect(html).toContain("全部策略版本");
    expect(html).toContain("样本64");
    expect(html).toContain("65 / 65");
  });

  it("shows loading state without rendering empty-sample conclusions", () => {
    state.data = undefined;
    state.isLoading = true;
    expect(render()).toContain("正在读取今日信号与后续行情");
    expect(render()).not.toContain("暂无信号记录");
  });
});
