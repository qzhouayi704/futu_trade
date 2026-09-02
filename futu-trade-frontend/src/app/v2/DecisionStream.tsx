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
  POSITION_OPENED: "持仓建立",
  POSITION_EFFICIENCY_CHANGED: "持仓状态更新",
  EXIT_RISK_CONFIRMED: "卖出风险确认",
  ROTATION_PROPOSED: "换票建议",
  POSITION_CLOSED: "持仓结束",
  TRADE_INTENT_CREATED: "交易意图生成",
  RISK_APPROVED: "风险检查通过",
  RISK_REJECTED: "风险检查拦截",
  ORDER_SUBMITTED: "订单已提交",
  ORDER_UPDATED: "订单状态更新",
  EXECUTION_COMPLETED: "交易执行完成",
  NOTIFICATION_REQUESTED: "提醒待发送",
  NOTIFICATION_DELIVERED: "提醒已送达",
  NOTIFICATION_FAILED: "提醒发送失败",
};

const stateLabel: Record<string, string> = {
  IDLE: "未进入候选",
  SETUP: "候选准备中",
  WATCHING: "观察确认中",
  CONFIRMED: "信号已确认",
  INVALIDATED: "信号已失效",
  FLAT: "空仓",
  HOLDING: "持仓中",
  PROFIT_READY: "盈利保护中",
  STALLED: "走势停滞",
  EXIT_RISK: "存在卖出风险",
  ROTATION_READY: "可考虑换票",
  EXITING: "卖出处理中",
  CLOSED: "已平仓",
};

const reasonLabel: Record<string, string> = {
  SNAPSHOT_INVALID: "行情特征数据无效",
  DATA_QUALITY_INVALID: "关键行情数据无效",
  MARKET_CONTEXT_INCOMPLETE: "市场环境数据不完整",
  NOT_ACTIVE: "成交活跃度不足",
  LIQUIDITY_TOO_LOW: "流动性不足",
  TURNOVER_RANK_NOT_HOT: "成交额热度不足",
  SECTOR_BREADTH_WEAK: "所属板块宽度偏弱",
  RELATIVE_STRENGTH_LOW: "相对强度不足",
  DAILY_POSITION_INVALID: "缺少日线参考",
  HOT_ACTIVE_DAILY_SETUP: "热门活跃，等待资金确认",
  FIRST_STRONG_INFLOW_WATCH: "出现首次强流入，继续观察",
  LOW_POSITION_ACCUMULATION_WATCH: "低位多次资金吸收，等待环境确认",
  LOW_POSITION_15M_ACCUMULATION_CONFIRMED: "低位15分钟资金吸收确认",
  CAPITAL_MEMORY_REVERSAL_WATCH: "全天资金吸收转强，等待多次确认",
  CAPITAL_MEMORY_MULTI_INFLOW_SHADOW_CONFIRMED: "资金记忆多次流入，影子确认",
  CAPITAL_MEMORY_TURNED_DISTRIBUTING: "近期资金转为明显流出",
  LEGACY_RALLY_STRONG_WATCH: "量价齐升，等待多次流入",
  LEGACY_RALLY_SETUP_WATCH: "量价齐升，升级为重点观察",
  STRICT_MOMENTUM_WATCH: "强势动量，等待多次资金确认",
  STRICT_MOMENTUM_SHADOW_CONFIRMED: "强势动量影子确认",
  FAST_15M_MULTI_INFLOW_CONFIRMED: "15分钟多次流入确认",
  WEAK_MARKET_60M_STRONG_STOCK_CONFIRMED: "弱市中60分钟强势资金确认",
  EXTREME_MARKET_60M_MULTI_INFLOW_CONFIRMED: "极弱市场中60分钟多次流入确认",
  PRICE_ACCEPTANCE_BROKEN: "价格承接已经破坏",
  LARGE_OUTFLOW_OFFSETS_INFLOW: "大单流出已经抵消前期流入",
  FLOW_CONFIRMATION_EXPIRED: "资金确认等待时间已过",
  HOT_UNIVERSE_EXITED: "已不符合热门活跃股票范围",
  SOFT_GATE_STRONG_SIGNAL_REENTRY: "强信号恢复，重新进入观察",
  COOLDOWN_COMPLETE_REENTER_SETUP: "冷却结束，重新进入候选准备",
  HARD_STOP_3_PCT: "触及3%硬止损",
  TAKE_PROFIT_5_PCT: "达到5%止盈目标",
  REPEATED_OUTFLOW_AND_STRUCTURE_BREAK: "多次大单流出且价格结构破位",
  TRAIL_AFTER_SUPPORT_LOST: "失去资金支撑，触发回撤保护",
  PROFIT_FLOOR_AFTER_SUPPORT_LOST: "失去资金支撑，跌破利润保护线",
  SUSTAINED_PRICE_AND_FLOW_STALL: "价格与资金持续停滞",
  REPEATED_OUTFLOW_ABSORBED_OR_SUPPORTED: "大单流出被吸收或仍有资金支撑",
  POSITION_EFFICIENT: "持仓效率正常",
  PROFIT_PROTECTION_ARMED: "盈利保护已经启动",
  CONFIRMED_CANDIDATE_NET_ADVANTAGE: "新候选相对当前持仓优势明确",
  ACTIVE_ORDER_CONFLICT: "已有未完成订单，暂不重复操作",
  POSITION_PRICE_INVALID: "持仓价格数据无效",
  BROKER_POSITION_CLOSED: "券商持仓已经关闭",
  COST_BASIS_CHANGED: "持仓成本发生变化，重新计算",
  PRICE_HISTORY_INSUFFICIENT: "分钟价格历史不足",
  FEATURE_SNAPSHOT_MISSING: "缺少最新行情特征",
  SUSTAINED_PRICE_STALL: "股价持续横盘停滞",
  RISK_CHECKS_PASSED: "风险检查通过",
  ACCOUNT_CAPACITY_UNAVAILABLE: "账户资金数据不可用",
  AVAILABLE_FUNDS_INSUFFICIENT: "可用资金不足",
  MAX_POSITION_COUNT_REACHED: "持仓数量已达上限",
  MAX_SINGLE_POSITION_EXCEEDED: "单只股票仓位超过上限",
  MARKET_NOT_TRADING: "当前不在交易时段",
  FREQUENCY_GUARD_UNAVAILABLE: "交易频率保护不可用",
};

function eventText(value: string): string {
  return eventLabel[value] || "其他决策事件";
}

function stateText(value: string | null): string {
  if (!value) return "无";
  return stateLabel[value] || "其他状态";
}

function reasonText(value: string): string {
  return reasonLabel[value] || "其他系统判断原因";
}

export function DecisionStream({ items, compact = false }: { items: V2Decision[]; compact?: boolean }) {
  return <div className="divide-y divide-border/70">
    {items.slice(0, compact ? 8 : undefined).map((item) => <div key={item.event_id} className="grid min-h-14 grid-cols-[64px_1fr] gap-3 px-3 py-2 md:grid-cols-[64px_130px_1fr_180px] md:items-center">
      <div className="font-mono text-xs text-muted-foreground">{clock(item.exchange_time)}</div>
      <div><div className="font-semibold text-xs">{item.stock_code}</div><div className={`text-[11px] ${actionTypes.has(item.event_type) ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"}`}>{eventText(item.event_type)}</div></div>
      <div className="flex items-center gap-2 text-xs"><GitCommitHorizontal className="h-4 w-4 text-sky-500" /><span>{stateText(item.old_state)}</span><ArrowRight className="h-3 w-3 text-muted-foreground" /><span className="font-medium">{stateText(item.new_state)}</span></div>
      <div className="col-start-2 truncate text-xs text-muted-foreground md:col-auto" title={reasonText(item.reason_code)}>{reasonText(item.reason_code)}</div>
    </div>)}
    {!items.length && <div className="flex h-36 items-center justify-center text-sm text-muted-foreground">暂无决策事件</div>}
  </div>;
}
