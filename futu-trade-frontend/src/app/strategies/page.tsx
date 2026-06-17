'use client';

import { useState } from 'react';

/* ── 策略数据定义 ── */
interface StrategyDimension {
  name: string;
  maxScore: number;
  description: string;
}

interface BacktestResult {
  trades: number;
  avgReturn: string;
  winRate: string;
  profitFactor: string;
  avgHold: string;
  period: string;
}

interface TradeParams {
  buyMethod: string;
  stopLoss: string;
  trailingTP: string;
  maxHold: string;
}

interface Strategy {
  id: string;
  name: string;
  label: string;
  icon: string;
  status: 'active' | 'archived' | 'testing';
  statusLabel: string;
  description: string;
  logic: string;
  dimensions: StrategyDimension[];
  tradeParams: TradeParams;
  backtest: BacktestResult;
  bestCombo?: string;
  archiveReason?: string;
  archivePath?: string;
}

const strategies: Strategy[] = [
  {
    id: 'trend',
    name: 'TREND',
    label: '📈 趋势策略',
    icon: '📈',
    status: 'active',
    statusLabel: '运行中',
    description: '捕获放量强势启动的股票，通过量价配合和逐笔买卖力量判断趋势方向。',
    logic: '当股票出现放量上涨（量比≥1.5x）、日内振幅足够（≥5%）、5日涨跌在合理区间（-2%~15%）、且逐笔成交显示主动买入力量强时，给出高评分。',
    dimensions: [
      { name: '5日涨跌', maxScore: 20, description: '近5日累计涨跌幅，最优区间 -2%~15%' },
      { name: '日内振幅', maxScore: 20, description: '当日最高-最低价幅度，≥5%为佳' },
      { name: '量比', maxScore: 25, description: '今日成交量/5日均量，≥3x为强信号' },
      { name: '逐笔买卖力量', maxScore: 25, description: '基于逐笔成交的主动买卖比(BSR-1.0)' },
      { name: 'K线位置', maxScore: 5, description: '20日价格区间位置' },
      { name: '前日涨跌', maxScore: 5, description: '前日涨幅（反向，前日大涨则扣分）' },
    ],
    tradeParams: {
      buyMethod: 'T+1 阶梯低吸（前收-1%优先，未成交则开盘买入）',
      stopLoss: '8%',
      trailingTP: '涨10%后回撤3%触发卖出',
      maxHold: '3天',
    },
    backtest: {
      trades: 1689,
      avgReturn: '+1.14%',
      winRate: '48.9%',
      profitFactor: '1.50',
      avgHold: '2.7天',
      period: '2026-04 ~ 2026-05（26个交易日）',
    },
    bestCombo: 'TREND 75-85分：152笔，+2.16%，55.9%胜率，PF=2.02',
  },
  {
    id: 'breakout',
    name: 'BREAKOUT',
    label: '🔺 蓄势突破',
    icon: '🔺',
    status: 'active',
    statusLabel: '运行中',
    description: '识别突破前期阻力位的股票，通过突破级别、资金流入和量能确认信号有效性。',
    logic: '当股票收盘价突破近5/10/20日最高价，且伴随放量和资金净流入时触发。突破级别越高（20日>10日>5日）、突破幅度适中（0~3%最佳）、资金持续流入天数越多，评分越高。',
    dimensions: [
      { name: '突破级别', maxScore: 15, description: '20日高=15分，10日高=12分，5日高=8分' },
      { name: '突破幅度', maxScore: 15, description: '突破阻力位的幅度，0~3%最优' },
      { name: '资金净流入', maxScore: 15, description: '富途API资金流入占比' },
      { name: '大单买比', maxScore: 10, description: '大单买入占比≥60%为强' },
      { name: '资金连续流入', maxScore: 10, description: '连续净流入天数' },
      { name: '量比', maxScore: 15, description: '放量确认突破有效性' },
      { name: '逐笔买卖力量', maxScore: 10, description: '逐笔成交主动买入力量' },
      { name: '涨幅适中', maxScore: 10, description: '当日涨幅1~5%最优' },
    ],
    tradeParams: {
      buyMethod: 'T+1 开盘买入（突破确认性入场）',
      stopLoss: '8%',
      trailingTP: '涨10%后回撤3%触发卖出',
      maxHold: '5天',
    },
    backtest: {
      trades: 208,
      avgReturn: '-0.08%',
      winRate: '43.3%',
      profitFactor: '0.97',
      avgHold: '4.2天',
      period: '2026-04 ~ 2026-05（26个交易日）',
    },
    bestCombo: 'BREAKOUT 85-100分：10笔，+1.55%，60%胜率，PF=1.65',
  },
  {
    id: 'reversal',
    name: 'REVERSAL',
    label: '📉 趋势反转',
    icon: '📉',
    status: 'archived',
    statusLabel: '已归档',
    description: '原用于识别超跌反弹机会，通过检测低位、近期下跌、放量反弹等条件筛选可能反转的股票。',
    logic: '当股票处于20日低位（K线位置<20%）、5日跌幅>3%、出现阳线反转+放量时给出高评分。',
    archiveReason: '回测数据证明该策略在港股市场无效：2226个超跌样本，200+参数组合测试，所有组合3日收益均为负。根本原因是港股动量效应强——跌的股票大概率继续跌。蓝思科技案例分析证明真正有效的底部反转信号已被 TREND + BREAKOUT 覆盖。',
    archivePath: 'strategy_archive/reversal_v1.py',
    dimensions: [
      { name: 'K线低位', maxScore: 15, description: '20日价格区间底部位置' },
      { name: '5日跌幅', maxScore: 15, description: '近5日累计跌幅，-3%~-15%' },
      { name: '前日跌幅', maxScore: 10, description: '前一日跌幅' },
      { name: '低位反弹', maxScore: 15, description: '距5日低点反弹幅度' },
      { name: '今日涨幅', maxScore: 10, description: '当日阳线反转' },
      { name: '逐笔买卖力量', maxScore: 15, description: '反弹伴随主动买入' },
      { name: '量比', maxScore: 15, description: '放量确认反弹' },
      { name: '日内振幅', maxScore: 5, description: '交易可行性' },
    ],
    tradeParams: {
      buyMethod: 'T+1 开盘买入',
      stopLoss: '12%（v2收紧）',
      trailingTP: '涨8%后回撤5%触发卖出',
      maxHold: '5天',
    },
    backtest: {
      trades: 664,
      avgReturn: '-0.61%',
      winRate: '43.4%',
      profitFactor: '0.82',
      avgHold: '4.2天',
      period: '2026-04 ~ 2026-05（26个交易日）',
    },
  },
];

/* ── 状态标签组件 ── */
function StatusBadge({ status, label }: { status: string; label: string }) {
  const colors: Record<string, string> = {
    active: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800',
    archived: 'bg-gray-100 text-gray-500 border-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:border-gray-700',
    testing: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-800',
  };
  const dots: Record<string, string> = {
    active: 'bg-emerald-500',
    archived: 'bg-gray-400',
    testing: 'bg-amber-500 animate-pulse',
  };
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${colors[status] || colors.archived}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${dots[status] || dots.archived}`} />
      {label}
    </span>
  );
}

/* ── 评分维度进度条 ── */
function DimensionBar({ dim }: { dim: StrategyDimension }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-gray-600 dark:text-gray-400 w-24 flex-shrink-0 truncate" title={dim.description}>{dim.name}</span>
      <div className="flex-1 bg-gray-100 dark:bg-gray-800 rounded-full h-2 overflow-hidden">
        <div className="h-full rounded-full bg-gradient-to-r from-indigo-400 to-indigo-600" style={{ width: `${(dim.maxScore / 25) * 100}%` }} />
      </div>
      <span className="text-xs font-mono text-gray-500 w-8 text-right">{dim.maxScore}分</span>
    </div>
  );
}

/* ── 策略卡片 ── */
function StrategyCard({ strategy, isExpanded, onToggle }: { strategy: Strategy; isExpanded: boolean; onToggle: () => void }) {
  const isActive = strategy.status === 'active';
  const borderColor = isActive ? 'border-indigo-200 dark:border-indigo-800/50' : 'border-gray-200 dark:border-gray-700/50';
  const bgColor = isActive ? 'bg-white dark:bg-gray-900' : 'bg-gray-50/50 dark:bg-gray-900/50';

  return (
    <div className={`rounded-2xl border ${borderColor} ${bgColor} overflow-hidden shadow-sm hover:shadow-md transition-shadow`}>
      {/* Header */}
      <button onClick={onToggle} className="w-full flex items-center justify-between p-5 text-left group">
        <div className="flex items-center gap-4">
          <div className={`w-12 h-12 rounded-xl flex items-center justify-center text-2xl ${isActive ? 'bg-indigo-50 dark:bg-indigo-900/30' : 'bg-gray-100 dark:bg-gray-800'}`}>
            {strategy.icon}
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h3 className="text-lg font-bold text-gray-900 dark:text-gray-100">{strategy.label}</h3>
              <StatusBadge status={strategy.status} label={strategy.statusLabel} />
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-1">{strategy.description}</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {/* Key metrics summary */}
          <div className="hidden sm:flex items-center gap-4">
            <div className="text-center">
              <div className={`text-sm font-bold ${parseFloat(strategy.backtest.avgReturn) >= 0 ? 'text-red-600' : 'text-green-600'}`}>{strategy.backtest.avgReturn}</div>
              <div className="text-[10px] text-gray-400">收益</div>
            </div>
            <div className="text-center">
              <div className="text-sm font-bold text-gray-700 dark:text-gray-300">{strategy.backtest.winRate}</div>
              <div className="text-[10px] text-gray-400">胜率·回测</div>
            </div>
            <div className="text-center">
              <div className={`text-sm font-bold ${parseFloat(strategy.backtest.profitFactor) >= 1.0 ? 'text-indigo-600' : 'text-gray-400'}`}>{strategy.backtest.profitFactor}</div>
              <div className="text-[10px] text-gray-400">PF</div>
            </div>
          </div>
          <svg className={`w-5 h-5 text-gray-400 transition-transform duration-300 ${isExpanded ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {/* Expanded Content */}
      {isExpanded && (
        <div className="border-t border-gray-100 dark:border-gray-800">
          {/* Archive Warning */}
          {strategy.archiveReason && (
            <div className="mx-5 mt-4 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/50">
              <div className="flex items-start gap-2">
                <span className="text-amber-500 text-sm mt-0.5">⚠️</span>
                <div>
                  <div className="text-xs font-semibold text-amber-700 dark:text-amber-400 mb-1">归档原因</div>
                  <p className="text-xs text-amber-600 dark:text-amber-500 leading-relaxed">{strategy.archiveReason}</p>
                  {strategy.archivePath && (
                    <p className="text-[10px] text-amber-500/70 mt-1 font-mono">📁 {strategy.archivePath}</p>
                  )}
                </div>
              </div>
            </div>
          )}

          <div className="p-5 grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Left Column */}
            <div className="space-y-5">
              {/* Strategy Logic */}
              <div>
                <h4 className="text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">策略逻辑</h4>
                <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">{strategy.logic}</p>
              </div>

              {/* Scoring Dimensions */}
              <div>
                <h4 className="text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">评分维度（满分100）</h4>
                <div className="space-y-2">
                  {strategy.dimensions.map((dim) => (
                    <DimensionBar key={dim.name} dim={dim} />
                  ))}
                </div>
                <div className="mt-2 text-right text-xs text-gray-400">
                  总分 = {strategy.dimensions.reduce((s, d) => s + d.maxScore, 0)}
                </div>
              </div>
            </div>

            {/* Right Column */}
            <div className="space-y-5">
              {/* Trade Parameters */}
              <div>
                <h4 className="text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">交易参数</h4>
                <div className="bg-gray-50 dark:bg-gray-800/50 rounded-lg p-3 space-y-2">
                  {[
                    ['买入方式', strategy.tradeParams.buyMethod],
                    ['止损', strategy.tradeParams.stopLoss],
                    ['追踪止盈', strategy.tradeParams.trailingTP],
                    ['最大持仓', strategy.tradeParams.maxHold],
                  ].map(([label, value]) => (
                    <div key={label} className="flex justify-between items-start">
                      <span className="text-xs text-gray-500 dark:text-gray-400 flex-shrink-0">{label}</span>
                      <span className="text-xs font-medium text-gray-700 dark:text-gray-300 text-right ml-3">{value}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Backtest Results */}
              <div>
                <h4 className="text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">回测结果</h4>
                <div className="bg-gray-50 dark:bg-gray-800/50 rounded-lg p-3">
                  <div className="grid grid-cols-3 gap-3 mb-3">
                    <div className="text-center">
                      <div className={`text-lg font-bold ${parseFloat(strategy.backtest.avgReturn) >= 0 ? 'text-red-600' : 'text-green-600'}`}>{strategy.backtest.avgReturn}</div>
                      <div className="text-[10px] text-gray-400">笔均收益</div>
                    </div>
                    <div className="text-center">
                      <div className="text-lg font-bold text-gray-700 dark:text-gray-300">{strategy.backtest.winRate}</div>
                      <div className="text-[10px] text-gray-400">胜率·回测</div>
                    </div>
                    <div className="text-center">
                      <div className={`text-lg font-bold ${parseFloat(strategy.backtest.profitFactor) >= 1.0 ? 'text-indigo-600' : 'text-gray-400'}`}>{strategy.backtest.profitFactor}</div>
                      <div className="text-[10px] text-gray-400">盈亏比(PF)</div>
                    </div>
                  </div>
                  <div className="space-y-1 border-t border-gray-200 dark:border-gray-700 pt-2">
                    <div className="flex justify-between text-xs">
                      <span className="text-gray-500">样本数</span>
                      <span className="font-medium text-gray-700 dark:text-gray-300">{strategy.backtest.trades}笔</span>
                    </div>
                    <div className="flex justify-between text-xs">
                      <span className="text-gray-500">平均持仓</span>
                      <span className="font-medium text-gray-700 dark:text-gray-300">{strategy.backtest.avgHold}</span>
                    </div>
                    <div className="flex justify-between text-xs">
                      <span className="text-gray-500">数据范围</span>
                      <span className="font-medium text-gray-700 dark:text-gray-300">{strategy.backtest.period}</span>
                    </div>
                  </div>
                </div>
                {strategy.bestCombo && (
                  <div className="mt-2 p-2 rounded-lg bg-indigo-50 dark:bg-indigo-900/20 border border-indigo-100 dark:border-indigo-800/50">
                    <div className="flex items-center gap-1.5">
                      <span className="text-indigo-500">⭐</span>
                      <span className="text-xs text-indigo-700 dark:text-indigo-400 font-medium">{strategy.bestCombo}</span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── 主页面 ── */
export default function StrategiesPage() {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ trend: true });

  const activeStrategies = strategies.filter((s) => s.status === 'active');
  const archivedStrategies = strategies.filter((s) => s.status === 'archived');

  const toggleExpand = (id: string) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <div className="min-h-screen bg-gray-50/50 dark:bg-gray-950">
      <div className="max-w-5xl mx-auto px-6 py-8">
        {/* Page Header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
              </svg>
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">策略管理</h1>
              <p className="text-sm text-gray-500 dark:text-gray-400">查看系统所有交易策略的评分逻辑、交易参数和回测表现</p>
            </div>
          </div>
        </div>

        {/* Summary Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-4 text-center">
            <div className="text-2xl font-bold text-indigo-600">{strategies.length}</div>
            <div className="text-xs text-gray-500 mt-1">总策略数</div>
          </div>
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-4 text-center">
            <div className="text-2xl font-bold text-emerald-600">{activeStrategies.length}</div>
            <div className="text-xs text-gray-500 mt-1">运行中</div>
          </div>
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-4 text-center">
            <div className="text-2xl font-bold text-gray-400">{archivedStrategies.length}</div>
            <div className="text-xs text-gray-500 mt-1">已归档</div>
          </div>
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-4 text-center">
            <div className="text-2xl font-bold text-red-600">
              {activeStrategies.length > 0 ? activeStrategies.reduce((best, s) => {
                const ret = parseFloat(s.backtest.avgReturn);
                return ret > best ? ret : best;
              }, -999).toFixed(2) + '%' : '-'}
            </div>
            <div className="text-xs text-gray-500 mt-1">最优收益</div>
          </div>
        </div>

        {/* Active Strategies */}
        <div className="mb-6">
          <h2 className="text-sm font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-4 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            活跃策略
          </h2>
          <div className="space-y-4">
            {activeStrategies.map((s) => (
              <StrategyCard key={s.id} strategy={s} isExpanded={!!expanded[s.id]} onToggle={() => toggleExpand(s.id)} />
            ))}
          </div>
        </div>

        {/* Archived Strategies */}
        {archivedStrategies.length > 0 && (
          <div className="mb-6">
            <h2 className="text-sm font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-4 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-gray-400" />
              已归档策略
            </h2>
            <div className="space-y-4">
              {archivedStrategies.map((s) => (
                <StrategyCard key={s.id} strategy={s} isExpanded={!!expanded[s.id]} onToggle={() => toggleExpand(s.id)} />
              ))}
            </div>
          </div>
        )}

        {/* Footer Note */}
        <div className="mt-8 text-center">
          <p className="text-xs text-gray-400 dark:text-gray-500">
            回测数据基于 2561 笔模拟交易 · 2026年4-5月 · 284只港股 · T+1开盘买入 + 策略出场
          </p>
        </div>
      </div>
    </div>
  );
}
