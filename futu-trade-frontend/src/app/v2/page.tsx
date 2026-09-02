"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, BarChart3, BriefcaseBusiness, ListFilter, RefreshCw, ServerCog } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useSocket } from "@/lib/socket";
import { v2Api } from "@/lib/api/v2";
import { CandidateTable } from "./CandidateTable";
import { CandidateWorkspace } from "./CandidateWorkspace";
import { DecisionStream } from "./DecisionStream";
import { MetricStrip } from "./MetricStrip";
import { OutcomeDistribution } from "./OutcomeDistribution";
import { PositionTable } from "./PositionTable";
import { ShadowAcceptance } from "./ShadowAcceptance";
import { SystemPanel } from "./SystemPanel";

const tabs = [
  { id: "cockpit", label: "盘中驾驶舱", icon: Activity },
  { id: "candidates", label: "候选池", icon: ListFilter },
  { id: "positions", label: "持仓与换票", icon: BriefcaseBusiness },
  { id: "review", label: "复盘中心", icon: BarChart3 },
  { id: "system", label: "系统状态", icon: ServerCog },
] as const;
type TabId = (typeof tabs)[number]["id"];

export default function V2WorkbenchPage() {
  const [tab, setTab] = useState<TabId>("cockpit");
  const client = useQueryClient();
  const { socket, isConnected } = useSocket();
  const cockpit = useQuery({ queryKey: ["v2", "cockpit"], queryFn: v2Api.cockpit, refetchInterval: 30_000 });
  const candidates = useQuery({ queryKey: ["v2", "candidates"], queryFn: v2Api.candidates, refetchInterval: 30_000 });
  const positions = useQuery({ queryKey: ["v2", "positions"], queryFn: v2Api.positions, refetchInterval: 30_000 });
  const decisions = useQuery({ queryKey: ["v2", "decisions"], queryFn: v2Api.decisions, refetchInterval: 30_000 });
  const distribution = useQuery({ queryKey: ["v2", "distribution"], queryFn: v2Api.distribution, refetchInterval: 60_000 });
  const acceptance = useQuery({ queryKey: ["v2", "shadow-acceptance"], queryFn: v2Api.shadowAcceptance, refetchInterval: 60_000 });
  const health = useQuery({ queryKey: ["v2", "health"], queryFn: v2Api.health, refetchInterval: 15_000 });

  useEffect(() => {
    if (!socket) return;
    const refresh = () => client.invalidateQueries({ queryKey: ["v2"] });
    socket.on("v2_trade_alert", refresh);
    return () => { socket.off("v2_trade_alert", refresh); };
  }, [socket, client]);

  const refreshAll = () => client.invalidateQueries({ queryKey: ["v2"] });
  const hasError = [cockpit, candidates, positions, decisions, distribution, acceptance, health].some((query) => query.isError);

  return <TooltipProvider>
    <div className="min-h-screen bg-background">
      <header className="border-b border-border bg-card/40 px-4 py-4 md:px-6">
        <div className="mx-auto flex max-w-[1680px] items-center justify-between gap-4">
          <div className="min-w-0"><h1 className="text-xl font-semibold">V2 交易工作台</h1><div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground"><span className={`h-2 w-2 rounded-full ${isConnected ? "bg-emerald-500" : "bg-rose-500"}`} />{cockpit.data?.mode?.toUpperCase() || "DISABLED"}<span>·</span><span>{cockpit.data?.strategy_version || "尚无策略版本"}</span><span>·</span><span className="text-emerald-600 dark:text-emerald-400">订单执行关闭</span></div></div>
          <Tooltip><TooltipTrigger asChild><Button variant="outline" size="icon" onClick={refreshAll} disabled={cockpit.isFetching} aria-label="刷新 V2 数据"><RefreshCw className={cockpit.isFetching ? "animate-spin" : ""} /></Button></TooltipTrigger><TooltipContent>刷新全部视图</TooltipContent></Tooltip>
        </div>
      </header>
      <div className="border-b border-border px-2 md:px-6"><nav className="mx-auto flex max-w-[1680px] overflow-x-auto" aria-label="V2 工作视图">{tabs.map(({ id, label, icon: Icon }) => <button key={id} onClick={() => setTab(id)} className={`flex h-11 shrink-0 items-center gap-2 border-b-2 px-3 text-xs font-medium md:px-4 ${tab === id ? "border-emerald-500 text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}><Icon className="h-4 w-4" />{label}</button>)}</nav></div>
      <main className="mx-auto max-w-[1680px] px-3 py-4 md:px-6 md:py-6">
        {hasError && <div className="mb-4 border-l-2 border-rose-500 bg-rose-500/8 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">部分 V2 Read Model 暂不可用，系统会继续重试。</div>}
        {tab === "cockpit" && <div className="space-y-6"><MetricStrip data={cockpit.data} /><section><h2 className="mb-2 text-sm font-semibold">优先候选</h2><CandidateTable items={cockpit.data?.candidates || []} compact /></section><section><h2 className="mb-2 text-sm font-semibold">持仓效率</h2><PositionTable items={cockpit.data?.positions || []} compact /></section><section><h2 className="mb-2 text-sm font-semibold">最新决策</h2><DecisionStream items={cockpit.data?.decisions || []} compact /></section></div>}
        {tab === "candidates" && <CandidateWorkspace currentItems={candidates.data?.items || []} />}
        {tab === "positions" && <PositionTable items={positions.data?.items || []} />}
        {tab === "review" && <div className="space-y-10"><ShadowAcceptance data={acceptance.data} /><OutcomeDistribution data={distribution.data} /><section><h2 className="mb-2 text-sm font-semibold">事件回放</h2><DecisionStream items={decisions.data?.items || []} /></section></div>}
        {tab === "system" && <SystemPanel data={health.data} />}
      </main>
    </div>
  </TooltipProvider>;
}
