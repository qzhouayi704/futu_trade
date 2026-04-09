// 配置管理 Hook

import { useState, useEffect, useCallback } from "react";
import { configApi } from "@/lib/api";
import type { ApiResponse } from "@/types";

// 配置类型定义
export interface Config {
  // 富途API配置
  futu_host: string;
  futu_port: number;

  // 系统运行配置
  update_interval: number;
  database_path: string;
  auto_trade: boolean;

  // 交易参数配置
  price_change_threshold: number;
  volume_surge_threshold: number;

  // 数据限制配置
  max_stocks_monitor: number;
  max_subscription_stocks: number;
  max_active_stocks: number;
  max_plate_stocks: number;
  max_target_plates: number;
  max_quality_plates: number;

  // K线和历史数据配置
  kline_days: number;
  max_kline_records: number;
  max_recent_signals: number;
  stocks_per_plate: number;
  max_stocks_for_kline_update: number;
  max_stocks_for_trading: number;
}

export interface ConfigMeta {
  config_path?: string;
  last_modified?: string;
}

export interface ConfigValidation {
  valid: boolean;
  message?: string;
}

export function useConfig() {
  const [config, setConfig] = useState<Config | null>(null);
  const [originalConfig, setOriginalConfig] = useState<Config | null>(null);
  const [meta, setMeta] = useState<ConfigMeta>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 加载配置
  const loadConfig = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await configApi.getConfig() as ApiResponse<Config> & { meta?: ConfigMeta };

      if (response.success && response.data) {
        setConfig(response.data);
        setOriginalConfig(JSON.parse(JSON.stringify(response.data))); // 深拷贝
        setMeta(response.meta || {});
      } else {
        throw new Error(response.message || "加载配置失败");
      }
    } catch (err: any) {
      const errorMessage = err.message || "加载配置时发生错误";
      setError(errorMessage);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  // 保存配置
  const saveConfig = useCallback(async (newConfig: Config) => {
    setLoading(true);
    setError(null);

    try {
      const response = await configApi.updateConfig(newConfig) as ApiResponse<Config> & {
        meta?: ConfigMeta;
        requires_restart?: boolean;
      };

      if (response.success && response.data) {
        setConfig(response.data);
        setOriginalConfig(JSON.parse(JSON.stringify(response.data)));
        setMeta(response.meta || {});

        return {
          success: true,
          requires_restart: response.requires_restart || false,
        };
      } else {
        throw new Error(response.message || "保存配置失败");
      }
    } catch (err: any) {
      const errorMessage = err.message || "保存配置时发生错误";
      setError(errorMessage);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  // 重置配置
  const resetConfig = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await configApi.resetConfig() as ApiResponse<Config> & { meta?: ConfigMeta };

      if (response.success && response.data) {
        setConfig(response.data);
        setOriginalConfig(JSON.parse(JSON.stringify(response.data)));
        setMeta(response.meta || {});
      } else {
        throw new Error(response.message || "重置配置失败");
      }
    } catch (err: any) {
      const errorMessage = err.message || "重置配置时发生错误";
      setError(errorMessage);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  // 验证配置
  const validateConfig = useCallback((configToValidate: Config): ConfigValidation => {
    // 必填字段验证
    const requiredFields: Record<string, string> = {
      futu_host: "富途API主机地址",
      futu_port: "富途API端口",
      update_interval: "更新间隔",
    };

    for (const [field, label] of Object.entries(requiredFields)) {
      const value = configToValidate[field as keyof Config];
      if (!value || (typeof value === "string" && value.trim() === "")) {
        return {
          valid: false,
          message: `${label}不能为空`,
        };
      }
    }

    // 数值范围验证
    const numberRanges: Record<string, { min: number; max: number; label: string }> = {
      futu_port: { min: 1, max: 65535, label: "富途API端口" },
      update_interval: { min: 5, max: 3600, label: "更新间隔" },
      price_change_threshold: { min: 0, max: 50, label: "价格变化阈值" },
      volume_surge_threshold: { min: 1, max: 20, label: "成交量激增阈值" },
    };

    for (const [field, range] of Object.entries(numberRanges)) {
      const value = configToValidate[field as keyof Config] as number;
      if (value !== null && value !== undefined) {
        if (value < range.min || value > range.max) {
          return {
            valid: false,
            message: `${range.label}必须在${range.min}-${range.max}之间`,
          };
        }
      }
    }

    return { valid: true };
  }, []);

  // 检查配置是否有变化
  const hasChanges = useCallback(() => {
    if (!config || !originalConfig) return false;
    return JSON.stringify(config) !== JSON.stringify(originalConfig);
  }, [config, originalConfig]);

  // 初始化加载
  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  return {
    config,
    originalConfig,
    meta,
    loading,
    error,
    setConfig,
    loadConfig,
    saveConfig,
    resetConfig,
    validateConfig,
    hasChanges,
  };
}
