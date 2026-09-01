import { ArrowRight, GitCommitHorizontal } from "lucide-react";
import type { V2Decision } from "@/lib/api/v2";
import { clock } from "./format";

const actionTypes = new Set(["BUY_CONFIRMED", "EXIT_RISK_CONFIRMED", "ROTATION_PROPOSED"]);

export function DecisionStream({ items, compact = false }: { items: V2Decision[]; compact?: boolean }) {
  return <div className="divide-y divide-border/70">
    {items.slice(0, compact ? 8 : undefined).map((item) => <div key={item.event_id} className="grid min-h-14 grid-cols-[64px_1fr] gap-3 px-3 py-2 md:grid-cols-[64px_130px_1fr_180px] md:items-center">
      <div className="font-mono text-xs text-muted-foreground">{clock(item.exchange_time)}</div>
      <div><div className="font-semibold text-xs">{item.stock_code}</div><div className={`text-[11px] ${actionTypes.has(item.event_type) ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"}`}>{item.event_type}</div></div>
      <div className="flex items-center gap-2 text-xs"><GitCommitHorizontal className="h-4 w-4 text-sky-500" /><span>{item.old_state || "--"}</span><ArrowRight className="h-3 w-3 text-muted-foreground" /><span className="font-medium">{item.new_state || "--"}</span></div>
      <div className="col-start-2 truncate text-xs text-muted-foreground md:col-auto" title={item.reason_code}>{item.reason_code}</div>
    </div>)}
    {!items.length && <div className="flex h-36 items-center justify-center text-sm text-muted-foreground">暂无决策事件</div>}
  </div>;
}
