// 常量定义

// 市场类型
export const MARKETS = {
  HK: "HK",
  US: "US",
  CN: "CN",
} as const;

export const MARKET_NAMES = {
  HK: "港股",
  US: "美股",
  CN: "A股",
} as const;

// 信号类型
export const SIGNAL_TYPES = {
  BUY: "buy",
  SELL: "sell",
} as const;

export const SIGNAL_TYPE_NAMES = {
  buy: "买入",
  sell: "卖出",
} as const;

// 交易状态
export const TRADE_STATUS = {
  PENDING: "pending",
  SUCCESS: "success",
  FAILED: "failed",
  CANCELLED: "cancelled",
} as const;

export const TRADE_STATUS_NAMES = {
  pending: "待处理",
  success: "成功",
  failed: "失败",
  cancelled: "已取消",
} as const;

// 颜色常量
export const COLORS = {
  UP: "#28a745",
  DOWN: "#dc3545",
  PRIMARY: "#0d6efd",
  SUCCESS: "#28a745",
  DANGER: "#dc3545",
  WARNING: "#ffc107",
  INFO: "#17a2b8",
} as const;

// API 路径
export const API_PATHS = {
  STOCKS: "/api/stocks",
  QUOTES: "/api/quotes",
  TRADING: "/api/trading",
  STRATEGY: "/api/strategy",
  SYSTEM: "/api/system",
  CONFIG: "/api/config",
} as const;

// 分页默认值
export const PAGINATION = {
  DEFAULT_PAGE: 1,
  DEFAULT_PAGE_SIZE: 20,
  PAGE_SIZE_OPTIONS: [10, 20, 50, 100],
} as const;

// 刷新间隔（毫秒）
export const REFRESH_INTERVALS = {
  REALTIME: 1000, // 1秒
  NORMAL: 5000, // 5秒
  SLOW: 30000, // 30秒
  MINUTE: 60000, // 1分钟
} as const;
