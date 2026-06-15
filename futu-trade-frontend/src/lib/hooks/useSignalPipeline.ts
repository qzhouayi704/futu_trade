"use client";

import { useCallback, useEffect, useState } from "react";
import apiClient from "@/lib/api/client";
import { sniperApi } from "@/lib/api/sniper";
import { useSocket } from "@/lib/socket";

export interface PipelineRecord {
  id?: number;
  trade_date?: string;
  timestamp: string;
  stock_code: string;
  stock_name: string;
  source: string;
  direction: string;
  strength: number;
  final_action: string;
  final_reason: string;
  resonance?: Record<string, unknown>;
  guard?: Record<string, unknown>;
  raw_detail?: Record<string, unknown>;
  multi_dimensional_summary?: {
    v1_strength: number;
    v1_label: string;
    v2_score: number;
    momentum_verdict: string;
  };
}

interface UseSignalPipelineOptions {
  limit?: number;
  includeRejected?: boolean;
  pollMs?: number;
  enabled?: boolean;
}

type PipelineResponse = {
  success?: boolean;
  data?: unknown;
} | null;

function recordKey(record: PipelineRecord, fallbackIndex: number): string {
  if (record.id !== undefined && record.id !== null) return `id:${record.id}`;
  const key = [
    record.timestamp,
    record.stock_code,
    record.source,
    record.direction,
    record.final_action,
    record.final_reason,
  ].join(":");
  return key === ":::::" ? `fallback:${fallbackIndex}` : key;
}

function mergeRecords(
  current: PipelineRecord[],
  incoming: PipelineRecord[],
  limit: number
): PipelineRecord[] {
  const byKey = new Map<string, PipelineRecord>();
  [...incoming, ...current].forEach((record, index) => {
    byKey.set(recordKey(record, index), record);
  });
  return Array.from(byKey.values())
    .sort((a, b) => {
      const aId = a.id ?? 0;
      const bId = b.id ?? 0;
      if (aId !== bId) return bId - aId;
      return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
    })
    .slice(0, limit);
}

export function useSignalPipeline({
  limit = 50,
  includeRejected = false,
  pollMs = 30000,
  enabled = true,
}: UseSignalPipelineOptions = {}) {
  const { socket } = useSocket();
  const [records, setRecords] = useState<PipelineRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    if (!enabled) return;

    try {
      const responses: PipelineResponse[] = await Promise.all([
        sniperApi.getSignalPipeline(limit) as Promise<PipelineResponse>,
        includeRejected
          ? (apiClient.get(`/signals/rejected?limit=${limit}`) as unknown as Promise<PipelineResponse>)
          : Promise.resolve(null),
      ]);

      const next: PipelineRecord[] = [];
      for (const response of responses) {
        if (response?.success && Array.isArray(response.data)) {
          next.push(...(response.data as PipelineRecord[]));
        }
      }

      setRecords(mergeRecords([], next, limit));
      setError(null);
    } catch (err) {
      setError(err);
      console.error("加载决策流水线失败:", err);
    } finally {
      setLoading(false);
    }
  }, [enabled, includeRejected, limit]);

  useEffect(() => {
    load();
    if (!enabled || pollMs <= 0) return;
    const timer = setInterval(load, pollMs);
    return () => clearInterval(timer);
  }, [enabled, load, pollMs]);

  useEffect(() => {
    if (!enabled || !socket) return;
    const handlePipeline = (record: PipelineRecord) => {
      setRecords((current) => mergeRecords(current, [record], limit));
    };
    socket.on("signal_pipeline", handlePipeline);
    return () => {
      socket.off("signal_pipeline", handlePipeline);
    };
  }, [enabled, limit, socket]);

  return {
    records,
    loading,
    error,
    reload: load,
  };
}
