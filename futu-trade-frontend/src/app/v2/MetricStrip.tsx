import { Activity, ArrowLeftRight, CircleDollarSign, Target } from "lucide-react";
import type { V2Cockpit } from "@/lib/api/v2";

export function MetricStrip({ data }: { data?: V2Cockpit }) {
  const metrics = [
    { label: "确认候选", value: data?.summary.confirmed_candidates ?? 0, icon: Target, tone: "text-emerald-500" },
    { label: "持仓", value: data?.summary.open_positions ?? 0, icon: CircleDollarSign, tone: "text-sky-500" },
    { label: "待处理", value: data?.summary.actionable_positions ?? 0, icon: ArrowLeftRight, tone: "text-amber-500" },
    { label: "评估样本", value: data?.summary.evaluated_signals ?? 0, icon: Activity, tone: "text-fuchsia-500" },
  ];
  return (
    <section className="grid grid-cols-2 border-y border-border/80 bg-card/40 lg:grid-cols-4">
      {metrics.map(({ label, value, icon: Icon, tone }, index) => (
        <div key={label} className={`flex min-h-20 items-center gap-3 px-4 py-3 ${index > 0 ? "border-l border-border/70" : ""}`}>
          <Icon className={`h-5 w-5 ${tone}`} aria-hidden="true" />
          <div>
            <div className="text-xl font-semibold tabular-nums">{value}</div>
            <div className="text-xs text-muted-foreground">{label}</div>
          </div>
        </div>
      ))}
    </section>
  );
}
