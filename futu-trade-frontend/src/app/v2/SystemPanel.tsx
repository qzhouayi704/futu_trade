import { CheckCircle2, CircleOff, Database, Radio, ShieldCheck } from "lucide-react";
import type { V2Health } from "@/lib/api/v2";

export function SystemPanel({ data }: { data?: V2Health }) {
  const running = data?.status === "running";
  const queueRatio = data?.event_queue.capacity ? data.event_queue.size / data.event_queue.capacity : 0;
  return <div className="grid gap-0 border-y border-border lg:grid-cols-2">
    <section className="border-b border-border p-5 lg:border-b-0 lg:border-r">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold"><Radio className="h-4 w-4 text-emerald-500" />运行边界</h2>
      <div className="space-y-3 text-sm">
        <div className="flex items-center justify-between"><span className="text-muted-foreground">V2 Runtime</span><span className="flex items-center gap-2 font-medium">{running ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : <CircleOff className="h-4 w-4 text-muted-foreground" />}{data?.status || "unknown"}</span></div>
        <div className="flex items-center justify-between"><span className="text-muted-foreground">模式</span><strong>{data?.mode?.toUpperCase() || "DISABLED"}</strong></div>
        <div className="flex items-center justify-between"><span className="text-muted-foreground">订单执行</span><span className="flex items-center gap-2 font-medium text-emerald-600 dark:text-emerald-400"><ShieldCheck className="h-4 w-4" />关闭</span></div>
      </div>
    </section>
    <section className="p-5">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold"><Database className="h-4 w-4 text-sky-500" />事件队列</h2>
      <div className="mb-2 flex justify-between text-sm"><span className="text-muted-foreground">{data?.event_queue.size ?? 0} / {data?.event_queue.capacity ?? 0}</span><span>丢弃 {data?.event_queue.dropped ?? 0}</span></div>
      <div className="h-2 overflow-hidden rounded-sm bg-muted"><div className={`h-full ${queueRatio > 0.8 ? "bg-rose-500" : queueRatio > 0.5 ? "bg-amber-500" : "bg-emerald-500"}`} style={{ width: `${Math.min(100, queueRatio * 100)}%` }} /></div>
      <div className="mt-5 grid grid-cols-2 gap-px bg-border">{(data?.tasks || []).slice(0, 8).map((task, index) => <div key={`${task.name}-${index}`} className="flex justify-between bg-background px-3 py-2 text-xs"><span className="truncate text-muted-foreground">{task.name || "task"}</span><span>{task.failure ? "FAILED" : task.status || "OK"}</span></div>)}</div>
    </section>
  </div>;
}
