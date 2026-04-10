// Axios 客户端配置

import axios, { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from "axios";
import type { ApiResponse, ApiError } from "@/types";

// 创建 Axios 实例（调用 Next.js API，而不是直接调用 Flask）
const apiClient: AxiosInstance = axios.create({
  baseURL: "/api", // Next.js API Routes
  timeout: 10000, // 默认10秒超时，避免长时间等待
  headers: {
    "Content-Type": "application/json",
  },
});

// ---------- 超时策略映射 ----------
// 按 URL 前缀匹配，优先匹配更具体的路径
const TIMEOUT_RULES: Array<{ match: (url: string) => boolean; timeout: number }> = [
  // 长耗时接口 → 60s
  { match: (u) => /\/(news\/crawl|init|refresh|monitor\/start|advisor\/evaluate)/.test(u), timeout: 60000 },
  // 中等耗时接口 → 30s
  { match: (u) => /\/(enhanced-heat|high-turnover)/.test(u), timeout: 30000 },
  // 交易条件页面相关接口 → 20s（后端繁忙时容易超 10s）
  { match: (u) => /\/(quotes\/(conditions|quota|trading-conditions)|system\/status|strategy\/(active|indicators))/.test(u), timeout: 20000 },
];

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    const url = config.url || "";
    for (const rule of TIMEOUT_RULES) {
      if (rule.match(url)) {
        config.timeout = rule.timeout;
        break;
      }
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// ---------- 自动重试逻辑 ----------
const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;

function isRetryable(error: AxiosError): boolean {
  // 只对 GET 请求重试（幂等）
  if (error.config?.method && error.config.method.toUpperCase() !== "GET") return false;
  // 网络超时 / 连接失败
  if (error.code === "ECONNABORTED" || error.code === "ERR_NETWORK" || !error.response) return true;
  // 502 / 503 / 504 服务端临时问题
  const status = error.response?.status;
  if (status && [502, 503, 504].includes(status)) return true;
  return false;
}

function getRetryCount(config: InternalAxiosRequestConfig): number {
  return (config as any).__retryCount || 0;
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// 响应拦截器
apiClient.interceptors.response.use(
  (response) => {
    return response.data;
  },
  async (error: AxiosError<ApiError>) => {
    const config = error.config;

    // 自动重试
    if (config && isRetryable(error)) {
      const retryCount = getRetryCount(config);
      if (retryCount < MAX_RETRIES) {
        (config as any).__retryCount = retryCount + 1;
        console.warn(`[API Retry] ${config.method?.toUpperCase()} ${config.url} → 第${retryCount + 1}次重试`);
        await sleep(RETRY_DELAY_MS);
        return apiClient(config);
      }
    }

    // 统一错误处理（重试耗尽后才报错）
    const errorMessage = error.response?.data?.message || error.message || "网络请求失败";

    console.error(
      `[API Error] ${error.config?.method?.toUpperCase() || "?"} ${error.config?.url || "?"} → ${error.response?.status || "network"}: ${errorMessage}`
    );

    return Promise.reject({
      success: false,
      message: errorMessage,
      status_code: error.response?.status || 500,
    } as ApiError);
  }
);

export default apiClient;
