"use client";

import { useState, useEffect, useCallback } from "react";
import { flowSignalApi, type AllRulesResponse, type FlowSignalRecord } from "@/lib/api/flow-signal";
import { FlowSignalTab, RiskTab, StrategyTab } from "@/app/flow-signals/components";

export default function FlowSignalsPanel() {
  const [tab, setTab] = useState<"flow" | "risk" | "strategy">("flow");
  const [allRules, setAllRules] = useState<AllRulesResponse | null>(null);
  const [history, setHistory] = useState<FlowSignalRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("ALL");

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [r, h] = await Promise.all([
        flowSignalApi.getAllRules(),
        flowSignalApi.getHistory({ limit: 100 }),
      ]);
      if (r.success && r.data) setAllRules(r.data);
      if (h.success && h.data) setHistory(h.data.signals || []);
    } catch (e) {
      console.error("获取交易规则失败:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const tabs = [
    { key: "flow" as const, icon: "📊", label: "资金流向信号", count: allRules?.flow_rules?.length },
    { key: "risk" as const, icon: "⚖️", label: "风险管理", count: allRules?.risk_rules?.basic_rules?.length },
    { key: "strategy" as const, icon: "📈", label: "趋势反转策略", count: null },
  ];

  if (loading) {
    return (
      <div className="p-8 space-y-6 animate-pulse">
        <div className="h-8 w-52 bg-gray-100 rounded-xl" />
        <div className="h-14 bg-gray-50 rounded-2xl" />
        <div className="grid grid-cols-4 gap-4">{[1,2,3,4].map(i => <div key={i} className="h-36 bg-gray-50 rounded-2xl" />)}</div>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[22px] font-bold text-gray-900 tracking-tight">交易规则中心</h1>
          <p className="text-gray-400 text-[13px] mt-0.5">系统运行的全部交易规则 · 实时状态监控</p>
        </div>
        <div className="flex items-center gap-3">
          {allRules?.engine_enabled && (
            <span className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-50 text-emerald-600 rounded-full text-[11px] font-semibold border border-emerald-200">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              引擎运行中
            </span>
          )}
          <button
            onClick={fetchData}
            className="px-4 py-1.5 bg-white hover:bg-gray-50 text-gray-600 rounded-xl text-[13px] font-medium border border-gray-200 shadow-sm transition-all active:scale-[0.97]"
          >
            刷新
          </button>
        </div>
      </div>

      {/* Apple Segmented Control */}
      <div className="flex gap-0.5 p-1 rounded-2xl bg-gray-100/80 border border-gray-200/60 backdrop-blur-xl">
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-[13px] font-semibold transition-all duration-200 ${
              tab === t.key
                ? "bg-white text-gray-900 shadow-sm border border-gray-200/80"
                : "text-gray-400 hover:text-gray-600"
            }`}
          >
            <span>{t.icon}</span>
            <span>{t.label}</span>
            {t.count != null && t.count > 0 && (
              <span className={`px-1.5 py-0.5 rounded-md text-[10px] font-bold ${
                tab === t.key ? "bg-gray-100 text-gray-500" : "bg-gray-200/50 text-gray-400"
              }`}>{t.count}</span>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="min-h-[500px]">
        {tab === "flow" && allRules && <FlowSignalTab rules={allRules.flow_rules} history={history} filter={filter} onFilter={setFilter} />}
        {tab === "risk" && allRules && <RiskTab rules={allRules.risk_rules} />}
        {tab === "strategy" && allRules && <StrategyTab rules={allRules.strategy_rules} />}
      </div>
    </div>
  );
}
