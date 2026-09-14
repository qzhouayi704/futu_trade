import type { V2AlertPerformanceItem, V2SignalPermission, V2SignalStage, V2SignalStatus } from "@/lib/api/v2";

export const stageText: Record<V2SignalStage, string> = {
  SETUP: "候选准备",
  WATCHING: "资金观察",
  CONFIRMED: "买点确认",
};

export const statusText: Record<V2SignalStatus, string> = {
  IDLE: "当前未入选",
  SETUP: "候选准备中",
  WATCHING: "资金观察中",
  CONFIRMED: "当前已确认",
  INVALIDATED: "当前已失效",
};

export const permissionText: Record<V2SignalPermission, string> = {
  NONE: "当前无操作权限",
  TRACKING: "仅站内跟踪",
  RESEARCH: "研究确认，暂不推送买入",
  FORMAL_ELIGIBLE: "具备正式提醒资格",
  DELIVERED: "微信接口已接受正式提醒",
};

const strategySourceText: Record<string, string> = {
  capital_absorption: "低位资金吸收",
  capital_memory_reversal: "低位资金记忆",
  strong_trend_reentry: "趋势回踩再启动",
  post_invalidation_flow_recovery: "失效后低位资金反转",
  momentum_continuation: "严格动量",
};

export function strategySourcesText(sources: string[]): string {
  return sources.length
    ? sources.map((source) => strategySourceText[source] || source).join("、")
    : "暂无独立策略提名";
}

export function strategySourceLabel(source: string): string {
  return strategySourceText[source] || source;
}

export function signalHeadline(item: V2AlertPerformanceItem): string {
  if (item.action === "SELL") return "卖出提醒";
  if (item.action === "ROTATE") return "换入提醒";
  if (item.action === "BUY") return "买入提醒";
  return statusText[item.current_status];
}

export function lifecycleCounts(data: {
  count: number;
  lifecycle_summary: {
    current_status: Partial<Record<V2SignalStatus, number>>;
    max_stage: Partial<Record<V2SignalStage, number>>;
    alert_permission: Partial<Record<V2SignalPermission, number>>;
  };
}) {
  const statuses = data.lifecycle_summary.current_status;
  const permissions = data.lifecycle_summary.alert_permission;
  const inactive = (statuses.IDLE || 0) + (statuses.INVALIDATED || 0);
  return {
    active: Math.max(0, data.count - inactive),
    invalidated: statuses.INVALIDATED || 0,
    confirmed: data.lifecycle_summary.max_stage.CONFIRMED || 0,
    formal: (permissions.FORMAL_ELIGIBLE || 0) + (permissions.DELIVERED || 0),
  };
}
