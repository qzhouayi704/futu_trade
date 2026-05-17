"use client";

import type {
  FlowRule, FlowSignalRecord, AllRulesResponse,
  RiskBasicRule, CoordinatorLevel, DynamicDimension, StrategyRules,
} from "@/lib/api/flow-signal";

// ==================== Apple 浅色风格常量 ====================
const card = "bg-white/80 backdrop-blur-xl border border-gray-200/60 shadow-sm rounded-2xl";
const cardHover = "hover:shadow-md hover:border-gray-300/60 transition-all duration-300";

/** 将 SQLite UTC 时间字符串转为本地时间显示 */
function utcToLocal(utcStr: string): string {
  if (!utcStr) return "";
  try {
    // SQLite CURRENT_TIMESTAMP 格式: "2026-05-05 06:13:31"（UTC）
    const d = new Date(utcStr.includes("T") ? utcStr : utcStr.replace(" ", "T") + "Z");
    if (isNaN(d.getTime())) return utcStr;
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  } catch {
    return utcStr;
  }
}

// ==================== 通用组件 ====================
export function SectionHeader({ title, subtitle, icon }: { title: string; subtitle: string; icon: string }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <span className="text-xl">{icon}</span>
      <div><h3 className="text-gray-900 font-semibold text-[15px]">{title}</h3><p className="text-gray-400 text-xs">{subtitle}</p></div>
    </div>
  );
}

export function SignalBadge({ type }: { type: "BUY" | "SELL" | "ALERT" }) {
  const c = { BUY: "bg-emerald-50 text-emerald-600 border-emerald-200", SELL: "bg-rose-50 text-rose-600 border-rose-200", ALERT: "bg-amber-50 text-amber-600 border-amber-200" };
  const l = { BUY: "买入", SELL: "卖出", ALERT: "提醒" };
  return <span className={`px-2.5 py-0.5 rounded-full border text-[11px] font-semibold ${c[type]}`}>{l[type]}</span>;
}

// ==================== Tab1: 资金流向 ====================
export function FlowSignalTab({ rules, history, filter, onFilter }: {
  rules: FlowRule[]; history: FlowSignalRecord[]; filter: string; onFilter: (v: string) => void;
}) {
  const filtered = filter === "ALL" ? history : history.filter(s => s.signal_type === filter);
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        {rules.map(r => <FlowCard key={r.rule_id} rule={r} />)}
      </div>
      <div className={`${card} p-5`}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-gray-900 font-semibold text-[15px]">信号历史</h3>
          <div className="flex gap-1 p-1 rounded-xl bg-gray-100/80">
            {(["ALL","BUY","SELL","ALERT"] as const).map(t => (
              <button key={t} onClick={() => onFilter(t)} className={`px-3 py-1.5 rounded-lg text-[11px] font-semibold transition-all ${filter === t ? "bg-white text-gray-900 shadow-sm" : "text-gray-400 hover:text-gray-600"}`}>
                {t === "ALL" ? "全部" : t === "BUY" ? "买入" : t === "SELL" ? "卖出" : "提醒"}
              </button>
            ))}
          </div>
        </div>
        {filtered.length === 0 ? <p className="text-gray-300 text-center py-10 text-sm">暂无信号记录</p> : (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead><tr className="text-gray-400 text-xs border-b border-gray-100">
                <th className="text-left py-2.5 px-3 font-medium">时间</th>
                <th className="text-left py-2.5 px-3 font-medium">股票</th>
                <th className="text-left py-2.5 px-3 font-medium">规则</th>
                <th className="text-center py-2.5 px-3 font-medium">类型</th>
                <th className="text-right py-2.5 px-3 font-medium">价格</th>
                <th className="text-left py-2.5 px-3 font-medium">原因</th>
              </tr></thead>
              <tbody>{filtered.slice(0, 50).map(s => (
                <tr key={s.id} className="border-t border-gray-50 hover:bg-gray-50/50 transition-colors">
                  <td className="py-2.5 px-3 text-gray-400 font-mono text-xs">{utcToLocal(s.created_at)}</td>
                  <td className="py-2.5 px-3 text-gray-900 font-medium">{s.stock_name || s.stock_code}</td>
                  <td className="py-2.5 px-3 text-gray-500">{s.rule_name}</td>
                  <td className="py-2.5 px-3 text-center"><SignalBadge type={s.signal_type} /></td>
                  <td className="py-2.5 px-3 text-right text-gray-800 font-mono">{s.price?.toFixed(2)}</td>
                  <td className="py-2.5 px-3 text-gray-400 max-w-[240px] truncate">{s.reason}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function FlowCard({ rule }: { rule: FlowRule }) {
  const accent = {
    BUY: "from-emerald-50 to-white border-emerald-200/60",
    SELL: "from-rose-50 to-white border-rose-200/60",
    ALERT: "from-amber-50 to-white border-amber-200/60",
  };
  return (
    <div className={`rounded-2xl border p-4 bg-gradient-to-br ${accent[rule.signal_type]} backdrop-blur-xl shadow-sm ${cardHover} group`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] font-mono text-gray-300">{rule.rule_id}</span>
        <SignalBadge type={rule.signal_type} />
      </div>
      <h4 className="text-gray-900 font-semibold text-sm mb-1.5 group-hover:text-gray-700 transition-colors">{rule.rule_name}</h4>
      <p className="text-gray-500 text-xs leading-relaxed mb-2">{rule.condition}</p>
      <p className="text-gray-400 text-[11px]">💡 {rule.suggestion}</p>
    </div>
  );
}

// ==================== Tab2: 风险管理 ====================
export function RiskTab({ rules }: { rules: AllRulesResponse["risk_rules"] }) {
  return (
    <div className="space-y-8">
      <div>
        <SectionHeader title="基础止盈止损" subtitle="持仓风控的核心规则" icon="🎯" />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {rules.basic_rules.map(r => <RiskCard key={r.type} rule={r} />)}
        </div>
      </div>
      <div>
        <SectionHeader title="流动性自适应参数" subtitle="不同流动性等级使用不同阈值" icon="💧" />
        <LiquidityTable bounds={rules.dynamic_stop_loss.liquidity_bounds} rules={rules.basic_rules} />
      </div>
      <div>
        <SectionHeader title="风险协调器" subtitle="多级风控模块按优先级串联执行" icon="🔗" />
        <div className="space-y-2">{rules.coordinator_levels.map(l => <LevelCard key={l.priority} level={l} />)}</div>
      </div>
      <div>
        <SectionHeader title="动态止损维度" subtitle="五维度综合实时计算调整因子" icon="🎛️" />
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {rules.dynamic_stop_loss.dimensions.map(d => <DimCard key={d.name} dim={d} />)}
        </div>
      </div>
    </div>
  );
}

function RiskCard({ rule }: { rule: RiskBasicRule }) {
  const isSL = rule.type.includes("stop_loss");
  const urgC = rule.urgency >= 9 ? "text-rose-600 bg-rose-50" : rule.urgency >= 7 ? "text-amber-600 bg-amber-50" : "text-blue-600 bg-blue-50";
  return (
    <div className={`rounded-2xl border p-4 shadow-sm ${cardHover} ${isSL ? "border-rose-200/50 bg-gradient-to-br from-rose-50/50 to-white" : "border-emerald-200/50 bg-gradient-to-br from-emerald-50/50 to-white"}`}>
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-gray-900 font-semibold text-sm">{rule.name}</h4>
        <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${urgC}`}>U{rule.urgency}</span>
      </div>
      <p className="text-gray-400 text-xs mb-3 leading-relaxed">{rule.description}</p>
      <div className="flex items-center justify-between">
        <span className="text-gray-300 text-[11px]">默认</span>
        <span className={`font-mono text-sm font-bold ${isSL ? "text-rose-500" : "text-emerald-500"}`}>{rule.default_value}</span>
      </div>
      {rule.liquidity_adaptive && (
        <div className="mt-3 pt-3 border-t border-gray-100">
          <span className="text-gray-300 text-[10px]">💧 按流动性</span>
          <div className="flex gap-1.5 mt-1.5">{Object.entries(rule.liquidity_adaptive).map(([k, v]) => (
            <span key={k} className="text-[10px] px-2 py-0.5 rounded-full bg-gray-50 text-gray-500 border border-gray-200/60">{k}: {v}</span>
          ))}</div>
        </div>
      )}
    </div>
  );
}

function LiquidityTable({ bounds, rules }: {
  bounds: Record<string, { stop_loss: string; take_profit: string; label: string }>;
  rules: RiskBasicRule[];
}) {
  const adaptive = rules.filter(r => r.liquidity_adaptive);
  const levels = ["A", "B", "C"] as const;
  const lc = { A: "text-emerald-600", B: "text-blue-600", C: "text-amber-600" };
  return (
    <div className={`${card} overflow-hidden`}>
      <table className="w-full text-[13px]">
        <thead><tr className="bg-gray-50/80">
          <th className="text-left py-3 px-4 text-gray-400 font-medium text-xs">参数</th>
          {levels.map(l => <th key={l} className={`text-center py-3 px-4 font-semibold text-xs ${lc[l]}`}>{l}级 · {bounds[l]?.label}</th>)}
        </tr></thead>
        <tbody>
          {adaptive.map(r => (
            <tr key={r.type} className="border-t border-gray-100/80">
              <td className="py-2.5 px-4 text-gray-700">{r.name}</td>
              {levels.map(l => <td key={l} className="py-2.5 px-4 text-center font-mono text-gray-500">{r.liquidity_adaptive?.[l] || "-"}</td>)}
            </tr>
          ))}
          <tr className="border-t border-gray-100/80"><td className="py-2.5 px-4 text-gray-700">止损边界</td>
            {levels.map(l => <td key={l} className="py-2.5 px-4 text-center font-mono text-rose-500">{bounds[l]?.stop_loss}</td>)}</tr>
          <tr className="border-t border-gray-100/80"><td className="py-2.5 px-4 text-gray-700">止盈边界</td>
            {levels.map(l => <td key={l} className="py-2.5 px-4 text-center font-mono text-emerald-500">{bounds[l]?.take_profit}</td>)}</tr>
        </tbody>
      </table>
    </div>
  );
}

function LevelCard({ level }: { level: CoordinatorLevel }) {
  const uc = level.urgency >= 9 ? "bg-rose-500" : level.urgency >= 7 ? "bg-amber-500" : "bg-blue-500";
  return (
    <div className={`flex items-center gap-4 ${card} p-4 ${cardHover}`}>
      <div className="w-9 h-9 rounded-xl bg-gray-100 flex items-center justify-center text-gray-600 font-bold text-sm">{level.priority}</div>
      <div className="flex-1"><p className="text-gray-800 font-medium text-sm">{level.description}</p><p className="text-gray-300 text-[11px] font-mono">{level.name}</p></div>
      <div className={`w-1.5 h-7 rounded-full ${uc} opacity-70`} />
    </div>
  );
}

function DimCard({ dim }: { dim: DynamicDimension }) {
  const w = parseInt(dim.weight);
  return (
    <div className={`${card} p-4 text-center ${cardHover}`}>
      <div className="text-xl font-bold bg-gradient-to-b from-blue-500 to-blue-700 bg-clip-text text-transparent mb-1">{dim.weight}</div>
      <h4 className="text-gray-800 font-semibold text-xs mb-1">{dim.name}</h4>
      <p className="text-gray-400 text-[10px] leading-relaxed">{dim.description}</p>
      <div className="mt-2.5 w-full bg-gray-100 rounded-full h-1"><div className="bg-gradient-to-r from-blue-400 to-cyan-400 h-1 rounded-full" style={{ width: `${w * 3.3}%` }} /></div>
    </div>
  );
}

// ==================== Tab3: 趋势反转策略 ====================
export function StrategyTab({ rules }: { rules: StrategyRules }) {
  const pn: Record<string, string> = { lookback_days: "回看天数", min_drop_pct: "最小跌幅", min_rise_pct: "最小涨幅", min_reversal_pct: "最小反转", stop_loss_pct: "止损阈值", stop_loss_days: "止损天数" };
  return (
    <div className="space-y-8">
      <div className={`${card} p-5`}>
        <div className="flex items-center gap-3 mb-3">
          <h3 className="text-gray-900 font-semibold">{rules.strategy_name}</h3>
          {rules.preset_name && <span className="px-2.5 py-0.5 bg-blue-50 text-blue-600 rounded-full text-[11px] font-semibold border border-blue-200">{rules.preset_name}</span>}
        </div>
        {Object.keys(rules.parameters).length > 0 && (
          <div className="flex flex-wrap gap-2">{Object.entries(rules.parameters).map(([k, v]) => (
            <span key={k} className="px-2.5 py-1 rounded-full bg-gray-50 text-[11px] text-gray-500 border border-gray-200/60">
              <span className="text-gray-400">{pn[k] || k}: </span><span className="font-mono text-gray-600">{v}</span>
            </span>
          ))}</div>
        )}
      </div>
      <div><SectionHeader title="买入条件" subtitle="6条需满足4条，核心条件2+3必须满足" icon="🟢" />
        <div className="space-y-2">{rules.buy_conditions.map((c, i) => <CondCard key={i} idx={i+1} cond={c} type="buy" />)}</div></div>
      <div><SectionHeader title="卖出条件" subtitle="4条需满足3条，核心条件2+3必须满足" icon="🔴" />
        <div className="space-y-2">{rules.sell_conditions.map((c, i) => <CondCard key={i} idx={i+1} cond={c} type="sell" />)}</div></div>
      <div><SectionHeader title="组合止损/退出" subtitle="按优先级从高到低执行" icon="⚠️" />
        <div className="space-y-2">{rules.stop_loss_conditions.map((c, i) => <CondCard key={i} idx={i+1} cond={c} type="sl" />)}</div></div>
    </div>
  );
}

function CondCard({ idx, cond, type }: { idx: number; cond: string; type: "buy" | "sell" | "sl" }) {
  const core = cond.includes("【核心】");
  const text = cond.replace("【核心】", "");
  const colors = {
    buy: { border: "border-emerald-200/60", bg: "bg-emerald-50", num: "bg-emerald-100 text-emerald-600" },
    sell: { border: "border-rose-200/60", bg: "bg-rose-50", num: "bg-rose-100 text-rose-600" },
    sl: { border: "border-amber-200/60", bg: "bg-amber-50", num: "bg-amber-100 text-amber-600" },
  };
  const c = colors[type];
  return (
    <div className={`flex items-center gap-3 rounded-2xl border ${c.border} ${core ? c.bg : "bg-white/80"} shadow-sm p-3.5 ${cardHover}`}>
      <div className={`w-7 h-7 rounded-lg ${c.num} flex items-center justify-center text-[11px] font-bold shrink-0`}>{idx}</div>
      <span className="text-gray-700 text-[13px] flex-1">{text}</span>
      {core && <span className="px-2 py-0.5 bg-yellow-50 text-yellow-600 rounded-full text-[10px] font-bold border border-yellow-200 shrink-0">核心</span>}
    </div>
  );
}
