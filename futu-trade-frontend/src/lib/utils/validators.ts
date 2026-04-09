// 验证工具函数

/**
 * 验证股票代码格式
 */
export function isValidStockCode(code: string): boolean {
  if (!code) return false;

  // 港股格式：HK.xxxxx
  const hkPattern = /^HK\.\d{5}$/;
  // 美股格式：US.xxxx
  const usPattern = /^US\.[A-Z]{1,5}$/;
  // A股格式：SH.xxxxxx 或 SZ.xxxxxx
  const cnPattern = /^(SH|SZ)\.\d{6}$/;

  return hkPattern.test(code) || usPattern.test(code) || cnPattern.test(code);
}

/**
 * 验证价格
 */
export function isValidPrice(price: number): boolean {
  return !isNaN(price) && price > 0 && isFinite(price);
}

/**
 * 验证数量
 */
export function isValidQuantity(quantity: number): boolean {
  return !isNaN(quantity) && quantity > 0 && Number.isInteger(quantity);
}

/**
 * 验证邮箱
 */
export function isValidEmail(email: string): boolean {
  const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailPattern.test(email);
}

/**
 * 验证手机号
 */
export function isValidPhone(phone: string): boolean {
  const phonePattern = /^1[3-9]\d{9}$/;
  return phonePattern.test(phone);
}

/**
 * 验证URL
 */
export function isValidUrl(url: string): boolean {
  try {
    new URL(url);
    return true;
  } catch {
    return false;
  }
}

/**
 * 验证数字范围
 */
export function isInRange(value: number, min: number, max: number): boolean {
  return value >= min && value <= max;
}
