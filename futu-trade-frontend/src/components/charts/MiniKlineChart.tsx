'use client';

import { useEffect, useRef, useState } from 'react';
import { useTheme } from 'next-themes';
import {
  createChart,
  IChartApi,
  ISeriesApi,
  CandlestickData,
} from 'lightweight-charts';
import type { MiniKlineChartProps, RawKlineRow } from '@/types/kline';
import { transformKlineData } from './transforms';
import { getChartOptions, getCandlestickOptions } from './theme';

export function MiniKlineChart({
  stockCode,
  height = 200,
  className = '',
}: MiniKlineChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);

  const { theme, resolvedTheme } = useTheme();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 获取 K线数据（最近30天）
  const fetchKlineData = async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await fetch(
        `/api/stocks/kline/${stockCode}?days=30`
      );

      if (!response.ok) {
        throw new Error('获取K线数据失败');
      }

      const json = await response.json();
      const data: RawKlineRow[] = json.success ? (json.data?.kline_data || []) : [];

      if (!data || data.length === 0) {
        setError('暂无数据');
        return;
      }

      updateChartData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '未知错误');
    } finally {
      setLoading(false);
    }
  };

  // 更新图表数据
  const updateChartData = (rawData: RawKlineRow[]) => {
    if (!candleSeriesRef.current) return;

    const candleData = transformKlineData(rawData);
    candleSeriesRef.current.setData(candleData as CandlestickData[]);
  };

  // 初始化图表
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const currentTheme = (resolvedTheme || theme || 'light') as 'light' | 'dark';
    const chart = createChart(chartContainerRef.current, {
      ...getChartOptions(currentTheme),
      width: chartContainerRef.current.clientWidth,
      height,
      // 迷你图表简化配置
      rightPriceScale: {
        visible: false,
      },
      timeScale: {
        visible: false,
      },
      crosshair: {
        mode: 0, // CrosshairMode.Hidden
      },
    });

    chartRef.current = chart;

    // 创建蜡烛图系列
    const candleSeries = chart.addCandlestickSeries(
      getCandlestickOptions(currentTheme)
    );
    candleSeriesRef.current = candleSeries;

    // 响应式宽度调整
    const resizeObserver = new ResizeObserver((entries) => {
      if (entries.length === 0 || !chartRef.current) return;
      const { width } = entries[0].contentRect;
      chartRef.current.applyOptions({ width });
    });

    resizeObserver.observe(chartContainerRef.current);
    resizeObserverRef.current = resizeObserver;

    // 清理函数
    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
    };
  }, [height]);

  // 监听主题变化
  useEffect(() => {
    if (!chartRef.current) return;

    const currentTheme = (resolvedTheme || theme || 'light') as 'light' | 'dark';
    chartRef.current.applyOptions(getChartOptions(currentTheme));

    if (candleSeriesRef.current) {
      candleSeriesRef.current.applyOptions(getCandlestickOptions(currentTheme));
    }
  }, [theme, resolvedTheme]);

  // 监听股票代码变化
  useEffect(() => {
    if (stockCode) {
      fetchKlineData();
    }
  }, [stockCode]);

  if (loading) {
    return (
      <div
        className={`flex items-center justify-center ${className}`}
        style={{ height }}
      >
        <div className="text-xs text-gray-500">加载中...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        className={`flex items-center justify-center ${className}`}
        style={{ height }}
      >
        <div className="text-xs text-red-500">{error}</div>
      </div>
    );
  }

  return <div ref={chartContainerRef} className={className} />;
}
