import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { OvernightRows } from "../OvernightCandidates";
import type { V2OvernightObservation } from "@/lib/api/v2";


const item: V2OvernightObservation = {
  stock_code: "HK.00100",
  stock_name: "MINIMAX-W",
  setup_id: "setup-1",
  source_date: "2026-09-04",
  source_time: "2026-09-04T14:10:00+08:00",
  source_reason: "FAST_15M_MULTI_INFLOW_CONFIRMED",
  reference_price: 339,
  score: 78,
  day_main_net: 8_000_000,
  independent_buy_events: 4,
  eligible_date: "2026-09-07",
  expires_date: "2026-09-09",
  age_sessions: 1,
  status: "WATCHING",
  reason_code: "OVERNIGHT_PRIORITY_PENDING_RECONFIRMATION",
  last_event_time: "2026-09-07T09:35:00+08:00",
  selected: true,
};


describe("Overnight candidate lifecycle", () => {
  it("renders the lifecycle and reason in Chinese", () => {
    const html = renderToStaticMarkup(
      createElement(OvernightRows, { items: [item] })
    );

    expect(html).toContain("待当日确认");
    expect(html).toContain("第 1 / 3 个交易日");
    expect(html).toContain("等待当日价格与资金重新确认");
    expect(html).toContain("列入订阅优先名单");
    expect(html).not.toContain("OVERNIGHT_PRIORITY_PENDING_RECONFIRMATION");
  });

  it("shows suspended clues as observation-only", () => {
    const html = renderToStaticMarkup(
      createElement(OvernightRows, {
        items: [{
          ...item,
          status: "SUSPENDED",
          reason_code: "OVERNIGHT_PRIORITY_CAPITAL_UNRESOLVED",
          selected: false,
        }],
      })
    );

    expect(html).toContain("暂缓观察");
    expect(html).toContain("后续资金转弱，保留观察但暂不建仓");
    expect(html).toContain("未列入当前优先名单");
  });
});
