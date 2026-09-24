const labels: Record<string, string> = {
  RESEARCH_ATR: "波动率退出实验", PRODUCTION_RULES: "生产退出规则 · 日内模拟",
  HARD_STOP_3_PCT: "达到硬止损线", TAKE_PROFIT_5_PCT: "达到止盈线",
  REPEATED_OUTFLOW_AND_STRUCTURE_BREAK: "持续流出且价格结构破坏",
  SUSTAINED_DOWNTREND_AND_VWAP_BREAK: "持续走弱并跌破均价",
  TRAIL_AFTER_SUPPORT_LOST: "资金支持消失，回撤止盈",
  PROFIT_FLOOR_AFTER_SUPPORT_LOST: "资金支持消失，保护剩余利润",
  PRODUCTION_EXIT_EVIDENCE_INCOMPLETE: "资金依据不全，仅检查价格止损止盈",
  PRODUCTION_POSITION_EVALUATED: "模拟持仓已按生产规则评估",
  POSITION_EFFICIENT: "持仓走势有效，继续观察", PROFIT_PROTECTION_ARMED: "已启动利润保护观察",
  SUSTAINED_PRICE_AND_FLOW_STALL: "价格与资金持续停滞",
  REPEATED_OUTFLOW_ABSORBED_OR_SUPPORTED: "流出被承接或仍有资金支持",
  DOWNTREND_UNDER_SELL_PRESSURE: "卖压下走势偏弱", POSITION_PRICE_INVALID: "持仓价格无效",
  ACTIVE_ORDER_CONFLICT: "存在待成交订单",
  DISABLED: "未启用", NOT_INITIALIZED: "尚未初始化", RUNNING: "模拟运行中",
  STOPPED: "已停止", ERROR: "运行异常", WORKING: "等待成交", PARTIALLY_FILLED: "部分成交",
  HOLDING: "持仓中", EXIT_PENDING: "等待卖出成交", CLOSED: "已结束", CANCELLED: "已撤销",
  ENTRY_EXPIRED: "入场时限已过", ENTRY_CANCELLED: "剩余买入已撤销",
  ENTRY_STRUCTURE_BROKEN: "入场价格结构失效", STOP_BROKEN: "触及失效价",
  TAKE_PROFIT: "触及止盈价", HOLDING_DEADLINE: "达到持有期限",
  PAPER_PLAN_APPROVED: "模拟计划通过", RESEARCH_SETUP_CREATED: "研究计划已生成",
  NOT_FORMAL_CONFIRMATION: "不是正式确认信号", OUTSIDE_EXPERIMENT_UNIVERSE: "不在实验名单",
  EXPERIMENT_STRATEGY_MISMATCH: "策略或版本不一致",
  TRADING_INTERVAL_UNAVAILABLE_OR_CLOSED: "不在审核交易时段",
  SIGNAL_NOT_YET_KNOWN_OR_STALE: "信号时间异常或已过期",
  SIGNAL_EVIDENCE_NOT_YET_KNOWN_OR_STALE: "信号依据时间异常或已过期",
  SIGNAL_EVIDENCE_QUALITY_INVALID: "信号依据质量不足",
  SIGNAL_EVIDENCE_MISSING_OR_INVALID: "信号依据缺失或无效",
  LOT_SIZE_EVIDENCE_INVALID: "缺少有效每手股数依据", RESEARCH_STOP_TOO_WIDE: "失效距离超出实验限制",
  ENTRY_WINDOW_TOO_SHORT: "剩余入场时间不足", ENTRY_WINDOW_CLOSED: "入场窗口已关闭",
  EXPERIMENT_STOCK_DAY_ALREADY_PLANNED: "该股票当日已有实验计划",
  INVALIDATION_EVIDENCE_INVALID: "失效事件依据不符",
  SIGNAL_INVALIDATED_ENTRY_CANCELLED: "信号失效，剩余买入已撤销",
  NO_ENTRY_TO_CANCEL: "没有待撤销买入", ALREADY_PLANNED: "计划已存在",
  STOCK_ALREADY_ALLOCATED: "该股票已有资金分配", SOURCE_EVENT_ALREADY_PLANNED: "信号已生成计划",
  MAX_POSITIONS_REACHED: "活动计划数量已达上限", ACCOUNT_MARK_STALE: "持仓估值行情已过期",
  BELOW_ONE_LOT_BUDGET: "风险或资金预算不足一手",
  PAPER_INPUT_QUEUE_OVERFLOW: "模拟输入队列已满", PAPER_STOP_WITH_PENDING_INPUT: "停止时存在未处理输入",
  PAPER_SESSION_FAILED: "模拟处理失败", PAPER_FINAL_CHECKPOINT_FAILED: "停止状态保存失败",
  PAPER_STOP_TIMEOUT: "模拟停止超时", PAPER_CAPTURE_DISCONTINUITY: "盘口数据中断",
  PAPER_CAPTURE_UNAVAILABLE: "盘口采集不可用", PAPER_DECISION_STREAM_INCOMPLETE: "决策数据存在缺口",
};

export function paperLabel(code: string | null | undefined): string {
  return code ? labels[code] || "未识别状态，需核查" : "--";
}

export function paperMoney(value: string | null | undefined, digits = 2): string {
  if (value === null || value === undefined || value.trim() === "" || !Number.isFinite(Number(value))) return "--";
  return Number(value).toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function paperTime(value: string | null | undefined): string {
  if (!value || !Number.isFinite(Date.parse(value))) return "--";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Hong_Kong", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  }).format(new Date(value));
}
