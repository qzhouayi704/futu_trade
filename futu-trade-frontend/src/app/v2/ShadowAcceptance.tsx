import { CheckCircle2, CircleAlert, Gauge, GitCompareArrows } from "lucide-react";
import type { V2CohortMetric, V2ShadowAcceptance } from "@/lib/api/v2";
import { duration, pct, tone } from "./format";

const labels: Record<string, string> = {
  NORMAL: "正常市场", WEAK: "弱市", EXTREME: "极弱市场", UNKNOWN: "上下文缺失",
  FAST_15M: "15 分钟确认", SLOW_60M: "60 分钟确认",
  SINGLE: "单次流入", MULTI_2: "2 次独立流入", MULTI_3_PLUS: "3 次及以上",
  NO_LARGE_OUTFLOW: "无大单流出", MINOR_OUTFLOW: "有流出未抵消",
  MATERIAL_OFFSET: "流出明显抵消", FIRST_INFLOW_CONTROL: "首次流入对照",
  CONFIRMED_ENTRY: "多次流入确认",
};

function Success({ metric }: { metric: V2CohortMetric }) {
  return <span className={tone(metric.reached_1_5_ratio)}>{pct(metric.reached_1_5_ratio * 100, 1)}</span>;
}

function CohortTable({ title, items }: { title: string; items: V2CohortMetric[] }) {
  return <section className="min-w-0">
    <h3 className="mb-2 text-xs font-semibold text-muted-foreground">{title}</h3>
    <div className="overflow-x-auto border-y border-border">
      <table className="w-full min-w-[460px] text-left text-xs">
        <thead className="bg-muted/35 text-muted-foreground"><tr><th className="px-3 py-2 font-medium">分组</th><th className="px-3 py-2 font-medium">样本</th><th className="px-3 py-2 font-medium">达到 1.5%</th><th className="px-3 py-2 font-medium">MFE 中位</th><th className="px-3 py-2 font-medium">耗时中位</th></tr></thead>
        <tbody className="divide-y divide-border/70">{items.map((item) => <tr key={item.key}>
          <td className="px-3 py-2 font-medium">{labels[item.key || ""] || item.key}</td>
          <td className="px-3 py-2 tabular-nums">{item.sample_count}</td>
          <td className="px-3 py-2 font-semibold tabular-nums"><Success metric={item} /></td>
          <td className={`px-3 py-2 tabular-nums ${tone(item.mfe.percentiles.p50)}`}>{pct(item.mfe.percentiles.p50)}</td>
          <td className="px-3 py-2 tabular-nums text-muted-foreground">{duration(item.median_time_to_1_5_seconds)}</td>
        </tr>)}</tbody>
      </table>
    </div>
  </section>;
}

export function ShadowAcceptance({ data }: { data?: V2ShadowAcceptance }) {
  if (!data) return <div className="h-72 animate-pulse bg-muted/30" />;
  const progress = Math.min(100, data.observed_days / data.target_days * 100);
  return <section className="space-y-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><div className="flex items-center gap-2 text-sm font-semibold"><Gauge className="h-4 w-4 text-emerald-500" />10 日影子验收</div><p className="mt-1 text-xs text-muted-foreground">以信号后日内最高达到 1.5% 为主要成功口径，首个流入仅作对照。</p></div>
      <div className={`flex items-center gap-1.5 text-xs font-medium ${data.ready ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"}`}>{data.ready ? <CheckCircle2 className="h-4 w-4" /> : <CircleAlert className="h-4 w-4" />}{data.ready ? "样本期完成" : `累计 ${data.observed_days}/${data.target_days} 个交易日`}</div>
    </div>
    <div className="h-1.5 overflow-hidden bg-muted"><div className="h-full bg-emerald-500 transition-all" style={{ width: `${progress}%` }} /></div>
    <div className="grid grid-cols-2 divide-x divide-y divide-border border-y border-border lg:grid-cols-4 lg:divide-y-0">
      <div className="px-3 py-3"><div className="text-[11px] text-muted-foreground">确认买点成功率</div><div className="mt-1 text-lg font-semibold tabular-nums"><Success metric={data.entry_summary} /></div><div className="text-[10px] text-muted-foreground">{data.entry_summary.sample_count} 个样本</div></div>
      <div className="px-3 py-3"><div className="text-[11px] text-muted-foreground">首次流入对照</div><div className="mt-1 text-lg font-semibold tabular-nums"><Success metric={data.first_inflow_control} /></div><div className="text-[10px] text-muted-foreground">{data.first_inflow_control.sample_count} 个样本</div></div>
      <div className="px-3 py-3"><div className="text-[11px] text-muted-foreground">换票胜率</div><div className="mt-1 text-lg font-semibold tabular-nums">{pct(data.rotation_summary.rotation_win_ratio * 100, 1)}</div><div className="text-[10px] text-muted-foreground">{data.rotation_summary.comparable_count} 组可比</div></div>
      <div className="px-3 py-3"><div className="text-[11px] text-muted-foreground">换票净优势中位</div><div className={`mt-1 text-lg font-semibold tabular-nums ${tone(data.rotation_summary.advantage.percentiles.p50)}`}>{pct(data.rotation_summary.advantage.percentiles.p50)}</div><div className="text-[10px] text-muted-foreground">相对继续持有</div></div>
    </div>
    {data.warnings.length > 0 && <div className="flex items-start gap-2 border-l-2 border-amber-500 bg-amber-500/8 px-3 py-2 text-xs text-amber-700 dark:text-amber-300"><CircleAlert className="mt-0.5 h-4 w-4 shrink-0" /><span>{data.warnings.join("；")}</span></div>}
    <div className="grid gap-6 xl:grid-cols-2">
      <CohortTable title="市场环境" items={data.cohorts.market_regime} />
      <CohortTable title="确认窗口" items={data.cohorts.confirmation_window} />
      <CohortTable title="独立资金流入次数" items={data.cohorts.inflow_frequency} />
      <CohortTable title="流入后的大单流出" items={data.cohorts.outflow_context} />
    </div>
    <section>
      <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-muted-foreground"><GitCompareArrows className="h-4 w-4" />逐日核对</div>
      <div className="overflow-x-auto border-y border-border"><table className="w-full min-w-[680px] text-left text-xs"><thead className="bg-muted/35 text-muted-foreground"><tr><th className="px-3 py-2 font-medium">交易日</th><th className="px-3 py-2 font-medium">确认买点</th><th className="px-3 py-2 font-medium">成功率</th><th className="px-3 py-2 font-medium">首次流入</th><th className="px-3 py-2 font-medium">对照成功率</th><th className="px-3 py-2 font-medium">换票可比</th></tr></thead><tbody className="divide-y divide-border/70">{data.daily.map((day) => <tr key={day.trade_date}><td className="px-3 py-2 font-medium tabular-nums">{day.trade_date}</td><td className="px-3 py-2 tabular-nums">{day.entry.sample_count}</td><td className="px-3 py-2 font-semibold tabular-nums"><Success metric={day.entry} /></td><td className="px-3 py-2 tabular-nums">{day.first_inflow.sample_count}</td><td className="px-3 py-2 tabular-nums"><Success metric={day.first_inflow} /></td><td className="px-3 py-2 tabular-nums">{day.rotation.comparable_count}</td></tr>)}</tbody></table></div>
    </section>
  </section>;
}
