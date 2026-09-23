import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { PaperLedgerView } from "@/types/v2/paper-ledger";
import { PaperLedger, PaperLedgerContent } from "../PaperLedger";
import { paperLabel, paperMoney, paperTime } from "../labels";

const query = vi.hoisted(() => ({ data: undefined as PaperLedgerView | undefined, isError: false, isPending: true,
  options: {} as { retry?: boolean; refetchIntervalInBackground?: boolean } }));
vi.mock("@tanstack/react-query", () => ({ useQuery: (options: typeof query.options) => {
  query.options = options;
  return { ...query, isFetching: false, refetch: vi.fn() };
} }));
beforeEach(() => { query.data = undefined; query.isError = false; query.isPending = true; });

export const sample: PaperLedgerView = {
  status: "STOPPED", execution_enabled: false, runtime: null,
  ledger: {
    reported_at: "2026-09-23T11:00:00+08:00", as_of: "2026-09-23T10:30:00+08:00",
    account_id: "paper:test", experiment_id: "research-v1", strategy_id: "capital_absorption", strategy_version: "test-v1",
    stock_codes: ["HK.00100"], run_record_status: "OPEN_OR_UNCLEAN", run_error_code: null,
    cash: "99990.10", reserved_cash: "100", marked_equity: "100001.01", closed_order_net_pnl: "0",
    closed_order_count: 0, fees: "3.00", stale_position_codes: ["HK.00100"], order_count: 1,
    orders: [{ plan_id: "1", stock_code: "HK.00100", approved_at: "2026-09-23T10:00:00+08:00", status: "EXIT_PENDING",
      quantity: 200, bought: 100, sold: 0, held: 100, entry_remaining: 0, entry_min: "9.95", entry_limit: "10.05",
      stop_price: "9.7", valid_until: "2026-09-23T10:02:00+08:00", exit_at: "2026-09-23T15:55:00+08:00",
      entry_end_reason: null, exit_reason: "HOLDING_DEADLINE", closed_net_pnl: null }],
    fill_count: 1, recent_fills: [{ fill_id: "f1", stock_code: "HK.00100", side: "BUY", quantity: 100,
      price: "10", fee: "3", exchange_time: "2026-09-23T10:00:02+08:00" }],
    recent_signals: [{ event_id: "s1", stock_code: "HK.00100", processed_at: "2026-09-23T10:00:00+08:00", reason: "LOT_SIZE_EVIDENCE_INVALID" }],
  },
};

describe("paper ledger", () => {
  it("does not invent a zero balance when disabled or uninitialized", () => {
    for (const status of ["DISABLED", "NOT_INITIALIZED", "ERROR"] as const) {
      const html = renderToStaticMarkup(createElement(PaperLedgerContent, { data: { ...sample, status, ledger: null } }));
      expect(html).not.toContain("0.00");
      expect(html).not.toContain("已平仓净盈亏");
    }
  });
  it("distinguishes stale marks, incomplete runs, pending exits and unclosed PnL", () => {
    const html = renderToStaticMarkup(createElement(PaperLedgerContent, { data: sample }));
    expect(html).toContain("持仓估值行情已过期");
    expect(html).toContain("运行记录未正常关闭");
    expect(html).toContain("等待卖出成交");
    expect(html).toContain("达到持有期限");
    expect(html).toContain("99,990.10");
    expect(html).toMatch(/已平仓净盈亏<\/dt><dd[^>]*>--<\/dd>/);
    expect(html).not.toContain("胜率");
  });
  it("shows Chinese fill direction and independent signal rejection reasons", () => {
    const fills = renderToStaticMarkup(createElement(PaperLedgerContent, { data: sample, section: "fills" }));
    expect(fills).toContain("模拟买入");
    expect(fills).toContain("10:00:02");
    const signals = renderToStaticMarkup(createElement(PaperLedgerContent, { data: sample, section: "signals" }));
    expect(signals).toContain("缺少有效每手股数依据");
  });
  it("shows failed read without an endless spinner and does not retry in the query layer", () => {
    query.isError = true; query.isPending = false;
    const html = renderToStaticMarkup(createElement(TooltipProvider, null, createElement(PaperLedger)));
    expect(html).toContain("暂不能判断账户状态");
    expect(html).not.toContain("正在读取模拟账本...");
    expect(query.options.retry).toBe(false);
    expect(query.options.refetchIntervalInBackground).toBe(false);
  });
  it("marks previous data after a refresh failure", () => {
    query.isError = true; query.isPending = false; query.data = sample;
    const html = renderToStaticMarkup(createElement(TooltipProvider, null, createElement(PaperLedger)));
    expect(html).toContain("下方为上次读取结果");
    expect(html).toContain("99,990.10");
  });
  it("formats missing values and times without treating absence as zero", () => {
    expect(paperMoney(null)).toBe("--");
    expect(paperMoney("")).toBe("--");
    expect(paperMoney("invalid")).toBe("--");
    expect(paperMoney("0")).toBe("0.00");
    expect(paperTime("invalid")).toBe("--");
    expect(paperTime("2026-09-23T02:00:00Z")).toContain("10:00:00");
    expect(paperLabel("FUTURE_STATUS")).toBe("未识别状态，需核查");
  });
});
