// 预警信号类型定义

export interface Alert {
  type: string;              // 预警类型：'5分钟涨幅预警'/'5分钟跌幅预警'/'5分钟振幅预警'
  stock_code: string;        // 股票代码
  stock_name: string;        // 股票名称
  current_price: number;     // 当前价格
  base_price: number;        // 基准价格（5分钟内最早的价格）
  max_price: number;         // 5分钟内最高价
  min_price: number;         // 5分钟内最低价
  rise_percent?: number;     // 涨幅百分比（仅涨幅预警）
  fall_percent?: number;     // 跌幅百分比（仅跌幅预警）
  amplitude: number;         // 振幅百分比
  volume?: number;           // 成交量（仅成交量异常预警）
  volume_display?: string;   // 格式化后的成交量（如"500.0万"）
  timestamp: string;         // ISO格式时间戳
  level: string;             // 预警级别：'danger'/'warning'/'info'
  message: string;           // 详细预警消息
  time_period?: string;      // 时间周期（如'5分钟'）
}

export interface AlertsResponse {
  success: boolean;
  message: string;
  data: Alert[];
}
