"use client";

import React, { useEffect, useRef, useState } from "react";
import { createChart, IChartApi, ISeriesApi, LineData, Time, LineStyle } from "lightweight-charts";
import { IntradayTimelinePoint } from "@/lib/api/enhanced-heat";
import type { IntradayLevelsData, IntradayPriceLevel } from "@/lib/api/enhanced-heat";

interface IntradayChartProps {
  timelineData: IntradayTimelinePoint[];
  levelsData: IntradayLevelsData | null;
}

export function IntradayChart({ timelineData, levelsData }: IntradayChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const [containerHeight, setContainerHeight] = useState(300);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Create chart instance
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { color: "transparent" },
        textColor: "#6B7280", // text-gray-500
      },
      grid: {
        vertLines: { color: "#F3F4F6", style: LineStyle.Dashed },
        horzLines: { color: "#F3F4F6", style: LineStyle.Dashed },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderVisible: false,
        fixLeftEdge: true,
        fixRightEdge: true,
        tickMarkFormatter: (time: number) => {
          const date = new Date(time * 1000);
          return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`;
        },
      },
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: {
          top: 0.1,
          bottom: 0.1,
        },
      },
      crosshair: {
        mode: 1, // Normal mode
        vertLine: {
          color: "#9CA3AF",
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: "#4B5563",
        },
        horzLine: {
          color: "#9CA3AF",
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: "#4B5563",
        },
      },
      handleScroll: false,
      handleScale: false,
    });

    // Main Price Line
    const mainSeries = chart.addLineSeries({
      color: "#3B82F6", // blue-500
      lineWidth: 2,
      crosshairMarkerVisible: true,
      crosshairMarkerRadius: 4,
    });

    // VWAP Line
    const vwapSeries = chart.addLineSeries({
      color: "#F59E0B", // amber-500
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      crosshairMarkerVisible: false,
    });

    // Volume Histogram
    const volumeSeries = chart.addHistogramSeries({
      color: "#94A3B8", // slate-400
      priceFormat: {
        type: "volume",
      },
      priceScaleId: "", // overlay
    });
    
    // Scale margins so volume stays at the bottom 20%
    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    });

    chartRef.current = chart;
    seriesRef.current = mainSeries;
    vwapSeriesRef.current = vwapSeries;
    volumeSeriesRef.current = volumeSeries;

    // Custom Tooltip
    chart.subscribeCrosshairMove((param) => {
      if (!tooltipRef.current || !chartContainerRef.current) return;
      
      if (
        param.point === undefined ||
        !param.time ||
        param.point.x < 0 ||
        param.point.x > chartContainerRef.current.clientWidth ||
        param.point.y < 0 ||
        param.point.y > chartContainerRef.current.clientHeight
      ) {
        tooltipRef.current.style.display = 'none';
      } else {
        const date = new Date((param.time as number) * 1000);
        const timeStr = `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`;
        
        const price = param.seriesData.get(mainSeries) as LineData | undefined;
        const vwap = param.seriesData.get(vwapSeries) as LineData | undefined;
        
        let html = `<div class="font-medium text-gray-900 mb-1 border-b pb-1">${timeStr}</div>`;
        if (price) html += `<div class="text-blue-600 flex justify-between gap-4"><span>价格</span> <span class="font-mono font-medium">${price.value.toFixed(3)}</span></div>`;
        if (vwap) html += `<div class="text-amber-600 flex justify-between gap-4"><span>均价</span> <span class="font-mono font-medium">${vwap.value.toFixed(3)}</span></div>`;
        
        // Find volume
        const dataPoint = timelineData.find(d => Math.abs((new Date(d.time).getTime() / 1000) - (param.time as number)) < 2);
        if (dataPoint) {
          html += `<div class="text-gray-600 flex justify-between gap-4 mt-1 pt-1 border-t"><span>成交量</span> <span>${(dataPoint.volume / 10000).toFixed(1)}万</span></div>`;
        }

        tooltipRef.current.innerHTML = html;
        tooltipRef.current.style.display = 'block';
        
        // Position tooltip
        const tooltipWidth = tooltipRef.current.offsetWidth;
        const tooltipHeight = tooltipRef.current.offsetHeight;
        const containerWidth = chartContainerRef.current.clientWidth;
        const containerHeight = chartContainerRef.current.clientHeight;
        const y = param.point.y;
        
        let left = param.point.x + 15;
        if (left + tooltipWidth > containerWidth) {
          left = param.point.x - tooltipWidth - 15;
        }
        
        let top = y + 15;
        if (top + tooltipHeight > containerHeight) {
          top = y - tooltipHeight - 15;
        }
        
        tooltipRef.current.style.left = left + 'px';
        tooltipRef.current.style.top = top + 'px';
      }
    });

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
      }
    };

    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, []);

  // Update Data and Price Lines
  useEffect(() => {
    if (!seriesRef.current || !vwapSeriesRef.current || !chartRef.current) return;

    if (timelineData.length > 0) {
      // Format data
      const priceData: LineData[] = timelineData.map((d) => ({
        time: (new Date(d.time).getTime() / 1000) as Time,
        value: d.price,
      }));
      const vwapData: LineData[] = timelineData.map((d) => ({
        time: (new Date(d.time).getTime() / 1000) as Time,
        value: d.avg_price,
      }));

      seriesRef.current.setData(priceData);
      vwapSeriesRef.current.setData(vwapData);
      chartRef.current.timeScale().fitContent();
    }

    // Add Price Lines (Support/Resistance/POC)
    if (chartRef.current) {
      chartRef.current.removeSeries(seriesRef.current);
      chartRef.current.removeSeries(vwapSeriesRef.current);
      if (volumeSeriesRef.current) chartRef.current.removeSeries(volumeSeriesRef.current);

      const newMainSeries = chartRef.current.addLineSeries({
        color: "#3B82F6",
        lineWidth: 2,
      });
      const newVwapSeries = chartRef.current.addLineSeries({
        color: "#F59E0B",
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
      });
      const newVolumeSeries = chartRef.current.addHistogramSeries({
        color: "#94A3B8",
        priceFormat: { type: "volume" },
        priceScaleId: "",
      });
      newVolumeSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });

      seriesRef.current = newMainSeries;
      vwapSeriesRef.current = newVwapSeries;
      volumeSeriesRef.current = newVolumeSeries;

      if (timelineData.length > 0) {
        newMainSeries.setData(timelineData.map(d => ({ time: (new Date(d.time).getTime() / 1000) as Time, value: d.price })));
        newVwapSeries.setData(timelineData.map(d => ({ time: (new Date(d.time).getTime() / 1000) as Time, value: d.avg_price })));
        
        // Calculate volume color based on price change
        newVolumeSeries.setData(timelineData.map((d, i) => {
          const prevPrice = i > 0 ? timelineData[i - 1].price : d.price;
          const color = d.price >= prevPrice ? "rgba(16, 185, 129, 0.5)" : "rgba(239, 68, 68, 0.5)"; // emerald vs red
          return {
            time: (new Date(d.time).getTime() / 1000) as Time,
            value: d.volume,
            color: color
          };
        }));
        
        chartRef.current.timeScale().fitContent();
      }

      if (levelsData) {
        // Draw Resistance
        levelsData.resistance_levels.forEach(level => {
          newMainSeries.createPriceLine({
            price: level.price,
            color: "#EF4444", // red-500
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: false,
          });
        });

        // Draw Support
        levelsData.support_levels.forEach(level => {
          newMainSeries.createPriceLine({
            price: level.price,
            color: "#10B981", // emerald-500
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: false,
          });
        });

        // Draw POC
        if (levelsData.poc) {
          newMainSeries.createPriceLine({
            price: levelsData.poc.price,
            color: "#F59E0B", // amber-500
            lineWidth: 2,
            lineStyle: LineStyle.Solid,
            axisLabelVisible: false,
          });
        }
      }
    }

  }, [timelineData, levelsData]);

  return (
    <div className="w-full h-full min-h-[300px] relative group">
      <div 
        ref={chartContainerRef} 
        className="absolute inset-0"
      />
      {/* Tooltip */}
      <div
        ref={tooltipRef}
        className="absolute hidden pointer-events-none bg-white/95 backdrop-blur shadow-lg border border-gray-100 rounded-lg p-3 text-xs z-50 transition-none"
        style={{ left: 0, top: 0, minWidth: '120px' }}
      />
    </div>
  );
}
