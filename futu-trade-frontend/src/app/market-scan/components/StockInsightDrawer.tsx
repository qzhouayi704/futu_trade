'use client';

import React, { useEffect, useState } from 'react';
import {
  StockInsightResult,
  StockNewsResult,
  StockTag,
  KeyLevels,
  analyzeStock,
  searchStockNews,
  Signal,
  Scenario,
} from '@/lib/api/stock-insight';

interface StockInsightDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  stockCode: string;
  stockName: string;
  quickScanResult?: Record<string, unknown>;
  flowSignals?: Record<string, unknown>[];
}

export function StockInsightDrawer({
  isOpen,
  onClose,
  stockCode,
  stockName,
  quickScanResult,
  flowSignals,
}: StockInsightDrawerProps) {
  const [insight, setInsight] = useState<StockInsightResult | null>(null);
  const [news, setNews] = useState<StockNewsResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [newsLoading, setNewsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen && stockCode) {
      loadData();
    } else {
      setInsight(null);
      setNews(null);
      setError(null);
    }
  }, [isOpen, stockCode]);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await analyzeStock(stockCode, quickScanResult, flowSignals);
      setInsight(result);
    } catch (err) {
      console.error('加载分析失败:', err);
      setError('分析服务不可用');
    } finally {
      setLoading(false);
    }

    // 异步加载消息面
    setNewsLoading(true);
    try {
      const newsResult = await searchStockNews(stockCode, stockName);
      setNews(newsResult);
    } catch (err) {
      console.error('消息面加载失败:', err);
    } finally {
      setNewsLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <>
      {/* 遮罩 */}
      <div
        className="fixed inset-0 bg-black/40 z-40 transition-opacity"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="fixed top-0 right-0 h-full w-[480px] bg-[#0f1419] border-l border-gray-700/50 z-50 overflow-y-auto shadow-2xl animate-slide-in-right">
        {/* 头部 */}
        <div className="sticky top-0 z-10 bg-[#0f1419]/95 backdrop-blur-md border-b border-gray-700/50 px-5 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                {stockName}
                <span className="text-sm font-normal text-gray-400">{stockCode}</span>
              </h2>
              {insight && (
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-lg">{insight.verdict.emoji}</span>
                  <span className="text-sm font-medium" style={{
                    color: insight.verdict.sentiment.includes('多') ? '#22c55e' :
                      insight.verdict.sentiment.includes('空') ? '#ef4444' : '#eab308'
                  }}>
                    {insight.verdict.sentiment}
                  </span>
                </div>
              )}
            </div>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-full bg-gray-800 hover:bg-gray-700 flex items-center justify-center text-gray-400 hover:text-white transition-colors"
            >
              ✕
            </button>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center h-64">
            <div className="text-gray-400 flex flex-col items-center gap-3">
              <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              <span className="text-sm">分析中...</span>
            </div>
          </div>
        ) : error ? (
          <div className="p-5 text-center text-red-400">{error}</div>
        ) : insight ? (
          <div className="p-5 space-y-4">
            <VerdictSection verdict={insight.verdict} />
            {(insight.stock_tag || insight.key_levels) && (
              <BattlePanelSection
                stockTag={insight.stock_tag}
                keyLevels={insight.key_levels}
              />
            )}
            <ScenarioSection scenarios={insight.verdict.scenarios} />
            <CapitalFlowSection capitalFlow={insight.capital_flow} capitalScore={insight.capital_score} />
            <ActivitySection activity={insight.activity} klinePattern={insight.kline_pattern} />
            <SignalsSection signals={insight.signals} verdict={insight.verdict} />
            <NewsSection news={news} loading={newsLoading} />
          </div>
        ) : null}
      </div>

      <style jsx>{`
        @keyframes slideInRight {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
        .animate-slide-in-right {
          animation: slideInRight 0.25s ease-out;
        }
      `}</style>
    </>
  );
}

// ==================== 子组件 ====================

/** ① 综合判定 */
function VerdictSection({ verdict }: { verdict: StockInsightResult['verdict'] }) {
  return (
    <div className="bg-gray-800/60 rounded-xl p-4 border border-gray-700/40">
      <div className="text-sm text-gray-300">{verdict.text}</div>
    </div>
  );
}

/** ② 情景预判 */
function ScenarioSection({ scenarios }: { scenarios: Scenario[] }) {
  const colors: Record<string, string> = {
    bullish: '#22c55e',
    bearish: '#ef4444',
    neutral: '#eab308',
  };

  return (
    <div className="bg-gray-800/60 rounded-xl p-4 border border-gray-700/40">
      <h3 className="text-xs font-medium text-gray-400 mb-3 uppercase tracking-wider">情景预判</h3>
      <div className="space-y-2">
        {scenarios.map((s) => (
          <div key={s.name} className="flex items-center gap-3">
            <span className="text-xs text-gray-300 w-16 shrink-0">{s.name}</span>
            <div className="flex-1 h-5 bg-gray-700/50 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${s.probability}%`,
                  backgroundColor: colors[s.type] || '#6b7280',
                }}
              />
            </div>
            <span className="text-xs font-medium text-gray-300 w-8 text-right">{s.probability}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** ③ 资金流时间线 */
function CapitalFlowSection({ capitalFlow, capitalScore }: {
  capitalFlow: StockInsightResult['capital_flow'];
  capitalScore: StockInsightResult['capital_score'];
}) {
  const timeline = capitalFlow.timeline;
  const maxVal = Math.max(...timeline.map(t => Math.abs(t.net_inflow)), 1);

  const formatAmount = (v: number) => {
    const abs = Math.abs(v);
    if (abs >= 1e8) return (v / 1e8).toFixed(1) + '亿';
    if (abs >= 1e4) return (v / 1e4).toFixed(0) + '万';
    return v.toFixed(0);
  };

  return (
    <div className="bg-gray-800/60 rounded-xl p-4 border border-gray-700/40">
      <h3 className="text-xs font-medium text-gray-400 mb-3 uppercase tracking-wider">
        资金流 · 近{timeline.length}天
      </h3>

      {timeline.length > 0 ? (
        <>
          {/* 柱状图 */}
          <div className="flex items-end gap-1 h-16 mb-3">
            {timeline.map((t, i) => {
              const h = Math.abs(t.net_inflow) / maxVal * 100;
              const isPositive = t.net_inflow >= 0;
              return (
                <div key={i} className="flex-1 flex flex-col items-center justify-end h-full">
                  <div
                    className="w-full rounded-t transition-all"
                    style={{
                      height: `${Math.max(h, 4)}%`,
                      backgroundColor: isPositive ? '#22c55e' : '#ef4444',
                      opacity: 0.7 + (i / timeline.length) * 0.3,
                    }}
                    title={`${t.date}: ${formatAmount(t.net_inflow)}`}
                  />
                  <span className="text-[9px] text-gray-500 mt-1">{t.date.slice(-2)}</span>
                </div>
              );
            })}
          </div>

          {/* 统计 */}
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="flex justify-between text-gray-400">
              <span>连续流入</span>
              <span className="text-gray-200">{capitalFlow.continuity_days}天</span>
            </div>
            <div className="flex justify-between text-gray-400">
              <span>资金评分</span>
              <span className="text-gray-200">{capitalScore.score.toFixed(0)}分</span>
            </div>
            <div className="flex justify-between text-gray-400">
              <span>大单买入比</span>
              <span className="text-gray-200">{(capitalScore.big_order_ratio * 100).toFixed(1)}%</span>
            </div>
            <div className="flex justify-between text-gray-400">
              <span>主力净流入</span>
              <span style={{ color: capitalScore.main_net_inflow >= 0 ? '#22c55e' : '#ef4444' }}>
                {formatAmount(capitalScore.main_net_inflow)}
              </span>
            </div>
          </div>
        </>
      ) : (
        <div className="text-xs text-gray-500 text-center py-4">暂无资金流数据</div>
      )}

      <div className="mt-2 text-xs text-gray-400">
        趋势: <span className="text-gray-200">{capitalFlow.trend_text}</span>
      </div>
    </div>
  );
}

/** ④ 活跃度趋势 + K线形态 */
function ActivitySection({ activity, klinePattern }: {
  activity: StockInsightResult['activity'];
  klinePattern: StockInsightResult['kline_pattern'];
}) {
  return (
    <div className="bg-gray-800/60 rounded-xl p-4 border border-gray-700/40">
      <h3 className="text-xs font-medium text-gray-400 mb-3 uppercase tracking-wider">活跃度 & K线</h3>

      {/* 活跃度 */}
      {activity.length > 0 ? (
        <div className="flex items-center gap-2 text-xs mb-3">
          {activity.map((a, i) => (
            <React.Fragment key={i}>
              {i > 0 && <span className="text-gray-600">→</span>}
              <span className="text-gray-400">{a.date}</span>
              <span className={`font-medium ${a.turnover_rate >= 20 ? 'text-orange-400' : 'text-gray-200'}`}>
                {a.turnover_rate.toFixed(1)}%
                {a.turnover_rate >= 30 && ' 🔥'}
              </span>
            </React.Fragment>
          ))}
        </div>
      ) : (
        <div className="text-xs text-gray-500 mb-3">暂无活跃度数据</div>
      )}

      {/* K线形态 */}
      {klinePattern.pattern_name !== '无数据' && (
        <div className="flex items-center gap-3 text-xs pt-3 border-t border-gray-700/30">
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
            klinePattern.type === '阳线' ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'
          }`}>
            {klinePattern.type === '阳线' ? '收涨' : '收跌'}
          </span>
          {klinePattern.upper_shadow_ratio >= 30 && (
            <span className="text-yellow-400">
              冲高回落{klinePattern.upper_shadow_ratio}%
              {klinePattern.upper_shadow_ratio >= 50 && ' ⚠️'}
            </span>
          )}
          {klinePattern.lower_shadow_ratio >= 30 && (
            <span className="text-green-400">
              探底回升{klinePattern.lower_shadow_ratio}%
            </span>
          )}
          <span className="text-gray-300 font-medium">{klinePattern.pattern_name}</span>
        </div>
      )}
    </div>
  );
}

/** ⑤ 多空信号汇总 */
function SignalsSection({ signals, verdict }: {
  signals: StockInsightResult['signals'];
  verdict: StockInsightResult['verdict'];
}) {
  return (
    <div className="bg-gray-800/60 rounded-xl p-4 border border-gray-700/40">
      <h3 className="text-xs font-medium text-gray-400 mb-3 uppercase tracking-wider">多空信号汇总</h3>

      {/* 看多 */}
      {signals.bullish.length > 0 && (
        <div className="mb-3">
          <div className="text-xs font-medium text-green-400 mb-2">
            ✅ 看多信号 ({signals.bullish_count})
          </div>
          <div className="space-y-2">
            {signals.bullish.map((sig, i) => (
              <SignalItem key={i} signal={sig} type="bullish" />
            ))}
          </div>
        </div>
      )}

      {/* 看空 */}
      {signals.bearish.length > 0 && (
        <div className="mb-3">
          <div className="text-xs font-medium text-red-400 mb-2">
            ❌ 看空信号 ({signals.bearish_count})
          </div>
          <div className="space-y-2">
            {signals.bearish.map((sig, i) => (
              <SignalItem key={i} signal={sig} type="bearish" />
            ))}
          </div>
        </div>
      )}

      {signals.bullish.length === 0 && signals.bearish.length === 0 && (
        <div className="text-xs text-gray-500 text-center py-2">暂无信号</div>
      )}

      {/* 综合得分 */}
      <div className="mt-3 pt-3 border-t border-gray-700/30 flex items-center justify-between text-xs">
        <span className="text-gray-400">综合得分</span>
        <div className="flex items-center gap-3">
          <span className="text-green-400 font-medium">看多 {verdict.bullish_score}</span>
          <span className="text-gray-600">vs</span>
          <span className="text-red-400 font-medium">看空 {verdict.bearish_score}</span>
        </div>
      </div>
    </div>
  );
}

function SignalItem({ signal, type }: { signal: Signal; type: 'bullish' | 'bearish' }) {
  return (
    <div className="flex items-start gap-2 text-xs">
      <span className={type === 'bullish' ? 'text-green-500' : 'text-red-500'}>
        {type === 'bullish' ? '✅' : '❌'}
      </span>
      <div className="flex-1 min-w-0">
        <div className="font-medium text-gray-200">{signal.label}</div>
        {signal.reason && (
          <div className="text-gray-500 mt-0.5 truncate">{signal.reason}</div>
        )}
        {signal.detail && (
          <div className="text-gray-500 mt-0.5">{signal.detail}</div>
        )}
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-gray-600 text-[10px]">{signal.source}</span>
          {signal.confidence && (
            <span className="text-gray-600 text-[10px]">置信度 {(signal.confidence * 100).toFixed(0)}%</span>
          )}
        </div>
      </div>
    </div>
  );
}

/** ⑥ 消息面 */
function NewsSection({ news, loading }: { news: StockNewsResult | null; loading: boolean }) {
  return (
    <div className="bg-gray-800/60 rounded-xl p-4 border border-gray-700/40">
      <h3 className="text-xs font-medium text-gray-400 mb-3 uppercase tracking-wider flex items-center gap-2">
        📰 消息面
        {loading && (
          <span className="flex items-center gap-1 text-blue-400">
            <div className="w-3 h-3 border border-blue-500 border-t-transparent rounded-full animate-spin" />
            搜索中...
          </span>
        )}
      </h3>

      {loading && !news && (
        <div className="text-xs text-gray-500 text-center py-4">
          Gemini 正在搜索最新消息...（约7秒）
        </div>
      )}

      {news && news.error && (
        <div className="text-xs text-yellow-500 text-center py-2">
          ⚠ {news.error}
        </div>
      )}

      {news && news.news.length > 0 && (
        <div className="space-y-3">
          {news.news.slice(0, 5).map((item, i) => (
            <div key={i} className="text-xs">
              <div className="flex items-start gap-1.5">
                <span>{
                  item.sentiment === 'positive' ? '🟢' :
                    item.sentiment === 'negative' ? '🔴' : '⚪'
                }</span>
                <div className="flex-1">
                  <div className="text-gray-200 font-medium">{item.title}</div>
                  <div className="text-gray-500 mt-0.5">{item.summary}</div>
                  <div className="text-gray-600 mt-0.5">{item.date}</div>
                </div>
              </div>
            </div>
          ))}

          {/* 催化剂 & 风险 */}
          {(news.key_catalysts.length > 0 || news.risk_factors.length > 0) && (
            <div className="grid grid-cols-2 gap-3 pt-2 border-t border-gray-700/30">
              {news.key_catalysts.length > 0 && (
                <div>
                  <div className="text-[10px] text-green-400 font-medium mb-1">催化剂</div>
                  {news.key_catalysts.map((c, i) => (
                    <div key={i} className="text-[10px] text-gray-400 truncate">• {c}</div>
                  ))}
                </div>
              )}
              {news.risk_factors.length > 0 && (
                <div>
                  <div className="text-[10px] text-red-400 font-medium mb-1">风险</div>
                  {news.risk_factors.map((r, i) => (
                    <div key={i} className="text-[10px] text-gray-400 truncate">• {r}</div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {news && !news.error && news.news.length === 0 && !loading && (
        <div className="text-xs text-gray-500 text-center py-2">暂无近期消息</div>
      )}
    </div>
  );
}

/** ①b 作战面板（标签 + 关键价位 + VWAP 偏离阈值 + 策略参数） */
function BattlePanelSection({ stockTag, keyLevels }: { stockTag?: StockTag; keyLevels?: KeyLevels }) {
  const tagStyles: Record<string, { bg: string; text: string; icon: string }> = {
    '锁仓控盘': { bg: 'bg-red-900/40', text: 'text-red-400', icon: '🔒' },
    '暴量拉升': { bg: 'bg-orange-900/40', text: 'text-orange-400', icon: '🚀' },
    '仙股炒作': { bg: 'bg-purple-900/40', text: 'text-purple-400', icon: '💀' },
    '明星高波动': { bg: 'bg-sky-900/40', text: 'text-sky-400', icon: '⭐' },
    '正常': { bg: 'bg-gray-800/40', text: 'text-gray-400', icon: '✅' },
  };

  const stopLossPct: Record<string, string> = {
    '锁仓控盘': '-10%', '暴量拉升': '-8%', '仙股炒作': '-15%',
    '明星高波动': '-8%', '正常': '-5%',
  };
  const takeProfitPct: Record<string, string> = {
    '锁仓控盘': '+15%', '暴量拉升': '+10%', '仙股炒作': '+20%',
    '明星高波动': '+12%', '正常': '+8%',
  };
  const maxPosPct: Record<string, string> = {
    '锁仓控盘': '50%', '暴量拉升': '30%', '仙股炒作': '20%',
    '明星高波动': '80%', '正常': '100%',
  };
  const entryRules: Record<string, string> = {
    '锁仓控盘': '必须放量突破', '暴量拉升': '仅在回撤位进场',
    '仙股炒作': '仅在回撤位进场', '明星高波动': '标准信号', '正常': '标准信号',
  };

  const label = stockTag?.label || '正常';
  const style = tagStyles[label] || tagStyles['正常'];
  const fmt = (v: number) => v > 0 ? v.toFixed(3) : '-';

  return (
    <div className={`rounded-xl p-4 border border-gray-700/40 ${style.bg}`}>
      {/* 标签头 */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider">作战面板</h3>
        <div className="flex items-center gap-2">
          <span className={`px-2 py-0.5 rounded text-xs font-bold ${style.text}`}>
            {style.icon} {label}
          </span>
          {stockTag?.phase && (
            <span className="px-2 py-0.5 rounded text-[10px] bg-gray-700/50 text-gray-300">
              {stockTag.phase}
            </span>
          )}
        </div>
      </div>

      {/* 风险提示 */}
      {stockTag?.risk_note && (
        <div className="text-[11px] text-yellow-400/80 mb-3 flex items-start gap-1">
          <span>⚠️</span>
          <span>{stockTag.risk_note}</span>
        </div>
      )}

      {/* 关键价位 */}
      {keyLevels && keyLevels.prev_close > 0 && (
        <div className="mb-3">
          <div className="text-[10px] text-gray-500 mb-2">📊 关键价位</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-gray-500">阻力位 (5日高)</span>
              <span className="text-red-400 font-mono">{fmt(keyLevels.resistance_5d)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">前日高</span>
              <span className="text-gray-300 font-mono">{fmt(keyLevels.prev_high)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">前日收</span>
              <span className="text-gray-300 font-mono">{fmt(keyLevels.prev_close)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">前日低</span>
              <span className="text-gray-300 font-mono">{fmt(keyLevels.prev_low)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">支撑位 (5日低)</span>
              <span className="text-green-400 font-mono">{fmt(keyLevels.support_5d)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">止损位</span>
              <span className="text-red-500 font-mono">{fmt(keyLevels.stop_loss)}</span>
            </div>
          </div>

          {/* Fibonacci */}
          {keyLevels.fib_382 > 0 && (
            <div className="mt-2 pt-2 border-t border-gray-700/30">
              <div className="text-[10px] text-gray-500 mb-1">Fibonacci 回撤</div>
              <div className="flex gap-3 text-xs">
                <span className="text-gray-400">38.2% <span className="text-gray-300 font-mono">{fmt(keyLevels.fib_382)}</span></span>
                <span className="text-gray-400">50% <span className="text-gray-300 font-mono">{fmt(keyLevels.fib_500)}</span></span>
                <span className="text-gray-400">61.8% <span className="text-gray-300 font-mono">{fmt(keyLevels.fib_618)}</span></span>
              </div>
            </div>
          )}

          {/* 买入区间 */}
          {keyLevels.buy_zone_low > 0 && (
            <div className="mt-2 pt-2 border-t border-gray-700/30 flex items-center gap-2 text-xs">
              <span className="text-green-400">🎯 买入区间</span>
              <span className="text-green-300 font-mono">{fmt(keyLevels.buy_zone_low)} ~ {fmt(keyLevels.buy_zone_high)}</span>
            </div>
          )}
        </div>
      )}

      {/* VWAP 偏离度阈值 */}
      {keyLevels && (
        <div className="mb-3">
          <div className="text-[10px] text-gray-500 mb-2">📈 VWAP 偏离度信号</div>
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div className="bg-green-900/30 rounded px-2 py-1.5 text-center">
              <div className="text-[10px] text-green-500">回踩买点</div>
              <div className="text-green-300 font-mono font-medium">{keyLevels.vwap_buy_near}%</div>
            </div>
            <div className="bg-blue-900/30 rounded px-2 py-1.5 text-center">
              <div className="text-[10px] text-blue-500">超卖买点</div>
              <div className="text-blue-300 font-mono font-medium">{keyLevels.vwap_buy_far}%</div>
            </div>
            <div className="bg-red-900/30 rounded px-2 py-1.5 text-center">
              <div className="text-[10px] text-red-500">卖出区</div>
              <div className="text-red-300 font-mono font-medium">+{keyLevels.vwap_sell}%</div>
            </div>
          </div>
        </div>
      )}

      {/* 策略参数 */}
      <div className="pt-2 border-t border-gray-700/30">
        <div className="text-[10px] text-gray-500 mb-2">⚙️ 策略参数</div>
        <div className="flex items-center gap-4 text-xs">
          <span className="text-gray-400">止损 <span className="text-red-400 font-medium">{stopLossPct[label]}</span></span>
          <span className="text-gray-400">止盈 <span className="text-green-400 font-medium">{takeProfitPct[label]}</span></span>
          <span className="text-gray-400">仓位上限 <span className="text-gray-200 font-medium">{maxPosPct[label]}</span></span>
        </div>
        <div className="mt-1 text-[10px] text-gray-500">
          入场规则: <span className="text-gray-300">{entryRules[label]}</span>
        </div>
      </div>
    </div>
  );
}
