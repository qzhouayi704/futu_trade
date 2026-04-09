// 交易条件监控页面

"use client";

import { useState, useEffect } from "react";
import { Card, Button } from "@/components/common";
import { systemApi, quoteApi, strategyApi } from "@/lib/api";
import { useSocket } from "@/lib/socket";
import { useToast } from "@/components/common/Toast";
import { formatPercent, formatTime } from "@/lib/utils";
import type { SystemStatus } from "@/types/stock";

interface QuotaInfo {
  used: number;
  remaining: number;
  total: number;
  usage_rate: number;
  last_update?: string;
}

interface ConditionItem {
  name: string;
  description: string;
  passed: boolean;
  value?: unknown;
  threshold?: unknown;
}

interface TradingConditionDisplay {
  stock_code: string;
  stock_name: string;
  condition_type: "buy" | "sell" | "watch";
  conditions: ConditionItem[];
  all_passed: boolean;
}

interface StrategyInfo {
  strategy_id: string;
  strategy_name: string;
  preset_name: string;
}

interface StrategyIndicators {
  strategy_id: string;
  strategy_name: string;
  strategy_description: string;
  preset_name: string;
  preset_description: string;
  parameters: Record<string, any>;
  buy_conditions: string[];
  sell_conditions: string[];
  stop_loss_conditions: string[];
}

export default function ConditionsPage() {
  const { socket, isConnected } = useSocket();
  const { showToast } = useToast();

  const [quota, setQuota] = useState<QuotaInfo | null>(null);
  const [conditions, setConditions] = useState<TradingConditionDisplay[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | "pass" | "fail">("all");
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [strategyInfo, setStrategyInfo] = useState<StrategyInfo | null>(null);
  const [strategyIndicators, setStrategyIndicators] = useState<StrategyIndicators | null>(null);

  // 加载K线额度
  const loadQuota = async () => {
    try {
      const response = await quoteApi.getKlineQuota();

      if (response.success && response.data) {
        setQuota(response.data);
      }
    } catch (err: unknown) {
      console.error("加载K线额度失败:", err);
    }
  };

  // 加载交易条件
  const loadConditions = async () => {
    setLoading(true);

    try {
      const response = await quoteApi.getTradingConditions();

      if (response.success && response.data) {
        // 后端返回的是 TradingCondition[] 格式，需要转换为 TradingConditionDisplay[]
        // 暂时直接使用，因为结构不同，需要后端统一
        setConditions(response.data as unknown as TradingConditionDisplay[]);
      } else {
        throw new Error(response.message || "加载交易条件失败");
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "加载交易条件失败";
      showToast("error", "错误", message);
    } finally {
      setLoading(false);
    }
  };

  // 加载系统状态
  const loadSystemStatus = async () => {
    try {
      const response = await systemApi.getStatus();

      if (response.success && response.data) {
        setSystemStatus(response.data);
      }
    } catch (err: unknown) {
      console.error("加载系统状态失败:", err);
    }
  };

  // 加载策略信息
  const loadStrategyInfo = async () => {
    try {
      const response = await strategyApi.getActiveStrategy();

      if (response.success && response.data) {
        setStrategyInfo(response.data);
      }
    } catch (err: unknown) {
      console.error("加载策略信息失败:", err);
    }
  };

  // 加载策略指标
  const loadStrategyIndicators = async () => {
    try {
      const response = await strategyApi.getStrategyIndicators();

      if (response.success && response.data) {
        setStrategyIndicators(response.data);
      }
    } catch (err: unknown) {
      console.error("加载策略指标失败:", err);
    }
  };

  // 初始化加载
  useEffect(() => {
    loadQuota();
    loadConditions();
    loadSystemStatus();
    loadStrategyInfo();
    loadStrategyIndicators();
  }, []);

  // 监听条件更新
  useEffect(() => {
    if (!socket) return;

    const handleConditionsUpdate = (data: { quota?: QuotaInfo; conditions?: TradingConditionDisplay[] }) => {
      if (data.quota) {
        setQuota(data.quota);
      }
      if (data.conditions) {
        setConditions(data.conditions);
      }
    };

    socket.on("conditions_update", handleConditionsUpdate);

    return () => {
      socket.off("conditions_update", handleConditionsUpdate);
    };
  }, [socket]);

  // 筛选条件
  const filteredConditions = conditions.filter((condition) => {
    if (filter === "pass") return condition.all_passed;
    if (filter === "fail") return !condition.all_passed;
    return true;
  });

  // 获取进度条颜色
  const getProgressColor = (percent: number) => {
    if (percent >= 90) return "bg-red-600";
    if (percent >= 70) return "bg-yellow-600";
    return "bg-green-600";
  };

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <i className="fas fa-list-check text-blue-600"></i>
          交易条件监控
        </h1>

        <div className="flex items-center gap-4">
          {/* 系统状态 */}
          <div className="flex items-center gap-2 text-sm">
            <span className="text-gray-600">系统状态:</span>
            {systemStatus?.is_running ? (
              <span className="text-green-600 flex items-center gap-1">
                <i className="fas fa-circle"></i>
                运行中
              </span>
            ) : (
              <span className="text-gray-600 flex items-center gap-1">
                <i className="fas fa-circle"></i>
                已停止
              </span>
            )}
          </div>

          {/* WebSocket连接状态 */}
          <div className="flex items-center gap-2 text-sm">
            <span className="text-gray-600">实时连接:</span>
            {isConnected ? (
              <span className="text-green-600 flex items-center gap-1">
                <i className="fas fa-plug"></i>
                已连接
              </span>
            ) : (
              <span className="text-red-600 flex items-center gap-1">
                <i className="fas fa-plug"></i>
                未连接
              </span>
            )}
          </div>
        </div>
      </div>

      {/* 策略信息卡片 */}
      {strategyIndicators && (
        <Card className="mb-6 bg-gradient-to-br from-green-500 to-teal-600 text-white">
          <div className="mb-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-medium flex items-center gap-2 mb-2">
                  <i className="fas fa-chess-knight"></i>
                  当前策略
                </h2>
                <div className="text-2xl font-bold">{strategyIndicators.strategy_name}</div>
                <div className="text-sm opacity-90 mt-1">
                  预设: {strategyIndicators.preset_name}
                </div>
                {strategyIndicators.preset_description && (
                  <div className="text-xs opacity-75 mt-1">
                    {strategyIndicators.preset_description}
                  </div>
                )}
              </div>
              <div className="text-right">
                <div className="text-sm opacity-90">策略ID</div>
                <div className="text-lg font-medium">{strategyIndicators.strategy_id}</div>
              </div>
            </div>
          </div>

          {/* 策略指标详情 */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4 pt-4 border-t border-white border-opacity-20">
            {/* 买入条件 */}
            <div>
              <h3 className="text-sm font-semibold mb-2 flex items-center gap-1">
                <i className="fas fa-arrow-up text-red-300"></i>
                买入条件
              </h3>
              <ul className="text-xs space-y-1 opacity-90">
                {strategyIndicators.buy_conditions.map((condition, idx) => (
                  <li key={idx} className="flex items-start gap-1">
                    <span className="text-green-200">•</span>
                    <span>{condition}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* 卖出条件 */}
            <div>
              <h3 className="text-sm font-semibold mb-2 flex items-center gap-1">
                <i className="fas fa-arrow-down text-green-300"></i>
                卖出条件
              </h3>
              <ul className="text-xs space-y-1 opacity-90">
                {strategyIndicators.sell_conditions.map((condition, idx) => (
                  <li key={idx} className="flex items-start gap-1">
                    <span className="text-green-200">•</span>
                    <span>{condition}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* 止损条件 */}
            <div>
              <h3 className="text-sm font-semibold mb-2 flex items-center gap-1">
                <i className="fas fa-shield-alt text-yellow-300"></i>
                止损条件
              </h3>
              <ul className="text-xs space-y-1 opacity-90">
                {strategyIndicators.stop_loss_conditions.map((condition, idx) => (
                  <li key={idx} className="flex items-start gap-1">
                    <span className="text-green-200">•</span>
                    <span>{condition}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Card>
      )}

      {/* K线额度面板 */}
      <Card className="mb-6 bg-gradient-to-br from-blue-500 to-purple-600 text-white">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-medium flex items-center gap-2">
            <i className="fas fa-chart-bar"></i>
            K线数据获取额度
          </h2>
          <Button
            variant="secondary"
            size="sm"
            onClick={loadQuota}
            className="text-white border-white hover:bg-white hover:text-blue-600"
          >
            <i className="fas fa-sync mr-1"></i>
            刷新额度
          </Button>
        </div>

        {quota ? (
          <>
            <div className="grid grid-cols-4 gap-4 mb-4">
              <div className="text-center">
                <div className="text-3xl font-bold">{quota.used}</div>
                <div className="text-sm opacity-90">已使用</div>
              </div>
              <div className="text-center">
                <div className="text-3xl font-bold">{quota.remaining}</div>
                <div className="text-sm opacity-90">剩余可用</div>
              </div>
              <div className="text-center">
                <div className="text-3xl font-bold">{quota.total}</div>
                <div className="text-sm opacity-90">总额度</div>
              </div>
              <div className="text-center">
                <div className="text-3xl font-bold">
                  {formatPercent(quota.usage_rate)}
                </div>
                <div className="text-sm opacity-90">使用率</div>
              </div>
            </div>

            {/* 进度条 */}
            <div className="relative h-8 bg-white bg-opacity-20 rounded-full overflow-hidden">
              <div
                className={`h-full transition-all duration-500 ${getProgressColor(
                  quota.usage_rate
                )}`}
                style={{ width: `${quota.usage_rate}%` }}
              ></div>
              <div className="absolute inset-0 flex items-center justify-center text-sm font-medium">
                {quota.used} / {quota.total} ({formatPercent(quota.usage_rate)})
              </div>
            </div>

            {quota.last_update && (
              <div className="text-sm opacity-90 mt-3">
                <i className="fas fa-info-circle mr-1"></i>
                最后更新: {formatTime(new Date(quota.last_update))}
              </div>
            )}
          </>
        ) : (
          <div className="text-center py-8">
            <i className="fas fa-spinner fa-spin text-2xl mb-2"></i>
            <div>加载额度信息中...</div>
          </div>
        )}
      </Card>

      {/* 交易条件面板 */}
      <Card>
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-medium text-gray-900">
              股票交易条件详情
            </h2>
            <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium">
              {filteredConditions.length}
            </span>
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => setFilter("all")}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                filter === "all"
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              }`}
            >
              <i className="fas fa-list mr-1"></i>
              全部
            </button>
            <button
              onClick={() => setFilter("pass")}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                filter === "pass"
                  ? "bg-green-600 text-white"
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              }`}
            >
              <i className="fas fa-check mr-1"></i>
              符合条件
            </button>
            <button
              onClick={() => setFilter("fail")}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                filter === "fail"
                  ? "bg-red-600 text-white"
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              }`}
            >
              <i className="fas fa-times mr-1"></i>
              不符合条件
            </button>
            <Button
              variant="secondary"
              size="sm"
              onClick={loadConditions}
              loading={loading}
            >
              <i className="fas fa-sync mr-1"></i>
              刷新
            </Button>
          </div>
        </div>

        {/* 条件列表 */}
        <div className="space-y-4">
          {loading ? (
            <div className="text-center py-12">
              <i className="fas fa-spinner fa-spin text-2xl text-blue-600 mb-3"></i>
              <div className="text-gray-600">正在加载交易条件数据...</div>
            </div>
          ) : filteredConditions.length === 0 ? (
            <div className="text-center py-12">
              <i className="fas fa-inbox text-4xl text-gray-400 mb-3"></i>
              <div className="text-gray-600">
                {filter === "all"
                  ? "暂无交易条件数据"
                  : filter === "pass"
                  ? "暂无符合条件的股票"
                  : "暂无不符合条件的股票"}
              </div>
            </div>
          ) : (
            filteredConditions.map((condition, index) => (
              <div
                key={index}
                className={`border rounded-lg p-4 ${
                  condition.all_passed
                    ? "border-green-200 bg-green-50"
                    : "border-gray-200 bg-white"
                }`}
              >
                {/* 股票信息 */}
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div>
                      <div className="font-medium text-gray-900">
                        {condition.stock_name}
                      </div>
                      <div className="text-sm text-gray-600">
                        {condition.stock_code}
                      </div>
                    </div>
                    <span
                      className={`px-3 py-1 rounded-full text-xs font-medium ${
                        condition.condition_type === "buy"
                          ? "bg-red-100 text-red-800"
                          : condition.condition_type === "sell"
                          ? "bg-green-100 text-green-800"
                          : "bg-blue-100 text-blue-800"
                      }`}
                    >
                      {condition.condition_type === "buy"
                        ? "买入"
                        : condition.condition_type === "sell"
                        ? "卖出"
                        : "观察"}
                    </span>
                  </div>

                  <div
                    className={`flex items-center gap-2 ${
                      condition.all_passed ? "text-green-600" : "text-gray-600"
                    }`}
                  >
                    <i
                      className={`fas ${
                        condition.all_passed ? "fa-check-circle" : "fa-times-circle"
                      }`}
                    ></i>
                    <span className="font-medium">
                      {condition.all_passed ? "符合条件" : "不符合条件"}
                    </span>
                  </div>
                </div>

                {/* 条件详情 */}
                <div className="space-y-2">
                  {(condition.conditions || []).map((cond, idx) => (
                    <div
                      key={idx}
                      className="flex items-center justify-between py-2 px-3 bg-white rounded border border-gray-100"
                    >
                      <div className="flex items-center gap-3">
                        <i
                          className={`fas ${
                            cond.passed
                              ? "fa-check-circle text-green-600"
                              : "fa-times-circle text-red-600"
                          }`}
                        ></i>
                        <div>
                          <div className="text-sm font-medium text-gray-900">
                            {cond.name}
                          </div>
                          <div className="text-xs text-gray-600">
                            {cond.description}
                          </div>
                        </div>
                      </div>

                      {cond.value !== undefined && (
                        <div className="text-sm text-gray-600">
                          当前值: {String(cond.value)}
                          {cond.threshold !== undefined &&
                            ` / 阈值: ${String(cond.threshold)}`}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      </Card>
    </div>
  );
}
