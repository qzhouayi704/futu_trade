'use client';

import React, { useMemo } from 'react';
import { ArrowUp, ArrowDown, TrendingUp, TrendingDown } from 'lucide-react';
import { DeltaUpdateData, PocUpdateData, ScalpingSignalData } from '@/types/scalping';
import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts';

interface MetricsPanelProps {
  deltaData: DeltaUpdateData[];
  ofiValue: number | null;
  vwapData: { vwap: number; timestamp: string } | null;
  pocData: PocUpdateData | null;
  signals: ScalpingSignalData[];
}

const QUALITY_COLORS = {
  high: '#f97316', // orange-500
  medium: '#3b82f6', // blue-500
  low: '#6b7280' // gray-500
};

export const MetricsPanel = React.memo(({ deltaData, ofiValue, vwapData, pocData, signals }: MetricsPanelProps) => {
  // 获取当前价格（最新 Delta 数据的 close 价格）
  const currentPrice = useMemo(() => {
    return deltaData.length > 0 ? deltaData[deltaData.length - 1].close : null;
  }, [deltaData]);

  // 当前 Delta 值
  const currentDelta = useMemo(() => {
    return deltaData.length > 0 ? deltaData[deltaData.length - 1].delta : null;
  }, [deltaData]);

  // 计算 Delta 20 周期均值
  const deltaAverage = useMemo(() => {
    if (deltaData.length < 2) return null;
    const recent = deltaData.slice(-20);
    const sum = recent.reduce((acc, d) => acc + Math.abs(d.delta), 0);
    return sum / recent.length;
  }, [deltaData]);

  // VWAP 偏离度
  const vwapDeviation = useMemo(() => {
    if (!vwapData || !currentPrice) return null;
    return ((currentPrice - vwapData.vwap) / vwapData.vwap) * 100;
  }, [vwapData, currentPrice]);

  // POC 距离
  const pocDistance = useMemo(() => {
    if (!pocData || !currentPrice) return null;
    const distance = currentPrice - pocData.poc_price;
    return {
      ticks: Math.abs(distance),
      direction: distance > 0 ? 'above' : 'below'
    };
  }, [pocData, currentPrice]);

  // 信号质量分布
  const qualityDistribution = useMemo(() => {
    const dist = signals.reduce((acc, signal) => {
      const level = signal.quality_level || 'medium';
      acc[level]++;
      return acc;
    }, { high: 0, medium: 0, low: 0 });

    return [
      { name: '高质量', value: dist.high, color: QUALITY_COLORS.high },
      { name: '中等', value: dist.medium, color: QUALITY_COLORS.medium },
      { name: '低质量', value: dist.low, color: QUALITY_COLORS.low }
    ].filter(item => item.value > 0);
  }, [signals]);

  return (
    <div className="space-y-4">
      {/* 当前 Delta */}
      <div className="p-4 rounded-lg bg-gray-800/50 border border-gray-700">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-gray-400">当前 Delta</span>
          {currentDelta !== null && (
            currentDelta > 0 ? (
              <TrendingUp className="w-4 h-4 text-green-500" />
            ) : (
              <TrendingDown className="w-4 h-4 text-red-500" />
            )
          )}
        </div>
        {currentDelta !== null ? (
          <>
            <div className={`text-2xl font-bold ${currentDelta > 0 ? 'text-green-500' : 'text-red-500'}`}>
              {currentDelta.toFixed(0)}
            </div>
            {deltaAverage !== null && (
              <div className="mt-2 text-xs text-gray-500">
                20周期均值: {deltaAverage.toFixed(0)}
              </div>
            )}
            {/* Delta 柱状图 */}
            <div className="mt-2 h-2 bg-gray-700 rounded-full overflow-hidden">
              <div
                className={`h-full ${currentDelta > 0 ? 'bg-green-500' : 'bg-red-500'}`}
                style={{
                  width: deltaAverage ? `${Math.min(Math.abs(currentDelta) / (deltaAverage * 2) * 100, 100)}%` : '50%'
                }}
              />
            </div>
          </>
        ) : (
          <div className="text-gray-500">暂无数据</div>
        )}
      </div>

      {/* 当前 OFI */}
      <div className="p-4 rounded-lg bg-gray-800/50 border border-gray-700">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-gray-400">当前 OFI</span>
          {ofiValue !== null && (
            ofiValue > 0 ? (
              <ArrowUp className="w-4 h-4 text-green-500" />
            ) : (
              <ArrowDown className="w-4 h-4 text-red-500" />
            )
          )}
        </div>
        {ofiValue !== null ? (
          <div className={`text-2xl font-bold ${ofiValue > 0 ? 'text-green-500' : 'text-red-500'}`}>
            {ofiValue.toFixed(2)}
          </div>
        ) : (
          <div className="text-gray-500">暂无数据</div>
        )}
      </div>

      {/* VWAP 偏离度 */}
      <div className="p-4 rounded-lg bg-gray-800/50 border border-gray-700">
        <span className="text-sm text-gray-400">VWAP 偏离度</span>
        {vwapDeviation !== null ? (
          <>
            <div className={`text-2xl font-bold mt-2 ${Math.abs(vwapDeviation) > 2 ? 'text-red-500' : 'text-gray-300'}`}>
              {vwapDeviation > 0 ? '+' : ''}{vwapDeviation.toFixed(2)}%
            </div>
            {/* 进度条 */}
            <div className="mt-2 h-2 bg-gray-700 rounded-full overflow-hidden">
              <div
                className={`h-full ${Math.abs(vwapDeviation) > 2 ? 'bg-red-500' : 'bg-blue-500'}`}
                style={{
                  width: `${Math.min(Math.abs(vwapDeviation) * 20, 100)}%`
                }}
              />
            </div>
            {Math.abs(vwapDeviation) > 2 && (
              <div className="mt-1 text-xs text-red-500">⚠️ 偏离过大</div>
            )}
          </>
        ) : (
          <div className="text-gray-500 mt-2">暂无数据</div>
        )}
      </div>

      {/* POC 距离 */}
      <div className="p-4 rounded-lg bg-gray-800/50 border border-gray-700">
        <span className="text-sm text-gray-400">POC 距离</span>
        {pocDistance !== null ? (
          <>
            <div className="text-2xl font-bold mt-2 text-gray-300">
              {pocDistance.ticks.toFixed(2)} Tick
            </div>
            <div className="mt-1 text-xs text-gray-500">
              {pocDistance.direction === 'above' ? '价格在 POC 上方' : '价格在 POC 下方'}
            </div>
          </>
        ) : (
          <div className="text-gray-500 mt-2">暂无数据</div>
        )}
      </div>

      {/* 信号质量分布饼图 */}
      {qualityDistribution.length > 0 && (
        <div className="p-4 rounded-lg bg-gray-800/50 border border-gray-700">
          <span className="text-sm text-gray-400 mb-2 block">信号质量分布</span>
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie
                data={qualityDistribution}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) => `${name} ${((percent || 0) * 100).toFixed(0)}%`}
                outerRadius={60}
                fill="#8884d8"
                dataKey="value"
              >
                {qualityDistribution.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
});

MetricsPanel.displayName = 'MetricsPanel';