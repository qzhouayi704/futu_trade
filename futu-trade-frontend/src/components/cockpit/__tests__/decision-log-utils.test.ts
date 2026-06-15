import { describe, expect, it } from "vitest";
import { classifyPipelineRecord } from "../decision-log-utils";

describe("classifyPipelineRecord", () => {
  it("groups executed and broadcast records into the executed tab", () => {
    expect(classifyPipelineRecord("executed", "capital_direct: 执行BUY")).toBe("executed");
    expect(classifyPipelineRecord("broadcast", "广播提醒")).toBe("executed");
  });

  it("detects cooldown records from either action or reason", () => {
    expect(classifyPipelineRecord("cooldown", "")).toBe("cooldown");
    expect(classifyPipelineRecord("rejected", "冷却期内")).toBe("cooldown");
    expect(classifyPipelineRecord("rejected", "cooldown active")).toBe("cooldown");
    expect(classifyPipelineRecord("rejected", "触发限频保护")).toBe("cooldown");
  });

  it("groups waiting-like actions into the waiting tab", () => {
    expect(classifyPipelineRecord("waiting", "等待共振确认")).toBe("waiting");
    expect(classifyPipelineRecord("pending", "等待处理")).toBe("waiting");
    expect(classifyPipelineRecord("skipped", "重复信号跳过")).toBe("waiting");
  });

  it("keeps regular rejected records in the rejected tab", () => {
    expect(classifyPipelineRecord("rejected", "门卫拒绝: 仓位计算为0")).toBe("rejected");
    expect(classifyPipelineRecord("failed", "下单失败")).toBe("rejected");
  });
});
