import type { V2AlertPerformanceItem } from "@/lib/api/v2";

export interface TodaySignalRow {
  item: V2AlertPerformanceItem;
  change: number | null;
  high: number | null;
  low: number | null;
}

export const signalSortColumns = [
  { field: "stock", label: "股票", ascending: "stock-asc", descending: "stock-desc", initial: "asc" },
  { field: "stage", label: "当前状态", ascending: "stage-asc", descending: "stage-desc", initial: "desc" },
  { field: "time", label: "首次信号", ascending: "earliest", descending: "latest", initial: "desc" },
  { field: "price", label: "基准价", ascending: "price-asc", descending: "price-desc", initial: "desc" },
  { field: "change", label: "后续股价涨跌", ascending: "weakest", descending: "strongest", initial: "desc" },
  { field: "high", label: "信号后最高", ascending: "high-asc", descending: "high-desc", initial: "desc" },
  { field: "low", label: "信号后最低", ascending: "low-asc", descending: "low-desc", initial: "asc" },
] as const;
export type SignalSortColumn = (typeof signalSortColumns)[number];
export type SignalSort = SignalSortColumn["ascending" | "descending"];

export function toggleSignalSort(current: SignalSort, column: SignalSortColumn): SignalSort {
  if (current === column.ascending) return column.descending;
  if (current === column.descending) return column.ascending;
  return column.initial === "asc" ? column.ascending : column.descending;
}

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
  const column = signalSortColumns.find((option) => option.ascending === sort || option.descending === sort)!;
  const direction = sort === column.ascending ? 1 : -1;
  const names = new Intl.Collator("zh-CN", { numeric: true, sensitivity: "base" });
  const value = (row: TodaySignalRow): number | string | null => {
    switch (column.field) {
      case "stock": return row.item.stock_name || row.item.stock_code;
      case "stage": return {
        IDLE: 0, INVALIDATED: 0, SETUP: 1, WATCHING: 2, CONFIRMED: 3,
      }[row.item.current_status];
      case "time": return finite(Date.parse(row.item.signal_time));
      case "price": return finite(row.item.signal_price);
      default: return row[column.field];
    }
  };
  return [...rows].sort((a, b) => {
    const left = value(a), right = value(b);
    if (left == null && right != null) return 1;
    if (right == null && left != null) return -1;
    if (left != null && right != null && left !== right) {
      const difference = typeof left === "string" && typeof right === "string"
        ? names.compare(left, right) : Number(left) - Number(right);
      if (difference) return direction * difference;
    }
    return (finite(Date.parse(b.item.signal_time)) ?? 0) - (finite(Date.parse(a.item.signal_time)) ?? 0)
      || a.item.event_id.localeCompare(b.item.event_id);
  });
}
