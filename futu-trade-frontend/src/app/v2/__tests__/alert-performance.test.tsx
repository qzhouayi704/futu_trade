import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AlertPerformance } from "../AlertPerformance";
import type { V2AlertPerformance, V2AlertPeriodResult } from "@/lib/api/v2";

const state = vi.hoisted(() => ({ data: undefined as V2AlertPerformance | undefined }));
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: state.data, isError: false, isLoading: false, isFetching: false, refetch: vi.fn() }),
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

beforeEach(() => {
  state.data = {
    trade_date: "2026-09-07", scope: "candidates", count: 1,
    available_kline_through: null, intraday_coverage_count: 1,
    excluded: { total: 0, by_reason: {} }, summary_by_strategy_version: {}, summary_by_strategy_source: {},
    lifecycle_summary: {
      current_status: { INVALIDATED: 1 }, max_stage: { SETUP: 1 },
      alert_permission: { NONE: 1 },
    },
    summary: { alert_count: 1, same_day: metric, periods: { "1": metric, "3": metric, "5": metric, "10": metric } },
    items: [{
      event_id: "fixture", event_type: "CANDIDATE_ENTERED", stock_code: "HK.TEST", stock_name: "界面测试",
      signal_time: "2026-09-07T09:40:00+08:00", last_alert_time: "2026-09-07T09:40:00+08:00",
      signal_date: "2026-09-07", signal_price: 100, reason_code: "LOW_POSITION_SETUP", strategy_version: "test",
      action: "CANDIDATE", direction: "BUY", risk_result: "NOT_REQUIRED", entry_stage: "SETUP", max_stage: "SETUP",
      current_status: "INVALIDATED", current_reason_code: "PRICE_ACCEPTANCE_BROKEN",
      current_state_time: "2026-09-07T10:10:00+08:00", alert_eligible: false,
      alert_permission: "NONE", strategy_sources: [], ever_strategy_sources: [], current_strategy_sources: [],
      stage_points: {}, delivered_at: null, alert_count: 1, completed_horizon: 0,
      same_day: {
        status: "LIVE", trading_day: "2026-09-07", close_return_pct: null, latest_return_pct: 2.5,
        max_return_pct: 3, max_drawdown_pct: -0.5, source: "TICKER_DATA", intraday_covered: true,
        observed_from: "2026-09-07T09:40:30+08:00", observed_through: "2026-09-07T10:00:00+08:00", coverage: "OBSERVED",
      },
      periods: { "1": pending, "3": pending, "5": pending, "10": pending },
    }],
  };
});

describe("Review performance labels", () => {
  it("shows live returns and coverage without claiming a closing return", () => {
    const html = renderToStaticMarkup(createElement(AlertPerformance));
    expect(html).toContain("当前 +2.50%");
    expect(html).toContain("截至");
    expect(html).toContain("可见路径自");
    expect(html).not.toContain("收盘 +2.50%");
    expect(html).not.toContain("有完整路径");
    expect(html).toContain("当前已失效");
    expect(html).toContain("当前无操作权限");
    expect(html).toContain("首次 候选准备 → 最高 候选准备");
  });

  it("marks an unfinished historical close as partial", () => {
    state.data!.items[0].same_day.status = "PARTIAL";
    const html = renderToStaticMarkup(createElement(AlertPerformance));
    expect(html).toContain("末次可见 +2.50%");
    expect(html).toContain("待补收盘数据");
  });

  it("uses the finalized close when available", () => {
    Object.assign(state.data!.items[0].same_day, { status: "READY", close_return_pct: 1.8, latest_return_pct: null });
    const html = renderToStaticMarkup(createElement(AlertPerformance));
    expect(html).toContain("收盘 +1.80%");
    expect(html).not.toContain("待补收盘数据");
  });

  it("shows descriptive results grouped by the strategy known at baseline", () => {
    state.data!.summary_by_strategy_source = {
      capital_absorption: {
        alert_count: 3,
        same_day: { ...metric, mean_return_pct: 1.2, reached_1_5_ratio: 2 / 3 },
        periods: {
          "1": { ...metric, mean_return_pct: 0.8 },
          "3": metric, "5": metric, "10": metric,
        },
      },
    };

    const html = renderToStaticMarkup(createElement(AlertPerformance));

    expect(html).toContain("基准时策略");
    expect(html).toContain("低位资金吸收");
    expect(html).toContain("+1.20%");
    expect(html).toContain("66.7%");
  });
});
