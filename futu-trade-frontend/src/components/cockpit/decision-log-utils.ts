export type DecisionTabKey = "all" | "executed" | "rejected" | "waiting" | "cooldown";

const EXECUTED_ACTIONS = new Set(["executed", "broadcast", "submitted", "filled"]);
const WAITING_ACTIONS = new Set(["waiting", "pending", "skipped"]);
const REJECTED_ACTIONS = new Set(["rejected", "blocked", "failed", "cancelled", "canceled"]);

function normalizeText(value?: string | null) {
  return (value || "").trim().toLowerCase();
}

function hasAny(text: string, patterns: string[]) {
  return patterns.some((pattern) => text.includes(pattern));
}

/** 判断流水线记录应该归属到哪个筛选 Tab。 */
export function classifyPipelineRecord(
  action?: string | null,
  reason?: string | null
): DecisionTabKey {
  const normalizedAction = normalizeText(action);
  const normalizedReason = normalizeText(reason);

  const isCooldown =
    normalizedAction === "cooldown" ||
    hasAny(normalizedReason, ["冷却", "cooldown", "限频", "频率"]);
  if (isCooldown) return "cooldown";

  if (EXECUTED_ACTIONS.has(normalizedAction)) return "executed";
  if (WAITING_ACTIONS.has(normalizedAction)) return "waiting";
  if (REJECTED_ACTIONS.has(normalizedAction)) return "rejected";

  if (hasAny(normalizedReason, ["等待", "pending", "wait"])) return "waiting";
  if (hasAny(normalizedReason, ["执行", "executed", "broadcast"])) return "executed";

  return "rejected";
}
