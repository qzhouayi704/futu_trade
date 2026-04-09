// 配置表单组件

"use client";

import React, { useEffect, useState } from "react";
import { ConfigSection } from "./ConfigSection";
import { KlineSection } from "./KlineSection";
import { StrategySection } from "./StrategySection";
import type { Config } from "../hooks/useConfig";

interface ConfigFormProps {
  config: Config | null;
  onChange: (config: Config) => void;
}

export function ConfigForm({ config, onChange }: ConfigFormProps) {
  const [formData, setFormData] = useState<Config | null>(config);
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    futuApi: true,
    system: false,
    trading: false,
    dataLimit: false,
  });

  useEffect(() => {
    setFormData(config);
  }, [config]);

  const handleChange = (field: keyof Config, value: any) => {
    if (!formData) return;

    const newConfig = {
      ...formData,
      [field]: value,
    };

    setFormData(newConfig);
    onChange(newConfig);
  };

  const toggleSection = (section: string) => {
    setOpenSections((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  if (!formData) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">加载配置中...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* 富途API配置 */}
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <button
          type="button"
          onClick={() => toggleSection("futuApi")}
          className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors"
        >
          <div className="flex items-center gap-2">
            <i className="fas fa-plug text-gray-600"></i>
            <span className="font-medium text-gray-900">富途API配置</span>
          </div>
          <i
            className={`fas fa-chevron-down text-gray-400 transition-transform ${
              openSections.futuApi ? "rotate-180" : ""
            }`}
          ></i>
        </button>

        {openSections.futuApi && (
          <div className="px-4 py-4 bg-white">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  富途API主机地址{" "}
                  <span className="text-gray-500 font-normal">(通常为127.0.0.1)</span>
                </label>
                <input
                  type="text"
                  value={formData.futu_host}
                  onChange={(e) => handleChange("futu_host", e.target.value)}
                  placeholder="127.0.0.1"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  富途API端口{" "}
                  <span className="text-gray-500 font-normal">(默认11111)</span>
                </label>
                <input
                  type="number"
                  value={formData.futu_port}
                  onChange={(e) => handleChange("futu_port", parseInt(e.target.value))}
                  placeholder="11111"
                  min={1}
                  max={65535}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 系统运行配置 */}
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <button
          type="button"
          onClick={() => toggleSection("system")}
          className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors"
        >
          <div className="flex items-center gap-2">
            <i className="fas fa-cog text-gray-600"></i>
            <span className="font-medium text-gray-900">系统运行配置</span>
          </div>
          <i
            className={`fas fa-chevron-down text-gray-400 transition-transform ${
              openSections.system ? "rotate-180" : ""
            }`}
          ></i>
        </button>

        {openSections.system && (
          <div className="px-4 py-4 bg-white">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  更新间隔(秒){" "}
                  <span className="text-gray-500 font-normal">(建议30-300秒)</span>
                </label>
                <input
                  type="number"
                  value={formData.update_interval}
                  onChange={(e) => handleChange("update_interval", parseInt(e.target.value))}
                  placeholder="60"
                  min={5}
                  max={3600}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="text-xs text-gray-500 mt-1">
                  过短的间隔可能导致API频繁调用限制
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  数据库路径{" "}
                  <span className="text-gray-500 font-normal">(相对路径)</span>
                </label>
                <input
                  type="text"
                  value={formData.database_path}
                  onChange={(e) => handleChange("database_path", e.target.value)}
                  placeholder="simple_trade/data/trade.db"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            <div className="mt-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={formData.auto_trade}
                  onChange={(e) => handleChange("auto_trade", e.target.checked)}
                  className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                />
                <span className="text-sm font-medium text-gray-700">
                  启用自动交易{" "}
                  <span className="text-red-600 font-normal">(谨慎使用)</span>
                </span>
              </label>
              <p className="text-xs text-gray-500 mt-1 ml-6">
                开启后系统将根据策略自动执行交易
              </p>
            </div>
          </div>
        )}
      </div>

      {/* 交易参数配置 */}
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <button
          type="button"
          onClick={() => toggleSection("trading")}
          className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors"
        >
          <div className="flex items-center gap-2">
            <i className="fas fa-chart-line text-gray-600"></i>
            <span className="font-medium text-gray-900">交易参数配置</span>
          </div>
          <i
            className={`fas fa-chevron-down text-gray-400 transition-transform ${
              openSections.trading ? "rotate-180" : ""
            }`}
          ></i>
        </button>

        {openSections.trading && (
          <div className="px-4 py-4 bg-white">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  价格变化阈值(%){" "}
                  <span className="text-gray-500 font-normal">(建议1-10%)</span>
                </label>
                <input
                  type="number"
                  value={formData.price_change_threshold}
                  onChange={(e) =>
                    handleChange("price_change_threshold", parseFloat(e.target.value))
                  }
                  placeholder="3.0"
                  step={0.1}
                  min={0}
                  max={50}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="text-xs text-gray-500 mt-1">触发价格异动提醒的阈值</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  成交量激增阈值(倍){" "}
                  <span className="text-gray-500 font-normal">(建议1.5-5倍)</span>
                </label>
                <input
                  type="number"
                  value={formData.volume_surge_threshold}
                  onChange={(e) =>
                    handleChange("volume_surge_threshold", parseFloat(e.target.value))
                  }
                  placeholder="2.0"
                  step={0.1}
                  min={1}
                  max={20}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="text-xs text-gray-500 mt-1">
                  成交量相对平均值的倍数阈值
                </p>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 数据限制配置 */}
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <button
          type="button"
          onClick={() => toggleSection("dataLimit")}
          className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors"
        >
          <div className="flex items-center gap-2">
            <i className="fas fa-database text-gray-600"></i>
            <span className="font-medium text-gray-900">数据限制配置</span>
          </div>
          <i
            className={`fas fa-chevron-down text-gray-400 transition-transform ${
              openSections.dataLimit ? "rotate-180" : ""
            }`}
          ></i>
        </button>

        {openSections.dataLimit && (
          <div className="px-4 py-4 bg-white space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  监控股票数量上限
                </label>
                <input
                  type="number"
                  value={formData.max_stocks_monitor}
                  onChange={(e) =>
                    handleChange("max_stocks_monitor", parseInt(e.target.value))
                  }
                  placeholder="800"
                  min={10}
                  max={2000}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="text-xs text-gray-500 mt-1">同时监控的股票数量</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  订阅股票数量上限
                </label>
                <input
                  type="number"
                  value={formData.max_subscription_stocks}
                  onChange={(e) =>
                    handleChange("max_subscription_stocks", parseInt(e.target.value))
                  }
                  placeholder="1000"
                  min={10}
                  max={2000}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="text-xs text-gray-500 mt-1">订阅实时行情的股票数量</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  活跃股票池大小
                </label>
                <input
                  type="number"
                  value={formData.max_active_stocks}
                  onChange={(e) =>
                    handleChange("max_active_stocks", parseInt(e.target.value))
                  }
                  placeholder="800"
                  min={10}
                  max={2000}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="text-xs text-gray-500 mt-1">活跃股票池的大小</p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  板块股票数量上限
                </label>
                <input
                  type="number"
                  value={formData.max_plate_stocks}
                  onChange={(e) =>
                    handleChange("max_plate_stocks", parseInt(e.target.value))
                  }
                  placeholder="800"
                  min={10}
                  max={2000}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="text-xs text-gray-500 mt-1">每个板块获取的股票数量</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  目标板块数量上限
                </label>
                <input
                  type="number"
                  value={formData.max_target_plates}
                  onChange={(e) =>
                    handleChange("max_target_plates", parseInt(e.target.value))
                  }
                  placeholder="50"
                  min={5}
                  max={200}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="text-xs text-gray-500 mt-1">目标板块的数量限制</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  优质板块数量上限
                </label>
                <input
                  type="number"
                  value={formData.max_quality_plates}
                  onChange={(e) =>
                    handleChange("max_quality_plates", parseInt(e.target.value))
                  }
                  placeholder="20"
                  min={5}
                  max={100}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="text-xs text-gray-500 mt-1">优质板块的数量限制</p>
              </div>
            </div>
          </div>
        )}
      </div>

      <KlineSection formData={formData} onChange={handleChange} />

      <StrategySection />
    </div>
  );
}
