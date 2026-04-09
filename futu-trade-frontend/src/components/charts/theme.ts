import type { DeepPartial, ChartOptions, CandlestickSeriesOptions } from 'lightweight-charts';

/**
 * 根据主题返回 LWC ChartOptions
 */
export function getChartOptions(theme: 'light' | 'dark'): DeepPartial<ChartOptions> {
  const isDark = theme === 'dark';

  return {
    layout: {
      background: {
        color: isDark ? '#1a1a2e' : '#ffffff',
      },
      textColor: isDark ? '#d1d5db' : '#191919',
    },
    grid: {
      vertLines: {
        color: isDark ? '#2d2d44' : '#e0e0e0',
      },
      horzLines: {
        color: isDark ? '#2d2d44' : '#e0e0e0',
      },
    },
    crosshair: {
      mode: 1, // CrosshairMode.Normal
    },
    rightPriceScale: {
      borderColor: isDark ? '#2d2d44' : '#e0e0e0',
    },
    timeScale: {
      borderColor: isDark ? '#2d2d44' : '#e0e0e0',
      timeVisible: true,
      secondsVisible: false,
    },
  };
}

/**
 * 根据主题返回蜡烛图系列配置
 */
export function getCandlestickOptions(
  theme: 'light' | 'dark'
): DeepPartial<CandlestickSeriesOptions> {
  return {
    upColor: '#ef4444',      // 涨红
    downColor: '#22c55e',    // 跌绿
    borderUpColor: '#ef4444',
    borderDownColor: '#22c55e',
    wickUpColor: '#ef4444',
    wickDownColor: '#22c55e',
  };
}

/**
 * MA 均线颜色配置
 */
export const MA_COLORS = {
  5: '#eab308',   // 黄色 MA5
  10: '#3b82f6',  // 蓝色 MA10
  20: '#a855f7',  // 紫色 MA20
  60: '#22c55e',  // 绿色 MA60
} as const;

/**
 * 获取 MA 均线配置
 */
export function getMAConfigs() {
  return [
    { period: 5, color: MA_COLORS[5], label: 'MA5' },
    { period: 10, color: MA_COLORS[10], label: 'MA10' },
    { period: 20, color: MA_COLORS[20], label: 'MA20' },
    { period: 60, color: MA_COLORS[60], label: 'MA60' },
  ];
}
