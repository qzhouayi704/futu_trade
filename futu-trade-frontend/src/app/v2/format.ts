export function pct(value: number | null | undefined, digits = 2): string {
  return value == null ? "--" : `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function money(value: number | null | undefined): string {
  if (value == null) return "--";
  const abs = Math.abs(value);
  if (abs >= 100_000_000) return `${(value / 100_000_000).toFixed(2)}亿`;
  if (abs >= 10_000) return `${(value / 10_000).toFixed(1)}万`;
  return value.toFixed(0);
}

export function clock(value: string | null | undefined): string {
  if (!value) return "--";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value.slice(11, 16)
    : date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

export function duration(seconds: number | null): string {
  if (seconds == null) return "--";
  if (seconds < 60) return `${seconds}秒`;
  return `${Math.round(seconds / 60)}分`;
}

export function tone(value: number | null | undefined): string {
  if (value == null) return "text-muted-foreground";
  return value > 0 ? "text-emerald-600 dark:text-emerald-400" : value < 0 ? "text-rose-600 dark:text-rose-400" : "text-muted-foreground";
}
