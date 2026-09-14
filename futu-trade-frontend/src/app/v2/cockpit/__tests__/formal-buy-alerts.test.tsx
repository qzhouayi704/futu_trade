import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { V2AlertPerformance, V2AlertPerformanceItem } from "@/lib/api/v2";
import { FormalBuyAlerts } from "../FormalBuyAlerts";

const state = vi.hoisted(() => ({
  data: undefined as V2AlertPerformance | undefined,
  isError: false,
  options: {} as { queryKey?: unknown[]; refetchInterval?: number; refetchIntervalInBackground?: boolean },
}));
vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: typeof state.options) => {
    state.options = options;
    return { data: state.data, isError: state.isError, isLoading: !state.data };
  },
}));

function alert(overrides: Partial<V2AlertPerformanceItem> = {}): V2AlertPerformanceItem {
  return {
    event_id: "buy-1", stock_code: "HK.00100", stock_name: "正式样本",
    action: "BUY", risk_result: "APPROVED", alert_permission: "DELIVERED",
    signal_time: "2026-09-14T09:39:00+08:00", signal_price: 10,
    current_status: "INVALIDATED", delivered_at: "2026-09-14T09:40:00+08:00",
    same_day: {
      status: "LIVE", trading_day: "2026-09-14", close_return_pct: null,
      max_return_pct: 0, max_drawdown_pct: -1.5, latest_return_pct: -1.5,
      observed_through: "2026-09-14T10:00:00+08:00",
    },
    direction: "BUY",
    ...overrides,
  } as V2AlertPerformanceItem;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-14T10:02:00+08:00"));
  state.data = undefined;
  state.isError = false;
});

describe("今日正式买入提醒", () => {
  const render = () => renderToStaticMarkup(createElement(FormalBuyAlerts));

  it("reads delivered alerts independently of the candidate scope", () => {
    expect(render()).toContain("正在读取正式提醒");
    expect(state.options).toMatchObject({
      queryKey: ["v2", "alert-performance", "2026-09-14", "alerts"],
      refetchInterval: 60_000, refetchIntervalInBackground: false,
    });
  });

  it("keeps an earlier buy visible after its candidate becomes invalidated", () => {
    state.data = { trade_date: "2026-09-14", scope: "alerts", items: [
      alert(), alert({ event_id: "sell-1", action: "SELL" }),
      alert({ event_id: "unapproved", risk_result: "REJECTED" }),
    ] } as V2AlertPerformance;
    const html = render();
    expect(html).toContain("1 条微信接口已接受");
    expect(html).toContain("正式样本");
    expect(html).toContain("当前已失效");
    expect(html).toContain("-1.50%");
    expect(html).not.toContain("sell-1");
  });

  it("distinguishes unavailable or stale data from zero alerts", () => {
    state.isError = true;
    expect(render()).toContain("不能据此判断今天没有信号");
    state.isError = false;
    state.data = { trade_date: "2026-09-13", scope: "alerts", items: [alert()] } as V2AlertPerformance;
    expect(render()).toContain("正在读取正式提醒");
    const stale = alert();
    state.data = { trade_date: "2026-09-14", scope: "alerts", items: [alert({
      same_day: { ...stale.same_day, latest_return_pct: 5, is_stale: true },
    })] } as V2AlertPerformance;
    expect(render()).toContain("行情已中断");
    expect(render()).not.toContain("+5.00%");
  });
});
