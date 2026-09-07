import type { V2AlertPerformanceItem } from "@/lib/api/v2";

export interface TodaySignalRow {
  item: V2AlertPerformanceItem;
  change: number | null;
  high: number | null;
  low: number | null;
}

export type SignalSort = "latest" | "earliest" | "strongest" | "weakest";

export function marketDateKey(now = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Hong_Kong" }).format(now);
}

export function signalClock(value: string | null | undefined): string {
  if (!value) return "--";
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value.replace(" ", "T")}+08:00`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? "--" : new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Hong_Kong", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

function finite(value: number | null | undefined): number | null {
  return value != null && Number.isFinite(value) ? value : null;
}

export function todaySignalRow(item: V2AlertPerformanceItem): TodaySignalRow {
  const period = item.same_day;
  const multiplier = item.direction === "SELL" ? -1 : 1;
  const rawChange = finite(period.status === "READY" ? period.close_return_pct : period.latest_return_pct);
  // Review returns are directional; the cockpit compares the underlying stock price.
  const rawHigh = finite(multiplier === -1 ? period.max_drawdown_pct : period.max_return_pct);
  const rawLow = finite(multiplier === -1 ? period.max_return_pct : period.max_drawdown_pct);
  return {
    item,
    change: rawChange == null ? null : multiplier * rawChange,
    high: rawHigh == null ? null : multiplier * rawHigh,
    low: rawLow == null ? null : multiplier * rawLow,
  };
}

function changeSummary(rows: TodaySignalRow[]) {
  const values = rows.flatMap(({ change }) => change == null ? [] : [change]);
  return {
    count: values.length,
    up: values.filter((value) => value > 0).length,
    down: values.filter((value) => value < 0).length,
    flat: values.filter((value) => value === 0).length,
    mean: values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null,
  };
}

export function todaySignalSummary(rows: TodaySignalRow[]) {
  const buys = rows.filter(({ item }) => item.direction !== "SELL");
  const sells = rows.filter(({ item }) => item.direction === "SELL");
  const paths = buys.filter(({ high }) => high != null);
  return {
    count: rows.length,
    observed: rows.filter(({ change }) => change != null).length,
    settled: rows.filter(({ item, change }) => item.same_day.status === "READY" && change != null).length,
    buys: changeSummary(buys),
    sells: changeSummary(sells),
    paths: paths.length,
    reached3: paths.filter(({ high }) => high! >= 3).length,
    reached5: paths.filter(({ high }) => high! >= 5).length,
  };
}

export function sortTodaySignals(rows: TodaySignalRow[], sort: SignalSort): TodaySignalRow[] {
  return [...rows].sort((a, b) => {
    if (sort === "strongest" || sort === "weakest") {
      if (a.change == null && b.change != null) return 1;
      if (b.change == null && a.change != null) return -1;
      if (a.change != null && b.change != null && a.change !== b.change) {
        return sort === "strongest" ? b.change - a.change : a.change - b.change;
      }
    }
    const difference = Date.parse(a.item.signal_time) - Date.parse(b.item.signal_time);
    return (sort === "earliest" ? difference : -difference) || a.item.event_id.localeCompare(b.item.event_id);
  });
}
