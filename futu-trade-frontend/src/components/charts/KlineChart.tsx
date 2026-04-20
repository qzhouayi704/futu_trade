'use client';

import { useEffect, useRef, useState } from 'react';
import { useTheme } from 'next-themes';
import {
  createChart,
  IChartApi,
  ISeriesApi,
  CandlestickData,
  HistogramData,
  LineData,
} from 'lightweight-charts';
import type { KlineChartProps, RawKlineRow } from '@/types/kline';
import { transformKlineData, transformVolumeData } from './transforms';
import { calculateMultipleMA } from './indicators';
import { getChartOptions, getCandlestickOptions, getMAConfigs } from './theme';

export function KlineChart({
  stockCode,
  period = 'day',
  height = 500,
  showVolume = true,
  showMA = true,
  showTradePoints = false,
  enableRealtime = false,
  className = '',
}: KlineChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const maSeriesRef = useRef<Map<number, ISeriesApi<'Line'>>>(new Map());
  const resizeObserverRef = useRef<ResizeObserver | null>(null);

  const { theme, resolvedTheme } = useTheme();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 获取 K线数据
  const fetchKlineData = async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await fetch(
        `/api/kline/${stockCode}?days=${period === 'week' ? 90 : period === 'month' ? 365 : 30}`
      );

      if (!response.ok) {
        throw new Error('获取K线数据失败');
      }

      const json = await response.json();
      const data: RawKlineRow[] = json.success ? (json.data?.kline_data || []) : [];

      if (!data || data.length === 0) {
        setError('暂无K线数据');
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

    // 转换蜡烛图数据
    const candleData = transformKlineData(rawData);
    candleSeriesRef.current.setData(candleData as CandlestickData[]);

    // 更新成交量
    if (showVolume && volumeSeriesRef.current) {
      const volumeData = transformVolumeData(rawData);
      volumeSeriesRef.current.setData(volumeData as HistogramData[]);
    }

    // 更新 MA 均线
    if (showMA) {
      const maConfigs = getMAConfigs();
      const maData = calculateMultipleMA(
        candleData,
        maConfigs.map((c) => c.period)
      );

      maConfigs.forEach((config) => {
        const series = maSeriesRef.current.get(config.period);
        if (series && maData[config.period]) {
          series.setData(maData[config.period] as LineData[]);
        }
      });
    }
  };

  // 初始化图表
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const currentTheme = (resolvedTheme || theme || 'light') as 'light' | 'dark';
    const chart = createChart(chartContainerRef.current, {
      ...getChartOptions(currentTheme),
      width: chartContainerRef.current.clientWidth,
      height,
    });

    chartRef.current = chart;

    // 创建蜡烛图系列
    const candleSeries = chart.addCandlestickSeries(
      getCandlestickOptions(currentTheme)
    );
    candleSeriesRef.current = candleSeries;

    // 创建成交量系列
    if (showVolume) {
      const volumeSeries = chart.addHistogramSeries({
        priceFormat: {
          type: 'volume',
        },
        priceScaleId: 'volume',
      });
      volumeSeries.priceScale().applyOptions({
        scaleMargins: {
          top: 0.8,
          bottom: 0,
        },
      });
      volumeSeriesRef.current = volumeSeries;
    }

    // 创建 MA 均线系列
    if (showMA) {
      const maConfigs = getMAConfigs();
      maConfigs.forEach((config) => {
        const lineSeries = chart.addLineSeries({
          color: config.color,
          lineWidth: 2,
          title: config.label,
        });
        maSeriesRef.current.set(config.period, lineSeries);
      });
    }

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
      volumeSeriesRef.current = null;
      maSeriesRef.current.clear();
    };
  }, [height, showVolume, showMA]);

  // 监听主题变化
  useEffect(() => {
    if (!chartRef.current) return;

    const currentTheme = (resolvedTheme || theme || 'light') as 'light' | 'dark';
    chartRef.current.applyOptions(getChartOptions(currentTheme));

    if (candleSeriesRef.current) {
      candleSeriesRef.current.applyOptions(getCandlestickOptions(currentTheme));
    }
  }, [theme, resolvedTheme]);

  // 监听股票代码和周期变化
  useEffect(() => {
    if (stockCode) {
      fetchKlineData();
    }
  }, [stockCode, period]);

  // Socket.IO 实时更新（如果启用）
  useEffect(() => {
    if (!enableRealtime || !candleSeriesRef.current) return;

    // TODO: 集成 Socket.IO 实时更新逻辑
    // 监听 quotes_update 事件，更新最后一根蜡烛

    return () => {
      // 清理 Socket.IO 监听器
    };
  }, [enableRealtime, stockCode]);

  if (loading) {
    return (
      <div
        className={`flex items-center justify-center ${className}`}
        style={{ height }}
      >
        <div className="text-gray-500">加载中...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        className={`flex items-center justify-center ${className}`}
        style={{ height }}
      >
        <div className="text-red-500">{error}</div>
      </div>
    );
  }

  return <div ref={chartContainerRef} className={className} />;
}
