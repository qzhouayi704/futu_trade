// 格式化工具函数（从 common.js 迁移）

/**
 * 格式化价格
 */
export const formatPrice = (price: number | null | undefined): string => {
  if (price == null || price === 0 || isNaN(price)) {
    return "-";
  }
  try {
    const numPrice = parseFloat(String(price));
    if (isNaN(numPrice) || numPrice === 0) {
      return "-";
    }
    return numPrice.toFixed(2);
  } catch {
    return "-";
  }
};

/**
 * 格式化百分比
 */
export const formatPercent = (percent: number | null | undefined): string => {
  if (percent == null || isNaN(percent)) {
    return "0.00%";
  }
  try {
    const numPercent = parseFloat(String(percent));
    if (isNaN(numPercent)) {
      return "0.00%";
    }
    return numPercent.toFixed(2) + "%";
  } catch {
    return "0.00%";
  }
};

/**
 * 格式化成交量
 */
export const formatVolume = (volume: number | null | undefined): string => {
  if (volume == null || volume === 0) return "-";

  if (volume >= 1000000) {
    return (volume / 1000000).toFixed(1) + "M";
  } else if (volume >= 1000) {
    return (volume / 1000).toFixed(1) + "K";
  } else {
    return volume.toString();
  }
};

/**
 * 格式化时间戳（完整格式）
 */
export const formatTimestamp = (timestamp: string | Date): string => {
  try {
    const date = new Date(timestamp);
    return date.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return String(timestamp);
  }
};

/**
 * 格式化时间（简短格式）
 */
export const formatTime = (timestamp: string | Date): string => {
  try {
    const date = new Date(timestamp);
    return date.toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return String(timestamp);
  }
};

/**
 * 格式化日期时间（完整格式）
 */
export const formatDateTime = (timestamp: string | Date): string => {
  try {
    const date = new Date(timestamp);
    return date.toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return String(timestamp);
  }
};

/**
 * 格式化数字（千分位）
 */
export const formatNumber = (num: number | null | undefined): string => {
  if (num == null) return "-";
  return parseFloat(String(num)).toLocaleString("zh-CN");
};

/**
 * 格式化相对时间
 */
export const formatRelativeTime = (isoString: string | Date): string => {
  if (!isoString) return "--";

  try {
    const date = new Date(isoString);
    const now = new Date();
    const diff = now.getTime() - date.getTime();

    if (diff < 60000) {
      return "刚刚";
    } else if (diff < 3600000) {
      return Math.floor(diff / 60000) + "分钟前";
    } else if (diff < 86400000) {
      return Math.floor(diff / 3600000) + "小时前";
    } else {
      return date.toLocaleDateString();
    }
  } catch {
    return "--";
  }
};
