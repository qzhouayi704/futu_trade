// 自动刷新 Hook - 支持页面可见性感知和连续失败暂停

import { useEffect, useRef, useCallback, useState } from "react";

interface UseTickerAutoRefreshOptions {
  /** 刷新间隔（毫秒），默认 10000（10秒） */
  interval?: number;
  /** 是否启用自动刷新 */
  enabled?: boolean;
  /** 刷新回调，返回 Promise */
  onRefresh: () => Promise<void>;
  /** 连续失败次数达到此值时暂停，默认 3 */
  maxConsecutiveFailures?: number;
  /** 暂停时的回调 */
  onPaused?: () => void;
}

/**
 * 定时自动刷新 Hook
 *
 * - 使用 setInterval 定时调用 onRefresh
 * - 监听 document.visibilitychange：页面不可见时清除定时器，重新可见时立即刷新一次并恢复定时器
 * - 连续失败达到 maxConsecutiveFailures 次时暂停自动刷新，调用 onPaused
 * - 返回 { paused, resume } 供外部控制
 */
export function useTickerAutoRefresh({
  interval = 10000,
  enabled = true,
  onRefresh,
  maxConsecutiveFailures = 3,
  onPaused,
}: UseTickerAutoRefreshOptions) {
  const [paused, setPaused] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const failCountRef = useRef(0);
  const pausedRef = useRef(false);

  // 同步 pausedRef 与 state
  pausedRef.current = paused;

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const doRefresh = useCallback(async () => {
    if (pausedRef.current) return;
    try {
      await onRefresh();
      failCountRef.current = 0;
    } catch {
      failCountRef.current += 1;
      if (failCountRef.current >= maxConsecutiveFailures) {
        setPaused(true);
        clearTimer();
        onPaused?.();
      }
    }
  }, [onRefresh, maxConsecutiveFailures, clearTimer, onPaused]);

  const startTimer = useCallback(() => {
    clearTimer();
    if (!enabled || pausedRef.current) return;
    timerRef.current = setInterval(doRefresh, interval);
  }, [enabled, interval, doRefresh, clearTimer]);

  // 页面可见性监听 + 定时器管理
  useEffect(() => {
    if (!enabled) return;

    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        if (!pausedRef.current) {
          doRefresh();
          startTimer();
        }
      } else {
        clearTimer();
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);
    startTimer();

    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
      clearTimer();
    };
  }, [enabled, doRefresh, startTimer, clearTimer]);

  /** 重置失败计数，恢复自动刷新 */
  const resume = useCallback(() => {
    failCountRef.current = 0;
    setPaused(false);
    startTimer();
  }, [startTimer]);

  return { paused, resume };
}
