import { BarChart3, Timer } from "lucide-react";
import type { V2Distribution } from "@/lib/api/v2";
import { duration, pct, tone } from "./format";

function PercentileLine({ data }: { data: V2Distribution }) {
  const entries = ["p10", "p25", "p50", "p75", "p90", "p95"].map((key) => [key.toUpperCase(), data.mfe.percentiles[key]] as const);
  return <div className="grid grid-cols-3 divide-x divide-border border-y border-border md:grid-cols-6">
    {entries.map(([label, value]) => <div key={label} className="px-3 py-3 text-center"><div className={`text-base font-semibold tabular-nums ${tone(value)}`}>{pct(value)}</div><div className="mt-1 text-[11px] text-muted-foreground">{label} 日内最高</div></div>)}
  </div>;
}

function Histogram({ data }: { data: V2Distribution }) {
  const bins = data.mfe.histogram || [];
  const max = Math.max(1, ...bins.map((item) => item.count));
  return <div className="grid h-44 grid-cols-6 items-end gap-2 border-b border-border px-3 pt-5">
    {bins.map((item) => <div key={item.label} className="flex h-full flex-col justify-end text-center">
      <span className="mb-1 text-xs font-semibold tabular-nums">{item.count}</span>
      <div className={`mx-auto w-full max-w-16 rounded-t-sm ${item.label.startsWith("<") || item.label.startsWith("-") ? "bg-rose-500/75" : item.label.includes("5") ? "bg-emerald-500" : "bg-sky-500/80"}`} style={{ height: `${Math.max(3, item.count / max * 112)}px` }} />
      <span className="mt-2 h-8 text-[10px] text-muted-foreground">{item.label}</span>
    </div>)}
  </div>;
}

export function OutcomeDistribution({ data }: { data?: V2Distribution }) {
  if (!data) return <div className="h-64 animate-pulse bg-muted/30" />;
  return <div className="space-y-6">
    <PercentileLine data={data} />
    <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
      <section>
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><BarChart3 className="h-4 w-4 text-sky-500" />日内最高收益分布</div>
        <Histogram data={data} />
      </section>
      <section>
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><Timer className="h-4 w-4 text-amber-500" />阈值与换票验证</div>
        <div className="divide-y divide-border border-y border-border text-sm">
          <div className="flex justify-between px-2 py-3"><span className="text-muted-foreground">达到 1.5%</span><strong>{pct(data.milestones.reached_1_5_ratio * 100, 1)}</strong></div>
          <div className="flex justify-between px-2 py-3"><span className="text-muted-foreground">达到 3%</span><strong>{pct(data.milestones.reached_3_ratio * 100, 1)}</strong></div>
          <div className="flex justify-between px-2 py-3"><span className="text-muted-foreground">达到 5%</span><strong>{pct(data.milestones.reached_5_ratio * 100, 1)}</strong></div>
          <div className="flex justify-between px-2 py-3"><span className="text-muted-foreground">换票净优势中位数</span><strong className={tone(data.rotation_advantage.percentiles.p50)}>{pct(data.rotation_advantage.percentiles.p50)}</strong></div>
          <div className="flex justify-between px-2 py-3"><span className="text-muted-foreground">MFE 最大值</span><strong className={tone(data.mfe.max)}>{pct(data.mfe.max)}</strong></div>
        </div>
      </section>
    </div>
    <div className="overflow-x-auto border-t border-border">
      <table className="w-full min-w-[900px] text-left text-xs"><thead className="bg-muted/35 text-muted-foreground"><tr>
        <th className="px-3 py-2 font-medium">样本</th><th className="px-3 py-2 font-medium">MFE / MAE</th><th className="px-3 py-2 font-medium">1.5 / 3 / 5 到达</th><th className="px-3 py-2 font-medium">收盘 / 次日</th><th className="px-3 py-2 font-medium">换票 / 原股</th>
      </tr></thead><tbody className="divide-y divide-border/70">{data.items.map((item) => <tr key={item.event_id}>
        <td className="px-3 py-2"><div className="font-semibold">{item.stock_name || item.stock_code}</div><div className="text-muted-foreground">{item.event_type}</div></td>
        <td className="px-3 py-2 tabular-nums"><span className={tone(item.mfe_pct)}>{pct(item.mfe_pct)}</span> / <span className={tone(item.mae_pct)}>{pct(item.mae_pct)}</span></td>
        <td className="px-3 py-2 tabular-nums">{duration(item.time_to_1_5_seconds)} / {duration(item.time_to_3_seconds)} / {duration(item.time_to_5_seconds)}</td>
        <td className="px-3 py-2 tabular-nums"><span className={tone(item.close_return_pct)}>{pct(item.close_return_pct)}</span> / <span className={tone(item.next_day_return_pct)}>{pct(item.next_day_return_pct)}</span></td>
        <td className="px-3 py-2 tabular-nums"><span className={tone(item.rotation_return_pct)}>{pct(item.rotation_return_pct)}</span> / <span className={tone(item.hold_control_return_pct)}>{pct(item.hold_control_return_pct)}</span></td>
      </tr>)}</tbody></table>
    </div>
  </div>;
}
