// 决策助理页面

"use client";

import { useState, useEffect, useCallback } from "react";
import { useSocket } from "@/lib/socket";
import { advisorApi } from "@/lib/api/advisor";
import { Card } from "@/components/common/Card";
import { Button } from "@/components/common/Button";
import { AdviceList } from "./components/AdviceList";
import { HealthDashboard } from "./components/HealthDashboard";
import { SwapDetail } from "./components/SwapDetail";
import type {
  DecisionAdvice,
  PositionHealth,
  AdvisorSummary,
} from "@/types/advisor";

export default function AdvisorPage() {
  const { socket } = useSocket();
  const [advices, setAdvices] = useState<DecisionAdvice[]>([]);
  const [healthList, setHealthList] = useState<PositionHealth[]>([]);
  const [summary, setSummary] = useState<AdvisorSummary | null>(null);
  const [selectedAdvice, setSelectedAdvice] = useState<DecisionAdvice | null>(
    null
  );
  const [executingId, setExecutingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 初始加载：静默拉取缓存数据，不触发评估
  const fetchCachedData = useCallback(async () => {
    try {
      const [advicesRes, healthRes] = await Promise.all([
        advisorApi.getAdvices(),
        advisorApi.getHealth(),
      ]);
      if (advicesRes?.success && Array.isArray(advicesRes.data)) {
        setAdvices(advicesRes.data);
      }
      if (healthRes?.success && healthRes.data) {
        setHealthList(healthRes.data.positions || []);
        setSummary(healthRes.data.summary || null);
      }
    } catch {
      // 静默失败，后端未启动时不显示错误
    }
  }, []);

  // 手动评估
  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await advisorApi.triggerEvaluation();
      if (res?.success && res.data) {
        setAdvices(res.data.advices || []);
        setHealthList(res.data.health || []);
        setSummary(res.data.summary || null);
      }
    } catch (err) {
      setError("加载失败，请确认后端服务已启动");
    } finally {
      setLoading(false);
    }
  }, []);

  // 初始加载
  useEffect(() => {
    fetchCachedData();
  }, [fetchCachedData]);

  // WebSocket 实时更新
  useEffect(() => {
    if (!socket) return;
    const handleUpdate = (data: {
      advices: DecisionAdvice[];
      summary: AdvisorSummary;
      health: PositionHealth[];
    }) => {
      if (data.advices) setAdvices(data.advices);
      if (data.health) setHealthList(data.health);
      if (data.summary) setSummary(data.summary);
    };
    socket.on("advisor_update", handleUpdate);
    return () => {
      socket.off("advisor_update", handleUpdate);
    };
  }, [socket]);

  // 忽略建议
  const handleDismiss = async (id: string) => {
    try {
      await advisorApi.dismissAdvice(id);
      setAdvices((prev) => prev.filter((a) => a.id !== id));
      if (selectedAdvice?.id === id) setSelectedAdvice(null);
    } catch {
      // ignore
    }
  };

  // 执行建议
  const handleExecute = async (id: string) => {
    if (executingId) return;
    setExecutingId(id);
    try {
      const res = await advisorApi.executeAdvice(id);
      if (res?.success) {
        setAdvices((prev) => prev.filter((a) => a.id !== id));
        if (selectedAdvice?.id === id) setSelectedAdvice(null);
      }
    } catch {
      // ignore
    } finally {
      setExecutingId(null);
    }
  };

  // 统计摘要
  const criticalCount = summary?.critical_count || 0;
  const highCount = summary?.high_count || 0;
  const totalCount = summary?.total_advices || advices.length;

  return (
    <div className="p-6 space-y-4">
      {/* 顶部栏 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">决策助理</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {totalCount > 0
              ? `${totalCount} 条建议${criticalCount > 0 ? `，${criticalCount} 条紧急` : ""}${highCount > 0 ? `，${highCount} 条重要` : ""}`
              : "暂无建议"}
            {summary?.last_evaluation && (
              <span className="ml-2">
                · 上次评估{" "}
                {new Date(summary.last_evaluation).toLocaleTimeString("zh-CN")}
              </span>
            )}
          </p>
        </div>
        <Button
          variant="primary"
          size="sm"
          onClick={loadData}
          disabled={loading}
        >
          {loading ? "评估中..." : "手动评估"}
        </Button>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-red-50 text-red-600 text-sm">
          {error}
        </div>
      )}

      {/* 主体内容 */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* 左栏: 建议列表 */}
        <div className="lg:col-span-2">
          <Card title="决策建议" subtitle={`共 ${totalCount} 条`}>
            <AdviceList
              advices={advices}
              selectedAdvice={selectedAdvice}
              onSelect={setSelectedAdvice}
              onDismiss={handleDismiss}
              onExecute={handleExecute}
              executingId={executingId}
            />
          </Card>
        </div>

        {/* 右栏: 健康度 + 详情 */}
        <div className="lg:col-span-3 space-y-4">
          <Card
            title="持仓健康度"
            subtitle={`${healthList.length} 只持仓`}
          >
            <HealthDashboard healthList={healthList} />
          </Card>

          <Card title="建议详情">
            <SwapDetail advice={selectedAdvice} />
          </Card>
        </div>
      </div>
    </div>
  );
}
