import { ArrowRight, GitCommitHorizontal } from "lucide-react";
import type { V2Decision } from "@/lib/api/v2";
import { clock } from "./format";

const actionTypes = new Set(["BUY_CONFIRMED", "EXIT_RISK_CONFIRMED", "ROTATION_PROPOSED"]);

const eventLabel: Record<string, string> = {
  CANDIDATE_REJECTED: "未进入候选",
  CANDIDATE_ENTERED: "进入候选",
  CANDIDATE_UPDATED: "候选升级",
  CANDIDATE_INVALIDATED: "候选失效",
  BUY_CONFIRMED: "买点确认",
  BUY_INVALIDATED: "买点失效",
};

const reasonLabel: Record<string, string> = {
  TURNOVER_RANK_NOT_HOT: "成交额热度不足",
  SECTOR_BREADTH_WEAK: "所属板块宽度偏弱",
  RELATIVE_STRENGTH_LOW: "相对强度不足",
  DAILY_POSITION_INVALID: "缺少日线参考",
  LEGACY_RALLY_STRONG_WATCH: "量价齐升，等待多次流入",
  FAST_15M_MULTI_INFLOW_CONFIRMED: "15分钟多次流入确认",
};

export function DecisionStream({ items, compact = false }: { items: V2Decision[]; compact?: boolean }) {
  return <div className="divide-y divide-border/70">
    {items.slice(0, compact ? 8 : undefined).map((item) => <div key={item.event_id} className="grid min-h-14 grid-cols-[64px_1fr] gap-3 px-3 py-2 md:grid-cols-[64px_130px_1fr_180px] md:items-center">
      <div className="font-mono text-xs text-muted-foreground">{clock(item.exchange_time)}</div>
      <div><div className="font-semibold text-xs">{item.stock_code}</div><div className={`text-[11px] ${actionTypes.has(item.event_type) ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"}`}>{eventLabel[item.event_type] || item.event_type}</div></div>
      <div className="flex items-center gap-2 text-xs"><GitCommitHorizontal className="h-4 w-4 text-sky-500" /><span>{item.old_state || "--"}</span><ArrowRight className="h-3 w-3 text-muted-foreground" /><span className="font-medium">{item.new_state || "--"}</span></div>
      <div className="col-start-2 truncate text-xs text-muted-foreground md:col-auto" title={reasonLabel[item.reason_code] || item.reason_code}>{reasonLabel[item.reason_code] || item.reason_code}</div>
    </div>)}
    {!items.length && <div className="flex h-36 items-center justify-center text-sm text-muted-foreground">暂无决策事件</div>}
  </div>;
}
