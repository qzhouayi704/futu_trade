// K线和历史数据配置分组

"use client";

import React, { useState } from "react";
import type { Config } from "../hooks/useConfig";

interface KlineSectionProps {
  formData: Config;
  onChange: (field: keyof Config, value: number) => void;
}

export function KlineSection({ formData, onChange }: KlineSectionProps) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors"
      >
        <div className="flex items-center gap-2">
          <i className="fas fa-chart-bar text-gray-600"></i>
          <span className="font-medium text-gray-900">K线和历史数据配置</span>
        </div>
        <i className={`fas fa-chevron-down text-gray-400 transition-transform ${isOpen ? "rotate-180" : ""}`}></i>
      </button>

      {isOpen && (
        <div className="px-4 py-4 bg-white space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">K线数据天数</label>
              <input
                type="number"
                value={formData.kline_days}
                onChange={(e) => onChange("kline_days", parseInt(e.target.value))}
                placeholder="30"
                min={1}
                max={365}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-gray-500 mt-1">获取K线数据的天数</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">K线记录数量上限</label>
              <input
                type="number"
                value={formData.max_kline_records}
                onChange={(e) => onChange("max_kline_records", parseInt(e.target.value))}
                placeholder="200"
                min={10}
                max={1000}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-gray-500 mt-1">单只股票K线记录数量</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">最近交易信号数量</label>
              <input
                type="number"
                value={formData.max_recent_signals}
                onChange={(e) => onChange("max_recent_signals", parseInt(e.target.value))}
                placeholder="50"
                min={10}
                max={500}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-gray-500 mt-1">保留的最近交易信号数量</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">每板块股票数量</label>
              <input
                type="number"
                value={formData.stocks_per_plate}
                onChange={(e) => onChange("stocks_per_plate", parseInt(e.target.value))}
                placeholder="50"
                min={10}
                max={500}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-gray-500 mt-1">从每个板块获取的股票数量</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">K线更新股票数量</label>
              <input
                type="number"
                value={formData.max_stocks_for_kline_update}
                onChange={(e) => onChange("max_stocks_for_kline_update", parseInt(e.target.value))}
                placeholder="300"
                min={10}
                max={1000}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-gray-500 mt-1">每次更新K线的股票数量</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">交易用股票数量上限</label>
              <input
                type="number"
                value={formData.max_stocks_for_trading}
                onChange={(e) => onChange("max_stocks_for_trading", parseInt(e.target.value))}
                placeholder="1000"
                min={10}
                max={2000}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-gray-500 mt-1">用于交易策略的股票数量上限</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
