import { ArrowRight, Gauge } from "lucide-react";
import type { V2Position } from "@/lib/api/v2";
import { clock, pct, tone } from "./format";

export function PositionTable({ items, compact = false }: { items: V2Position[]; compact?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[940px] text-left text-xs">
        <thead className="border-b border-border bg-muted/35 text-muted-foreground"><tr>
          <th className="px-3 py-2 font-medium">持仓</th><th className="px-3 py-2 font-medium">状态 / 动作</th>
          <th className="px-3 py-2 font-medium">当前 / MFE / MAE</th><th className="px-3 py-2 font-medium">效率</th>
          <th className="px-3 py-2 font-medium">峰值回撤 / 资金衰减</th><th className="px-3 py-2 font-medium">换票比较</th>
          <th className="px-3 py-2 font-medium">更新时间</th>
        </tr></thead>
        <tbody className="divide-y divide-border/70">
          {items.slice(0, compact ? 5 : undefined).map((item) => {
            const efficiency = item.efficiency;
            const currentReturn = efficiency?.current_return_pct ?? item.position?.current_return_pct;
            return <tr key={item.stock_code} className="h-16 hover:bg-muted/25">
              <td className="px-3 py-2"><div className="font-semibold">{item.stock_name || item.stock_code}</div><div className="text-muted-foreground">{item.stock_code}</div></td>
              <td className="px-3 py-2"><div className="font-medium">{item.status}</div><div className="text-muted-foreground">{item.last_action || "HOLD"}</div></td>
              <td className="px-3 py-2 tabular-nums"><span className={tone(currentReturn)}>{pct(currentReturn)}</span><span className="mx-1 text-border">/</span><span className="text-emerald-600 dark:text-emerald-400">{pct(item.mfe_pct)}</span><span className="mx-1 text-border">/</span><span className="text-rose-600 dark:text-rose-400">{pct(item.mae_pct)}</span></td>
              <td className="px-3 py-2"><div className="flex items-center gap-2"><Gauge className="h-4 w-4 text-sky-500" /><span className="text-base font-semibold tabular-nums">{efficiency?.score?.toFixed(1) ?? "--"}</span></div><div className="text-muted-foreground">高点后 {efficiency?.minutes_since_high?.toFixed(0) ?? "--"} 分钟</div></td>
              <td className="px-3 py-2 tabular-nums"><div className={tone(efficiency?.drawdown_from_peak_pct)}>{pct(efficiency?.drawdown_from_peak_pct)}</div><div className="text-muted-foreground">衰减 {pct((efficiency?.flow_drawdown_ratio ?? 0) * 100, 0)}</div></td>
              <td className="px-3 py-2">{item.rotation ? <div><div className="flex items-center gap-1 font-medium">{item.stock_code}<ArrowRight className="h-3 w-3" />{item.rotation.buy_stock_code}</div><div className="text-emerald-600 dark:text-emerald-400">净优势 {item.rotation.net_advantage_score?.toFixed(1) ?? "--"}</div></div> : <span className="text-muted-foreground">继续持有</span>}</td>
              <td className="px-3 py-2 text-muted-foreground">{clock(item.updated_at)}</td>
            </tr>;
          })}
        </tbody>
      </table>
      {!items.length && <div className="flex h-36 items-center justify-center text-sm text-muted-foreground">暂无持仓效率状态</div>}
    </div>
  );
}
