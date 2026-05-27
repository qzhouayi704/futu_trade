// 模拟交易记录页面 — 每日汇总 + 详细记录
"use client";

import { useState, useEffect, useCallback } from "react";
import { Card } from "@/components/common";
import apiClient from "@/lib/api/client";

interface DailyStat {
  date: string;
  total_trades: number;
  buy_count: number;
  sell_count: number;
  total_amount: number;
  stock_count: number;
}

interface TradeRecord {
  id: number;
  stock_code: string;
  stock_name: string;
  direction: string;
  price: number;
  quantity: number;
  amount: number;
  resonance_type: string;
  reason: string;
  sources: string;
  created_at: string;
}

const resonanceLabels: Record<string, string> = {
  dual_source: "双源共振",
  strong_single: "强信号",
  multi_green: "多重绿色",
};

export default function SimulatedTradesPage() {
  const [dailyStats, setDailyStats] = useState<DailyStat[]>([]);
  const [records, setRecords] = useState<TradeRecord[]>([]);
  const [selectedDate, setSelectedDate] = useState("");
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async (date: string) => {
    setLoading(true);
    try {
      const params = date ? `?date=${date}` : "";
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await apiClient.get(`/sniper/simulated-trades/daily${params}`);
      if (res.success && res.data) {
        setDailyStats(res.data.daily_stats || []);
        setRecords(res.data.records || []);
      }
    } catch (e) {
      console.error("加载模拟交易数据失败:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData(selectedDate);
  }, [selectedDate, loadData]);

  const handleDateClick = (date: string) => {
    setSelectedDate(date === selectedDate ? "" : date);
  };

  // 汇总统计
  const totalTrades = dailyStats.reduce((s, d) => s + d.total_trades, 0);
  const totalBuys = dailyStats.reduce((s, d) => s + d.buy_count, 0);
  const totalSells = dailyStats.reduce((s, d) => s + d.sell_count, 0);
  const totalDays = dailyStats.length;

  return (
    <div className="container mx-auto px-3 md:px-4 py-4 md:py-6 max-w-7xl">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-4 md:mb-6">
        <h1 className="text-xl md:text-2xl font-bold text-gray-900 flex items-center gap-2">
          <span>📋</span> 模拟交易记录
        </h1>
        <button
          onClick={() => loadData(selectedDate)}
          className="px-3 py-1.5 text-sm text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
        >
          🔄 刷新
        </button>
      </div>

      {/* 总览卡片 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 md:mb-6">
        <Card>
          <div className="p-4 text-center">
            <div className="text-2xl font-bold text-gray-900">{totalTrades}</div>
            <div className="text-xs text-gray-500 mt-1">总交易次数</div>
          </div>
        </Card>
        <Card>
          <div className="p-4 text-center">
            <div className="text-2xl font-bold text-emerald-600">{totalBuys}</div>
            <div className="text-xs text-gray-500 mt-1">买入次数</div>
          </div>
        </Card>
        <Card>
          <div className="p-4 text-center">
            <div className="text-2xl font-bold text-red-600">{totalSells}</div>
            <div className="text-xs text-gray-500 mt-1">卖出次数</div>
          </div>
        </Card>
        <Card>
          <div className="p-4 text-center">
            <div className="text-2xl font-bold text-blue-600">{totalDays}</div>
            <div className="text-xs text-gray-500 mt-1">交易天数</div>
          </div>
        </Card>
      </div>

      {loading ? (
        <div className="text-center py-12 text-gray-400">加载中...</div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 md:gap-6">
          {/* 左侧：每日汇总 */}
          <Card>
            <div className="p-4">
              <h3 className="text-base font-semibold text-gray-900 mb-3">📅 每日汇总</h3>
              {dailyStats.length === 0 ? (
                <div className="text-center py-8 text-gray-400 text-sm">暂无交易记录</div>
              ) : (
                <div className="space-y-1.5">
                  {dailyStats.map((stat) => (
                    <button
                      key={stat.date}
                      onClick={() => handleDateClick(stat.date)}
                      className={`w-full text-left px-3 py-2.5 rounded-lg border transition-all ${
                        selectedDate === stat.date
                          ? "bg-blue-50 border-blue-300 shadow-sm"
                          : "bg-white border-gray-100 hover:border-gray-200 hover:bg-gray-50"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-semibold text-gray-800">{stat.date}</span>
                        <span className="text-xs text-gray-400">{stat.stock_count} 只股票</span>
                      </div>
                      <div className="flex items-center gap-3 mt-1">
                        <span className="text-[11px] text-emerald-600 font-medium">
                          买{stat.buy_count}
                        </span>
                        <span className="text-[11px] text-red-600 font-medium">
                          卖{stat.sell_count}
                        </span>
                        <span className="text-[11px] text-gray-400">
                          共{stat.total_trades}笔
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </Card>

          {/* 右侧：详细记录 */}
          <div className="lg:col-span-2">
            <Card>
              <div className="p-4">
                <h3 className="text-base font-semibold text-gray-900 mb-3">
                  {selectedDate ? `📄 ${selectedDate} 交易明细` : "📄 请选择日期查看明细"}
                </h3>
                {!selectedDate ? (
                  <div className="text-center py-12 text-gray-400 text-sm">
                    ← 点击左侧日期查看当天交易明细
                  </div>
                ) : records.length === 0 ? (
                  <div className="text-center py-12 text-gray-400 text-sm">
                    该日期无交易记录
                  </div>
                ) : (
                  <div className="space-y-2">
                    {records.map((r) => {
                      const isBuy = r.direction === "BUY";
                      const timeStr = r.created_at
                        ? new Date(r.created_at).toLocaleTimeString("zh-CN", {
                            hour: "2-digit", minute: "2-digit", second: "2-digit",
                          })
                        : "";
                      return (
                        <div
                          key={r.id}
                          className={`px-3 py-2.5 rounded-lg border ${
                            isBuy
                              ? "bg-emerald-50/60 border-emerald-200/50"
                              : "bg-red-50/60 border-red-200/50"
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 min-w-0">
                              <span className="text-[11px] font-mono text-gray-400">{timeStr}</span>
                              <span className={`text-sm font-bold ${isBuy ? "text-emerald-600" : "text-red-600"}`}>
                                {isBuy ? "🟢 买入" : "🔴 卖出"}
                              </span>
                              <span className="font-bold text-sm text-gray-800">{r.stock_name}</span>
                              <span className="text-xs text-gray-400">({r.stock_code})</span>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              <span className="text-sm font-bold tabular-nums text-gray-700">
                                ${r.price.toFixed(3)}
                              </span>
                              <span className="text-xs text-gray-400">x{r.quantity}</span>
                              <span className="text-xs font-medium text-gray-500">
                                ≈${r.amount?.toFixed(0)}
                              </span>
                            </div>
                          </div>
                          <div className="flex items-center gap-2 mt-1.5">
                            {r.resonance_type && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 font-medium">
                                {resonanceLabels[r.resonance_type] || r.resonance_type}
                              </span>
                            )}
                            {r.sources && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 font-medium">
                                {r.sources}
                              </span>
                            )}
                            <span className="text-[11px] text-gray-500 truncate">{r.reason}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
