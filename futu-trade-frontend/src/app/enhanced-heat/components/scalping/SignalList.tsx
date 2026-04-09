'use client';

import React, { useMemo } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { zhCN } from 'date-fns/locale';
import { ChevronDown, ChevronUp, Star } from 'lucide-react';
import { ScalpingSignalData, StopLossAlertData } from '@/types/scalping';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';

interface SignalListProps {
  signals: ScalpingSignalData[];
  stopLossAlerts: StopLossAlertData[];
}

const qualityConfig = {
  high: { icon: '🔥', label: '高质量', color: 'text-orange-500', bgColor: 'bg-orange-500/10', borderColor: 'border-orange-500' },
  medium: { icon: '⚡', label: '中等', color: 'text-blue-500', bgColor: 'bg-blue-500/10', borderColor: 'border-blue-500' },
  low: { icon: '⚠️', label: '低质量', color: 'text-gray-500', bgColor: 'bg-gray-500/10', borderColor: 'border-gray-500' }
};

const signalTypeConfig = {
  breakout_long: { label: '突破追多', color: 'text-green-500', bgColor: 'bg-green-500/10', borderColor: 'border-green-500' },
  support_long: { label: '支撑低吸', color: 'text-yellow-500', bgColor: 'bg-yellow-500/10', borderColor: 'border-yellow-500' }
};

const getStarRating = (score: number): number => {
  return Math.round((score / 10) * 5);
};

export const SignalList = React.memo(({ signals, stopLossAlerts }: SignalListProps) => {
  // 合并信号和止损提示，按时间倒序排列
  const allItems = useMemo(() => {
    const signalItems = signals.map(s => ({ type: 'signal' as const, data: s, timestamp: s.timestamp }));
    const alertItems = stopLossAlerts.map(a => ({ type: 'alert' as const, data: a, timestamp: a.timestamp }));
    return [...signalItems, ...alertItems].sort((a, b) =>
      new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
    );
  }, [signals, stopLossAlerts]);

  if (allItems.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        <p>暂无信号</p>
      </div>
    );
  }

  return (
    <div className="space-y-2 overflow-y-auto max-h-[600px] pr-2">
      {allItems.map((item, index) => {
        if (item.type === 'alert') {
          // 止损提示卡片
          const alert = item.data;
          const stopLossConfig = {
            breakout_stop: { label: '突破回落止损' },
            support_stop: { label: '支撑破位止损' }
          };
          const config = stopLossConfig[alert.signal_type];

          return (
            <div
              key={`alert-${index}`}
              className="p-3 rounded-lg border bg-red-500/10 border-red-500 animate-pulse"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-red-500 text-lg">🔴</span>
                  <span className="font-medium text-red-500">{config.label}</span>
                </div>
                <span className="text-xs text-gray-500">
                  {formatDistanceToNow(new Date(alert.timestamp), { addSuffix: true, locale: zhCN })}
                </span>
              </div>
              <div className="mt-2 text-sm">
                <p className="text-gray-300">当前价格: {alert.current_price.toFixed(2)}</p>
                <p className="text-gray-400 mt-1">
                  入场价格: {alert.entry_price.toFixed(2)} | 回撤: -{alert.drawdown_percent.toFixed(1)}%
                </p>
              </div>
            </div>
          );
        }

        // 交易信号卡片
        const signal = item.data as ScalpingSignalData;
        const signalType = signalTypeConfig[signal.signal_type];
        const quality = qualityConfig[signal.quality_level || 'medium'];
        const starRating = signal.score ? getStarRating(signal.score) : 0;

        return (
          <div
            key={`signal-${index}`}
            className={`p-3 rounded-lg border ${signalType.bgColor} ${signalType.borderColor}`}
          >
            {/* 信号头部 */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className={`font-medium ${signalType.color}`}>{signalType.label}</span>
                {signal.quality_level && (
                  <span className={`text-xs px-2 py-1 rounded ${quality.bgColor} ${quality.color}`}>
                    {quality.icon} {quality.label}
                  </span>
                )}
              </div>
              <span className="text-xs text-gray-500">
                {formatDistanceToNow(new Date(signal.timestamp), { addSuffix: true, locale: zhCN })}
              </span>
            </div>

            {/* 触发价格和评分 */}
            <div className="mt-2 flex items-center justify-between">
              <div>
                <span className="text-sm text-gray-400">触发价格: </span>
                <span className="text-lg font-semibold">{signal.trigger_price.toFixed(2)}</span>
                {signal.support_price && (
                  <span className="text-sm text-gray-400 ml-2">
                    (支撑: {signal.support_price.toFixed(2)})
                  </span>
                )}
              </div>
              {signal.score !== undefined && (
                <div className="flex items-center gap-1">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Star
                      key={i}
                      className={`w-4 h-4 ${i < starRating ? 'fill-yellow-500 text-yellow-500' : 'text-gray-600'}`}
                    />
                  ))}
                  <span className="text-xs text-gray-400 ml-1">({signal.score}/10)</span>
                </div>
              )}
            </div>

            {/* 可折叠详情 */}
            <Accordion type="single" collapsible className="mt-2">
              <AccordionItem value="details" className="border-none">
                <AccordionTrigger className="py-2 text-xs text-gray-400 hover:text-gray-300">
                  查看详情
                </AccordionTrigger>
                <AccordionContent className="space-y-2">
                  {/* 触发条件 */}
                  {signal.conditions && signal.conditions.length > 0 && (
                    <div>
                      <p className="text-xs font-medium text-gray-400 mb-1">触发条件:</p>
                      <ul className="space-y-1">
                        {signal.conditions.map((condition, i) => (
                          <li key={i} className="text-xs text-gray-300 flex items-start gap-1">
                            <span className="text-green-500">✅</span>
                            <span>{condition}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* 评分组成 */}
                  {signal.score_components && (
                    <div>
                      <p className="text-xs font-medium text-gray-400 mb-1">评分组成:</p>
                      <div className="grid grid-cols-2 gap-2">
                        <div className="text-xs">
                          <span className="text-gray-400">Delta: </span>
                          <span className="text-gray-300">{signal.score_components.delta_score}/10</span>
                        </div>
                        <div className="text-xs">
                          <span className="text-gray-400">OFI: </span>
                          <span className="text-gray-300">{signal.score_components.ofi_score}/10</span>
                        </div>
                        <div className="text-xs">
                          <span className="text-gray-400">加速度: </span>
                          <span className="text-gray-300">{signal.score_components.acceleration_score}/10</span>
                        </div>
                        <div className="text-xs">
                          <span className="text-gray-400">VWAP: </span>
                          <span className="text-gray-300">{signal.score_components.vwap_deviation_score}/10</span>
                        </div>
                        <div className="text-xs">
                          <span className="text-gray-400">POC: </span>
                          <span className="text-gray-300">{signal.score_components.poc_distance_score}/10</span>
                        </div>
                      </div>
                    </div>
                  )}
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          </div>
        );
      })}
    </div>
  );
});

SignalList.displayName = 'SignalList';
