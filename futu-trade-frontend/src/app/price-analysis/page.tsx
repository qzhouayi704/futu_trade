// 价格位置分析页面

"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Card, Button, Loading } from "@/components/common";
import { analysisApi } from "@/lib/api/analysis";
import { useToast } from "@/components/common/Toast";
import type { AnalysisResult, AnalysisTask, AutoTradeTask, BestParams, LastDayInfo } from "@/lib/api/analysis";

const ZONE_NAMES = [
  "低位(0-20%)",
  "偏低(20-40%)",
  "中位(40-60%)",
  "偏高(60-80%)",
  "高位(80-100%)",
];

const STATUS_LABELS: Record<string, { text: string; color: string }> = {
  waiting_buy: { text: "等待买入", color: "bg-yellow-100 text-yellow-800" },
  bought: { text: "已买入", color: "bg-blue-100 text-blue-800" },
  completed: { text: "止盈完成", color: "bg-green-100 text-green-800" },
  stop_loss: { text: "已止损", color: "bg-red-100 text-red-800" },
  stopped: { text: "已停止", color: "bg-gray-100 text-gray-800" },
};

export default function PriceAnalysisPage() {
  const { showToast } = useToast();

  // 分析状态
  const [stockCode, setStockCode] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState("");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState("");
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 自动交易状态
  const [selectedZone, setSelectedZone] = useState("");
  const [tradeQuantity, setTradeQuantity] = useState(100);
  const [prevClose, setPrevClose] = useState<number>(0);
  const [autoTradeTasks, setAutoTradeTasks] = useState<AutoTradeTask[]>([]);
  const autoTradePollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 清理轮询
  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
      if (autoTradePollingRef.current) clearInterval(autoTradePollingRef.current);
    };
  }, []);

  // 轮询自动交易状态
  const pollAutoTradeStatus = useCallback(async () => {
    try {
      const resp = await analysisApi.getAutoTradeStatus();
      if (resp.success && resp.data) {
        setAutoTradeTasks(resp.data);
      }
    } catch {
      // 静默失败
    }
  }, []);

  useEffect(() => {
    autoTradePollingRef.current = setInterval(pollAutoTradeStatus, 3000);
    pollAutoTradeStatus();
    return () => {
      if (autoTradePollingRef.current) clearInterval(autoTradePollingRef.current);
    };
  }, [pollAutoTradeStatus]);

  // 开始分析
  const handleStartAnalysis = async () => {
    if (!stockCode.trim()) {
      showToast("warning", "提示", "请输入股票代码");
      return;
    }

    setAnalyzing(true);
    setProgress("启动分析...");
    setResult(null);
    setError("");

    try {
      const resp = await analysisApi.startAnalysis(stockCode.trim());
      if (!resp.success || !resp.data) {
        throw new Error(resp.message || "启动分析失败");
      }

      const taskId = resp.data.task_id;

      // 轮询进度
      pollingRef.current = setInterval(async () => {
        try {
          const statusResp = await analysisApi.getAnalysisStatus(taskId);
          if (!statusResp.success || !statusResp.data) return;

          const task = statusResp.data;
          setProgress(task.progress || "");

          if (task.status === "completed" && task.result) {
            if (pollingRef.current) clearInterval(pollingRef.current);
            setResult(task.result);
            setAnalyzing(false);
            showToast("success", "完成", "分析完成");

            // 自动填充前一交易日的区间和收盘价
            const lastDay = task.result.last_day_info;
            if (lastDay) {
              if (lastDay.close_price > 0) {
                setPrevClose(lastDay.close_price);
              }
              if (lastDay.zone && task.result.best_params[lastDay.zone]?.buy_dip_pct > 0) {
                setSelectedZone(lastDay.zone);
              }
            }
          } else if (task.status === "error") {
            if (pollingRef.current) clearInterval(pollingRef.current);
            setError(task.error || "分析失败");
            setAnalyzing(false);
          }
        } catch {
          // 轮询失败静默处理
        }
      }, 1500);
    } catch (err: any) {
      setError(err.message || "启动分析失败");
      setAnalyzing(false);
    }
  };

  // 启动自动交易
  const handleStartAutoTrade = async () => {
    if (!selectedZone || !result) {
      showToast("warning", "提示", "请先完成分析并选择区间");
      return;
    }

    const params = result.best_params[selectedZone];
    if (!params || params.buy_dip_pct <= 0) {
      showToast("warning", "提示", "该区间无可行参数");
      return;
    }

    if (tradeQuantity <= 0 || tradeQuantity % 100 !== 0) {
      showToast("warning", "提示", "交易数量必须是100的正整数倍");
      return;
    }

    if (prevClose <= 0) {
      showToast("warning", "提示", "请输入前收盘价");
      return;
    }

    try {
      // 构建开盘类型参数
      const openTypeParams: Record<string, any> = {};
      if (result.open_type_params?.gap_up?.enabled && result.open_type_params.gap_up.buy_dip_pct != null) {
        openTypeParams.gap_up = {
          buy_dip_pct: result.open_type_params.gap_up.buy_dip_pct,
          sell_rise_pct: result.open_type_params.gap_up.sell_rise_pct,
          stop_loss_pct: result.open_type_params.gap_up.stop_loss_pct,
        };
      }

      const resp = await analysisApi.startAutoTrade({
        stock_code: result.stock_code,
        quantity: tradeQuantity,
        zone: selectedZone,
        buy_dip_pct: params.buy_dip_pct,
        sell_rise_pct: params.sell_rise_pct,
        stop_loss_pct: params.stop_loss_pct,
        prev_close: prevClose,
        open_type_params: Object.keys(openTypeParams).length > 0 ? openTypeParams : undefined,
        gap_threshold: result.gap_threshold,
      });

      if (resp.success) {
        showToast("success", "成功", `${result.stock_code} 自动交易已启动`);
        pollAutoTradeStatus();
      } else {
        throw new Error(resp.message);
      }
    } catch (err: any) {
      showToast("error", "错误", err.message || "启动失败");
    }
  };

  // 停止自动交易
  const handleStopAutoTrade = async (code: string) => {
    try {
      const resp = await analysisApi.stopAutoTrade(code);
      if (resp.success) {
        showToast("success", "成功", `${code} 已停止`);
        pollAutoTradeStatus();
      }
    } catch (err: any) {
      showToast("error", "错误", err.message || "停止失败");
    }
  };

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <svg className="w-7 h-7 text-purple-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
          价格位置分析
        </h1>
      </div>

      {/* 输入区域 */}
      <Card>
        <div className="flex items-end gap-4">
          <div className="flex-1">
            <label className="block text-sm font-medium text-gray-700 mb-1">股票代码</label>
            <input
              type="text"
              value={stockCode}
              onChange={(e) => setStockCode(e.target.value.toUpperCase())}
              placeholder="如 HK.00700"
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-purple-500 focus:border-transparent"
              onKeyDown={(e) => e.key === "Enter" && handleStartAnalysis()}
            />
          </div>
          <Button
            onClick={handleStartAnalysis}
            disabled={analyzing}
            className="bg-purple-600 hover:bg-purple-700 text-white px-6"
          >
            {analyzing ? "分析中..." : "开始分析"}
          </Button>
        </div>

        {/* 进度 */}
        {analyzing && (
          <div className="mt-4">
            <div className="flex items-center gap-2 text-sm text-purple-700">
              <Loading />
              <span>{progress}</span>
            </div>
            <div className="mt-2 w-full bg-gray-200 rounded-full h-2">
              <div className="bg-purple-600 h-2 rounded-full animate-pulse" style={{ width: "60%" }} />
            </div>
          </div>
        )}

        {error && (
          <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {error}
          </div>
        )}
      </Card>

      {/* 分析结果 */}
      {result && (
        <div className="mt-6 space-y-6">
          {/* 区间统计表 */}
          <Card>
            <h2 className="text-lg font-medium text-gray-900 mb-4">
              各区间涨跌幅统计 — {result.stock_code}（{result.metrics_count} 个交易日）
            </h2>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium text-gray-500">区间</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">天数</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">频率</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">涨幅均值</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">涨幅中位数</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">跌幅均值</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">跌幅中位数</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {ZONE_NAMES.map((zn) => {
                    const s = result.zone_stats[zn];
                    if (!s || s.count === 0) {
                      return (
                        <tr key={zn}>
                          <td className="px-3 py-2 font-medium">{zn}</td>
                          <td className="px-3 py-2 text-right text-gray-400">0</td>
                          <td className="px-3 py-2 text-right text-gray-400">-</td>
                          <td className="px-3 py-2 text-right text-gray-400">-</td>
                          <td className="px-3 py-2 text-right text-gray-400">-</td>
                          <td className="px-3 py-2 text-right text-gray-400">-</td>
                          <td className="px-3 py-2 text-right text-gray-400">-</td>
                        </tr>
                      );
                    }
                    return (
                      <tr key={zn} className="hover:bg-gray-50">
                        <td className="px-3 py-2 font-medium">{zn}</td>
                        <td className="px-3 py-2 text-right">{s.count}</td>
                        <td className="px-3 py-2 text-right">{s.frequency_pct.toFixed(1)}%</td>
                        <td className="px-3 py-2 text-right text-red-600">{s.rise_stats.mean.toFixed(2)}%</td>
                        <td className="px-3 py-2 text-right text-red-600">{s.rise_stats.median.toFixed(2)}%</td>
                        <td className="px-3 py-2 text-right text-green-600">{s.drop_stats.mean.toFixed(2)}%</td>
                        <td className="px-3 py-2 text-right text-green-600">{s.drop_stats.median.toFixed(2)}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          {/* 最优参数表 */}
          <Card>
            <h2 className="text-lg font-medium text-gray-900 mb-4">网格搜索最优参数</h2>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium text-gray-500">区间</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">买入跌幅</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">卖出涨幅</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">止损</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">利润空间</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">净盈亏</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">胜率</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">交易数</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {ZONE_NAMES.map((zn) => {
                    const p = result.best_params[zn];
                    if (!p || p.buy_dip_pct <= 0) {
                      return (
                        <tr key={zn}>
                          <td className="px-3 py-2 font-medium">{zn}</td>
                          <td colSpan={7} className="px-3 py-2 text-center text-gray-400">无可行参数</td>
                        </tr>
                      );
                    }
                    return (
                      <tr key={zn} className="hover:bg-gray-50">
                        <td className="px-3 py-2 font-medium">{zn}</td>
                        <td className="px-3 py-2 text-right">{p.buy_dip_pct.toFixed(2)}%</td>
                        <td className="px-3 py-2 text-right">{p.sell_rise_pct.toFixed(2)}%</td>
                        <td className="px-3 py-2 text-right">{p.stop_loss_pct.toFixed(1)}%</td>
                        <td className="px-3 py-2 text-right font-medium text-purple-600">
                          {p.profit_spread.toFixed(2)}%
                        </td>
                        <td className={`px-3 py-2 text-right font-medium ${p.avg_net_profit >= 0 ? "text-red-600" : "text-green-600"}`}>
                          {p.avg_net_profit.toFixed(4)}%
                        </td>
                        <td className="px-3 py-2 text-right">{p.win_rate.toFixed(1)}%</td>
                        <td className="px-3 py-2 text-right">{p.trades_count}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          {/* 开盘类型参数 */}
          {result.open_type_stats && (
            <Card>
              <h2 className="text-lg font-medium text-gray-900 mb-4">
                开盘类型参数
                {result.gap_threshold && (
                  <span className="ml-2 text-sm font-normal text-gray-500">
                    阈值: ±{result.gap_threshold}%
                  </span>
                )}
              </h2>

              {/* 开盘类型分布 */}
              <div className="mb-4">
                <h3 className="text-sm font-medium text-gray-700 mb-2">开盘类型分布</h3>
                <div className="flex gap-4">
                  {[
                    { key: "gap_up", label: "高开", color: "bg-red-100 text-red-800" },
                    { key: "flat", label: "平开", color: "bg-gray-100 text-gray-800" },
                    { key: "gap_down", label: "低开", color: "bg-green-100 text-green-800" },
                  ].map(({ key, label, color }) => {
                    const s = result.open_type_stats?.[key];
                    return (
                      <div key={key} className={`px-3 py-2 rounded-lg ${color} text-sm`}>
                        <span className="font-medium">{label}</span>: {s?.count ?? 0}天 ({s?.pct ?? 0}%)
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* 开盘类型参数表 */}
              {result.open_type_params && (
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200 text-sm">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium text-gray-500">开盘类型</th>
                        <th className="px-3 py-2 text-left font-medium text-gray-500">锚点</th>
                        <th className="px-3 py-2 text-right font-medium text-gray-500">买入跌幅</th>
                        <th className="px-3 py-2 text-right font-medium text-gray-500">卖出涨幅</th>
                        <th className="px-3 py-2 text-right font-medium text-gray-500">止损</th>
                        <th className="px-3 py-2 text-right font-medium text-gray-500">净盈亏</th>
                        <th className="px-3 py-2 text-right font-medium text-gray-500">胜率</th>
                        <th className="px-3 py-2 text-right font-medium text-gray-500">交易数</th>
                        <th className="px-3 py-2 text-center font-medium text-gray-500">建议</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200">
                      {[
                        { key: "gap_up", label: `高开(>${result.gap_threshold ?? 0.5}%)` },
                        { key: "flat", label: `平开(±${result.gap_threshold ?? 0.5}%)` },
                        { key: "gap_down", label: `低开(<-${result.gap_threshold ?? 0.5}%)` },
                      ].map(({ key, label }) => {
                        const p = result.open_type_params?.[key];
                        if (!p) return null;

                        const anchorLabel = p.anchor === "open_price" ? "开盘价" : "前收盘价";
                        const isFlat = key === "flat";
                        const rec = key === "gap_down" ? (p.recommendation === "trade" ? "交易" : "跳过") : (p.enabled ? "交易" : "不交易");
                        const recColor = rec === "交易" ? "bg-green-100 text-green-800" : rec === "跳过" ? "bg-red-100 text-red-800" : "bg-gray-100 text-gray-800";

                        return (
                          <tr key={key} className="hover:bg-gray-50">
                            <td className="px-3 py-2 font-medium">{label}</td>
                            <td className="px-3 py-2">{anchorLabel}</td>
                            <td className="px-3 py-2 text-right">
                              {isFlat ? "(按区间)" : p.buy_dip_pct != null ? `${p.buy_dip_pct.toFixed(2)}%` : "-"}
                            </td>
                            <td className="px-3 py-2 text-right">
                              {isFlat ? "(按区间)" : p.sell_rise_pct != null ? `${p.sell_rise_pct.toFixed(2)}%` : "-"}
                            </td>
                            <td className="px-3 py-2 text-right">
                              {isFlat ? "(按区间)" : p.stop_loss_pct != null ? `${p.stop_loss_pct.toFixed(1)}%` : "-"}
                            </td>
                            <td className={`px-3 py-2 text-right font-medium ${(p.avg_net_profit ?? 0) >= 0 ? "text-red-600" : "text-green-600"}`}>
                              {isFlat ? "-" : p.avg_net_profit != null ? `${p.avg_net_profit.toFixed(4)}%` : "-"}
                            </td>
                            <td className="px-3 py-2 text-right">
                              {isFlat ? "-" : p.win_rate != null ? `${p.win_rate.toFixed(1)}%` : "-"}
                            </td>
                            <td className="px-3 py-2 text-right">
                              {isFlat ? "-" : p.trades_count ?? "-"}
                            </td>
                            <td className="px-3 py-2 text-center">
                              <span className={`px-2 py-1 rounded-full text-xs font-medium ${recColor}`}>
                                {rec}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          )}

          {/* 模拟交易汇总 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card>
              <div className="text-center">
                <div className="text-sm text-gray-600 mb-1">总交易数</div>
                <div className="text-2xl font-bold text-gray-900">{result.trade_summary.total_trades}</div>
              </div>
            </Card>
            <Card>
              <div className="text-center">
                <div className="text-sm text-gray-600 mb-1">胜率</div>
                <div className="text-2xl font-bold text-blue-600">{result.trade_summary.win_rate.toFixed(1)}%</div>
              </div>
            </Card>
            <Card>
              <div className="text-center">
                <div className="text-sm text-gray-600 mb-1">平均净盈亏</div>
                <div className={`text-2xl font-bold ${result.trade_summary.avg_net_profit >= 0 ? "text-red-600" : "text-green-600"}`}>
                  {result.trade_summary.avg_net_profit.toFixed(4)}%
                </div>
              </div>
            </Card>
            <Card>
              <div className="text-center">
                <div className="text-sm text-gray-600 mb-1">止损率</div>
                <div className="text-2xl font-bold text-orange-600">{result.trade_summary.stop_loss_rate.toFixed(1)}%</div>
              </div>
            </Card>
          </div>

          {/* 自动交易面板 */}
          <Card>
            <h2 className="text-lg font-medium text-gray-900 mb-4">自动日内交易</h2>
            {result.last_day_info && result.last_day_info.close_price > 0 && (
              <div className="mb-4 p-3 bg-gray-50 border border-gray-200 rounded-lg text-sm">
                <div className="font-medium text-gray-700 mb-2">
                  前一交易日（{result.last_day_info.date}）概况
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-gray-600">
                  <span>收盘价: <span className="font-medium text-gray-900">{result.last_day_info.close_price}</span></span>
                  <span>区间: <span className="font-medium text-gray-900">{result.last_day_info.zone}</span></span>
                  <span>位置: <span className="font-medium text-gray-900">{result.last_day_info.price_position}%</span></span>
                  <span>开盘类型: <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-medium ${
                    result.last_day_info.open_type === "gap_up" ? "bg-red-100 text-red-700" :
                    result.last_day_info.open_type === "gap_down" ? "bg-green-100 text-green-700" :
                    "bg-gray-100 text-gray-700"
                  }`}>{
                    result.last_day_info.open_type === "gap_up" ? "高开" :
                    result.last_day_info.open_type === "gap_down" ? "低开" : "平开"
                  }{result.last_day_info.open_gap_pct !== 0 ? ` ${result.last_day_info.open_gap_pct > 0 ? "+" : ""}${result.last_day_info.open_gap_pct.toFixed(2)}%` : ""}</span></span>
                </div>
              </div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">选择区间</label>
                <select
                  value={selectedZone}
                  onChange={(e) => setSelectedZone(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md"
                >
                  <option value="">请选择</option>
                  {ZONE_NAMES.filter((zn) => {
                    const p = result.best_params[zn];
                    return p && p.buy_dip_pct > 0;
                  }).map((zn) => (
                    <option key={zn} value={zn}>{zn}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">交易数量（股）</label>
                <input
                  type="number"
                  value={tradeQuantity}
                  onChange={(e) => setTradeQuantity(parseInt(e.target.value) || 0)}
                  min={100}
                  step={100}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">前收盘价</label>
                <input
                  type="number"
                  value={prevClose || ""}
                  onChange={(e) => setPrevClose(parseFloat(e.target.value) || 0)}
                  step={0.01}
                  placeholder="输入前一交易日收盘价"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md"
                />
              </div>
              <div className="flex items-end">
                <Button
                  onClick={handleStartAutoTrade}
                  className="w-full bg-green-600 hover:bg-green-700 text-white"
                >
                  启动自动交易
                </Button>
              </div>
            </div>

            {selectedZone && result.best_params[selectedZone]?.buy_dip_pct > 0 && prevClose > 0 && (
              <div className="space-y-2 mb-4">
                <div className="bg-purple-50 border border-purple-200 rounded-lg p-3 text-sm">
                  <div className="font-medium text-purple-800 mb-1">平开日参数预览（{selectedZone}，锚点: 前收盘价）</div>
                  <div className="grid grid-cols-3 gap-2 text-purple-700">
                    <span>买入目标: {(prevClose * (1 - result.best_params[selectedZone].buy_dip_pct / 100)).toFixed(3)}</span>
                    <span>卖出目标: {(prevClose * (1 + result.best_params[selectedZone].sell_rise_pct / 100)).toFixed(3)}</span>
                    <span>止损价: {(prevClose * (1 - result.best_params[selectedZone].buy_dip_pct / 100) * (1 - result.best_params[selectedZone].stop_loss_pct / 100)).toFixed(3)}</span>
                  </div>
                </div>

                {result.open_type_params?.gap_up?.enabled && result.open_type_params.gap_up.buy_dip_pct != null && (
                  <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm">
                    <div className="font-medium text-red-800 mb-1">高开日参数预览（锚点: 开盘价，需开盘后确定）</div>
                    <div className="grid grid-cols-3 gap-2 text-red-700">
                      <span>买入回调: {result.open_type_params.gap_up.buy_dip_pct.toFixed(2)}%</span>
                      <span>卖出涨幅: {result.open_type_params.gap_up.sell_rise_pct?.toFixed(2)}%</span>
                      <span>止损: {result.open_type_params.gap_up.stop_loss_pct?.toFixed(1)}%</span>
                    </div>
                  </div>
                )}
              </div>
            )}
          </Card>
        </div>
      )}

      {/* 活跃交易任务 */}
      {autoTradeTasks.length > 0 && (
        <div className="mt-6">
          <Card>
            <h2 className="text-lg font-medium text-gray-900 mb-4">
              自动交易任务
              <span className="ml-2 px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-sm">
                {autoTradeTasks.length}
              </span>
            </h2>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium text-gray-500">股票</th>
                    <th className="px-3 py-2 text-center font-medium text-gray-500">状态</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">数量</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">买入目标</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">卖出目标</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">止损价</th>
                    <th className="px-3 py-2 text-left font-medium text-gray-500">信息</th>
                    <th className="px-3 py-2 text-center font-medium text-gray-500">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {autoTradeTasks.map((task) => {
                    const statusInfo = STATUS_LABELS[task.status] || { text: task.status, color: "bg-gray-100 text-gray-800" };
                    const isActive = task.status === "waiting_buy" || task.status === "bought";
                    return (
                      <tr key={task.stock_code} className="hover:bg-gray-50">
                        <td className="px-3 py-2 font-medium">{task.stock_code}</td>
                        <td className="px-3 py-2 text-center">
                          <span className={`px-2 py-1 rounded-full text-xs font-medium ${statusInfo.color}`}>
                            {statusInfo.text}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-right">{task.quantity}</td>
                        <td className="px-3 py-2 text-right">{task.buy_target.toFixed(3)}</td>
                        <td className="px-3 py-2 text-right">{task.sell_target.toFixed(3)}</td>
                        <td className="px-3 py-2 text-right">{task.stop_price.toFixed(3)}</td>
                        <td className="px-3 py-2 text-gray-600 text-xs max-w-xs truncate">{task.message}</td>
                        <td className="px-3 py-2 text-center">
                          {isActive && (
                            <button
                              onClick={() => handleStopAutoTrade(task.stock_code)}
                              className="px-2 py-1 text-xs bg-red-100 text-red-700 rounded hover:bg-red-200"
                            >
                              停止
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
