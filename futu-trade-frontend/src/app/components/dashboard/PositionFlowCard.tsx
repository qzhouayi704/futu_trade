// 持仓股票资金流向监控卡片
"use client";

import React, { useState } from "react";
import { Card } from "@/components/common";
import {
  ChevronDown,
  ChevronUp,
  Coins,
  TrendingUp,
  TrendingDown,
  Info,
  RefreshCw
} from "lucide-react";
import type { PositionCapitalFlow } from "@/types";

interface PositionFlowCardProps {
  data: PositionCapitalFlow[];
  loading?: boolean;
}

// 格式化资金单位为元/万/亿
function formatCapital(val: number): string {
  const absVal = Math.abs(val);
  if (absVal >= 100000000) {
    return `${(val / 100000000).toFixed(2)} 亿`;
  }
  if (absVal >= 10000) {
    return `${(val / 10000).toFixed(2)} 万`;
  }
  return `${val.toFixed(0)} 元`;
}

// 获取资金评分的对应样式和标签
function getScoreConfig(score: number) {
  if (score >= 75) {
    return {
      text: "极佳",
      badge: "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/30 dark:text-red-400 dark:border-red-800/30",
      textClass: "text-red-600 dark:text-red-400"
    };
  }
  if (score >= 40) {
    return {
      text: "偏多",
      badge: "bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-950/30 dark:text-orange-400 dark:border-orange-800/30",
      textClass: "text-orange-600 dark:text-orange-400"
    };
  }
  if (score >= -40) {
    return {
      text: "中性",
      badge: "bg-gray-50 text-gray-700 border-gray-200 dark:bg-gray-800/50 dark:text-gray-400 dark:border-gray-700",
      textClass: "text-gray-600 dark:text-gray-400"
    };
  }
  return {
    text: "偏空",
    badge: "bg-green-50 text-green-700 border-green-200 dark:bg-green-950/30 dark:text-green-400 dark:border-green-800/30",
    textClass: "text-green-600 dark:text-green-400"
  };
}

export function PositionFlowCard({ data = [], loading = false }: PositionFlowCardProps) {
  const [expandedStock, setExpandedStock] = useState<string | null>(null);

  const toggleExpand = (stockCode: string) => {
    setExpandedStock(expandedStock === stockCode ? null : stockCode);
  };

  // 过滤出有资金流向数据的持仓股票
  const validData = data.filter((item) => item.has_flow_data);

  return (
    <Card className="overflow-hidden border border-gray-100 dark:border-gray-800 shadow-sm">
      <div className="p-6">
        {/* 头部栏 */}
        <div className="flex items-center justify-between mb-5 border-b border-gray-50 dark:border-gray-800/50 pb-4">
          <div className="flex items-center gap-2">
            <div className="p-2 bg-indigo-50 dark:bg-indigo-950/40 rounded-lg text-indigo-600 dark:text-indigo-400">
              <Coins className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-gray-900 dark:text-white">
                持仓资金流向
              </h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                实时监控当前持仓股的主力及散户买卖数据
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs bg-indigo-50/50 dark:bg-indigo-950/20 text-indigo-600 dark:text-indigo-400 px-2.5 py-1 rounded-full border border-indigo-100/30">
            <span className="flex h-2 w-2 relative">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
            </span>
            <span>15s 自动刷新</span>
          </div>
        </div>

        {/* 加载状态 */}
        {loading ? (
          <div className="space-y-4 py-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="animate-pulse space-y-3 p-4 rounded-xl border border-gray-100 dark:border-gray-800">
                <div className="flex justify-between items-center">
                  <div className="h-5 bg-gray-200 dark:bg-gray-700 rounded w-1/4" />
                  <div className="h-5 bg-gray-200 dark:bg-gray-700 rounded w-1/5" />
                </div>
                <div className="h-3 bg-gray-100 dark:bg-gray-800 rounded w-full" />
              </div>
            ))}
          </div>
        ) : data.length === 0 ? (
          /* 空仓状态 */
          <div className="flex flex-col items-center justify-center py-12 px-4 text-center rounded-xl bg-gray-50/50 dark:bg-gray-900/20 border border-dashed border-gray-200 dark:border-gray-800">
            <div className="p-3 bg-gray-100 dark:bg-gray-800 rounded-full text-gray-400 dark:text-gray-500 mb-3">
              <Info className="w-6 h-6" />
            </div>
            <h4 className="text-sm font-semibold text-gray-800 dark:text-gray-200 mb-1">
              暂无持仓数据
            </h4>
            <p className="text-xs text-gray-500 dark:text-gray-400 max-w-xs">
              系统当前未检测到活跃持仓，或持仓尚未建立资金流向数据
            </p>
          </div>
        ) : (
          /* 资金流向列表 */
          <div className="space-y-3">
            {data.map((item) => {
              const scoreCfg = getScoreConfig(item.capital_score);
              const isNetInflow = item.main_net_inflow >= 0;
              const isExpanded = expandedStock === item.stock_code;

              return (
                <div
                  key={item.stock_code}
                  className={`group rounded-xl border transition-all duration-300 ${
                    isExpanded
                      ? "border-indigo-500 bg-indigo-50/10 dark:border-indigo-500/50 dark:bg-indigo-950/10 shadow-sm"
                      : "border-gray-100 dark:border-gray-800/80 hover:border-indigo-200 hover:bg-gray-50/30 dark:hover:border-indigo-950/50 dark:hover:bg-indigo-950/5"
                  }`}
                >
                  {/* 主要摘要行 */}
                  <div
                    onClick={() => toggleExpand(item.stock_code)}
                    className="p-4 flex flex-col md:flex-row md:items-center justify-between gap-4 cursor-pointer select-none"
                  >
                    {/* 股票基本信息 */}
                    <div className="flex items-center gap-3">
                      <div>
                        <div className="font-semibold text-gray-900 dark:text-white group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors">
                          {item.stock_name}
                        </div>
                        <div className="text-xs text-gray-500 dark:text-gray-400 font-mono mt-0.5">
                          {item.stock_code}
                        </div>
                      </div>
                    </div>

                    {/* 核心资金流向指标 */}
                    {!item.has_flow_data ? (
                      <div className="text-xs text-gray-400 dark:text-gray-500 flex items-center gap-1.5 bg-gray-50 dark:bg-gray-800/40 px-3 py-1.5 rounded-lg border border-gray-100/50 dark:border-gray-700/30">
                        <Info className="w-3.5 h-3.5" />
                        <span>暂无资金流数据 (已订阅但未产生)</span>
                      </div>
                    ) : (
                      <div className="flex flex-1 flex-wrap items-center justify-between md:justify-end gap-x-6 gap-y-3">
                        {/* 主力净流入 */}
                        <div className="text-right">
                          <div className="text-xs text-gray-400 dark:text-gray-500 mb-0.5">
                            主力净流入
                          </div>
                          <div
                            className={`text-sm font-bold flex items-center justify-end gap-1 ${
                              isNetInflow
                                ? "text-red-600 dark:text-red-400"
                                : "text-green-600 dark:text-green-400"
                            }`}
                          >
                            {isNetInflow ? (
                              <TrendingUp className="w-4 h-4 shrink-0" />
                            ) : (
                              <TrendingDown className="w-4 h-4 shrink-0" />
                            )}
                            <span>{isNetInflow ? "+" : ""}</span>
                            <span>{formatCapital(item.main_net_inflow)}</span>
                          </div>
                        </div>

                        {/* 主力买入占比进度条 */}
                        <div className="w-24 md:w-32">
                          <div className="flex justify-between text-[10px] text-gray-400 dark:text-gray-500 mb-1">
                            <span>买 {(item.big_order_buy_ratio * 100).toFixed(0)}%</span>
                            <span>卖 {((1 - item.big_order_buy_ratio) * 100).toFixed(0)}%</span>
                          </div>
                          <div className="h-1.5 w-full bg-green-200 dark:bg-green-900/60 rounded-full overflow-hidden flex">
                            <div
                              style={{ width: `${item.big_order_buy_ratio * 100}%` }}
                              className="h-full bg-red-500 dark:bg-red-600 rounded-full transition-all duration-500"
                            />
                          </div>
                        </div>

                        {/* 逐笔买卖力量 */}
                        {item.has_ticker_data && (
                          <div className="text-right min-w-14">
                            <div className="text-xs text-gray-400 dark:text-gray-500 mb-0.5">
                              逐笔力量
                            </div>
                            <span
                              className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold border ${
                                item.ticker_power > 0.2
                                  ? "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/30 dark:text-red-400 dark:border-red-800/30"
                                  : item.ticker_power > 0
                                  ? "bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-950/30 dark:text-orange-400 dark:border-orange-800/30"
                                  : item.ticker_power > -0.2
                                  ? "bg-gray-50 text-gray-700 border-gray-200 dark:bg-gray-800/50 dark:text-gray-400 dark:border-gray-700"
                                  : "bg-green-50 text-green-700 border-green-200 dark:bg-green-950/30 dark:text-green-400 dark:border-green-800/30"
                              }`}
                            >
                              {item.ticker_bsr > 0 ? item.ticker_bsr.toFixed(2) : "—"}
                            </span>
                          </div>
                        )}

                        {/* 资金评分 */}
                        <div className="text-right min-w-16">
                          <div className="text-xs text-gray-400 dark:text-gray-500 mb-0.5">
                            资金评分
                          </div>
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border ${scoreCfg.badge}`}
                          >
                            {item.capital_score.toFixed(0)} / {scoreCfg.text}
                          </span>
                        </div>
                      </div>
                    )}

                    {/* 展开/收起箭头 */}
                    <div className="text-gray-400 hover:text-indigo-500 dark:text-gray-600 transition-colors flex items-center justify-end self-end md:self-auto">
                      {isExpanded ? (
                        <ChevronUp className="w-5 h-5" />
                      ) : (
                        <ChevronDown className="w-5 h-5" />
                      )}
                    </div>
                  </div>

                  {/* 展开的资金流向详情 */}
                  {isExpanded && item.has_flow_data && (
                    <div className="border-t border-gray-100 dark:border-gray-800/80 p-4 bg-gray-50/50 dark:bg-gray-900/10 rounded-b-xl animate-fadeIn">
                      <h5 className="text-xs font-bold text-gray-500 dark:text-gray-400 mb-3 uppercase tracking-wider flex items-center gap-1.5">
                        <Info className="w-3.5 h-3.5" />
                        资金成交明细 (大单/中单/小单分类)
                      </h5>
                      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                        {/* 超大单 */}
                        <div className="bg-white dark:bg-gray-800/50 p-3 rounded-lg border border-gray-100 dark:border-gray-800/30">
                          <div className="text-xs font-semibold text-purple-600 dark:text-purple-400 mb-2">
                            超大单 (主控力)
                          </div>
                          <div className="space-y-1 text-xs">
                            <div className="flex justify-between text-gray-500">
                              <span>买入额</span>
                              <span className="text-red-500">{formatCapital(item.super_large_inflow)}</span>
                            </div>
                            <div className="flex justify-between text-gray-500">
                              <span>卖出额</span>
                              <span className="text-green-500">{formatCapital(item.super_large_outflow)}</span>
                            </div>
                            <div className="flex justify-between pt-1 border-t border-dashed border-gray-100 dark:border-gray-800 font-semibold text-gray-700 dark:text-gray-300">
                              <span>净流入</span>
                              <span className={item.super_large_inflow - item.super_large_outflow >= 0 ? "text-red-600" : "text-green-600"}>
                                {item.super_large_inflow - item.super_large_outflow >= 0 ? "+" : ""}
                                {formatCapital(item.super_large_inflow - item.super_large_outflow)}
                              </span>
                            </div>
                          </div>
                        </div>

                        {/* 大单 */}
                        <div className="bg-white dark:bg-gray-800/50 p-3 rounded-lg border border-gray-100 dark:border-gray-800/30">
                          <div className="text-xs font-semibold text-red-600 dark:text-red-400 mb-2">
                            大单 (主力)
                          </div>
                          <div className="space-y-1 text-xs">
                            <div className="flex justify-between text-gray-500">
                              <span>买入额</span>
                              <span className="text-red-500">{formatCapital(item.large_inflow)}</span>
                            </div>
                            <div className="flex justify-between text-gray-500">
                              <span>卖出额</span>
                              <span className="text-green-500">{formatCapital(item.large_outflow)}</span>
                            </div>
                            <div className="flex justify-between pt-1 border-t border-dashed border-gray-100 dark:border-gray-800 font-semibold text-gray-700 dark:text-gray-300">
                              <span>净流入</span>
                              <span className={item.large_inflow - item.large_outflow >= 0 ? "text-red-600" : "text-green-600"}>
                                {item.large_inflow - item.large_outflow >= 0 ? "+" : ""}
                                {formatCapital(item.large_inflow - item.large_outflow)}
                              </span>
                            </div>
                          </div>
                        </div>

                        {/* 中单 */}
                        <div className="bg-white dark:bg-gray-800/50 p-3 rounded-lg border border-gray-100 dark:border-gray-800/30">
                          <div className="text-xs font-semibold text-blue-600 dark:text-blue-400 mb-2">
                            中单 (中户)
                          </div>
                          <div className="space-y-1 text-xs">
                            <div className="flex justify-between text-gray-500">
                              <span>买入额</span>
                              <span className="text-red-500">{formatCapital(item.medium_inflow)}</span>
                            </div>
                            <div className="flex justify-between text-gray-500">
                              <span>卖出额</span>
                              <span className="text-green-500">{formatCapital(item.medium_outflow)}</span>
                            </div>
                            <div className="flex justify-between pt-1 border-t border-dashed border-gray-100 dark:border-gray-800 font-semibold text-gray-700 dark:text-gray-300">
                              <span>净流入</span>
                              <span className={item.medium_inflow - item.medium_outflow >= 0 ? "text-red-600" : "text-green-600"}>
                                {item.medium_inflow - item.medium_outflow >= 0 ? "+" : ""}
                                {formatCapital(item.medium_inflow - item.medium_outflow)}
                              </span>
                            </div>
                          </div>
                        </div>

                        {/* 小单 */}
                        <div className="bg-white dark:bg-gray-800/50 p-3 rounded-lg border border-gray-100 dark:border-gray-800/30">
                          <div className="text-xs font-semibold text-gray-600 dark:text-gray-400 mb-2">
                            小单 (散户)
                          </div>
                          <div className="space-y-1 text-xs">
                            <div className="flex justify-between text-gray-500">
                              <span>买入额</span>
                              <span className="text-red-500">{formatCapital(item.small_inflow)}</span>
                            </div>
                            <div className="flex justify-between text-gray-500">
                              <span>卖出额</span>
                              <span className="text-green-500">{formatCapital(item.small_outflow)}</span>
                            </div>
                            <div className="flex justify-between pt-1 border-t border-dashed border-gray-100 dark:border-gray-800 font-semibold text-gray-700 dark:text-gray-300">
                              <span>净流入</span>
                              <span className={item.small_inflow - item.small_outflow >= 0 ? "text-red-600" : "text-green-600"}>
                                {item.small_inflow - item.small_outflow >= 0 ? "+" : ""}
                                {formatCapital(item.small_inflow - item.small_outflow)}
                              </span>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Card>
  );
}
