// 决策建议列表

"use client";

import type { DecisionAdvice } from "@/types/advisor";
import { AdviceCard } from "./AdviceCard";

interface AdviceListProps {
  advices: DecisionAdvice[];
  selectedAdvice: DecisionAdvice | null;
  onSelect: (advice: DecisionAdvice) => void;
  onDismiss: (id: string) => void;
  onExecute: (id: string) => void;
  executingId: string | null;
}

export function AdviceList({
  advices,
  selectedAdvice,
  onSelect,
  onDismiss,
  onExecute,
  executingId,
}: AdviceListProps) {
  if (advices.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-gray-400">
        <svg className="w-12 h-12 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <p className="text-sm">暂无决策建议</p>
        <p className="text-xs mt-1">系统运行中会自动生成建议</p>
      </div>
    );
  }

  // 按紧急度分组
  const critical = advices.filter((a) => a.urgency === 10);
  const high = advices.filter((a) => a.urgency === 8);
  const medium = advices.filter((a) => a.urgency === 5);
  const low = advices.filter((a) => a.urgency === 1);

  return (
    <div className="space-y-4 overflow-y-auto max-h-[calc(100vh-220px)]">
      {critical.length > 0 && (
        <AdviceGroup
          label="紧急"
          color="text-red-600"
          advices={critical}
          selectedAdvice={selectedAdvice}
          onSelect={onSelect}
          onDismiss={onDismiss}
          onExecute={onExecute}
          executingId={executingId}
        />
      )}
      {high.length > 0 && (
        <AdviceGroup
          label="重要"
          color="text-orange-600"
          advices={high}
          selectedAdvice={selectedAdvice}
          onSelect={onSelect}
          onDismiss={onDismiss}
          onExecute={onExecute}
          executingId={executingId}
        />
      )}
      {medium.length > 0 && (
        <AdviceGroup
          label="建议"
          color="text-yellow-600"
          advices={medium}
          selectedAdvice={selectedAdvice}
          onSelect={onSelect}
          onDismiss={onDismiss}
          onExecute={onExecute}
          executingId={executingId}
        />
      )}
      {low.length > 0 && (
        <AdviceGroup
          label="提示"
          color="text-gray-500"
          advices={low}
          selectedAdvice={selectedAdvice}
          onSelect={onSelect}
          onDismiss={onDismiss}
          onExecute={onExecute}
          executingId={executingId}
        />
      )}
    </div>
  );
}

function AdviceGroup({
  label,
  color,
  advices,
  selectedAdvice,
  onSelect,
  onDismiss,
  onExecute,
  executingId,
}: {
  label: string;
  color: string;
  advices: DecisionAdvice[];
  selectedAdvice: DecisionAdvice | null;
  onSelect: (a: DecisionAdvice) => void;
  onDismiss: (id: string) => void;
  onExecute: (id: string) => void;
  executingId: string | null;
}) {
  return (
    <div>
      <h3 className={`text-xs font-semibold mb-2 ${color}`}>
        {label} ({advices.length})
      </h3>
      <div className="space-y-2">
        {advices.map((advice) => (
          <AdviceCard
            key={advice.id}
            advice={advice}
            isSelected={selectedAdvice?.id === advice.id}
            onSelect={onSelect}
            onDismiss={onDismiss}
            onExecute={onExecute}
            executing={executingId === advice.id}
          />
        ))}
      </div>
    </div>
  );
}
