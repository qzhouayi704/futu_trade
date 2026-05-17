// Toast 组件

"use client";

import { createContext, useContext, useState, ReactNode, useCallback, useRef } from "react";

type ToastType = "success" | "error" | "warning" | "info";

interface ToastMessage {
  id: string;
  type: ToastType;
  title: string;
  message: string;
  count: number;       // 合并计数
  exiting?: boolean;   // 退出动画
}

interface ToastContextType {
  showToast: (type: ToastType, title: string, message: string) => void;
}

/** 最多同时显示的 toast 数量 */
const MAX_VISIBLE = 3;
/** 去重窗口（ms）：同 title 在此时间内只更新计数 */
const DEDUP_WINDOW = 3000;

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const ToastProvider = ({ children }: { children: ReactNode }) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  /** 记录最近展示的 title → 时间戳，用于去重 */
  const recentRef = useRef<Map<string, { id: string; ts: number }>>(new Map());

  const removeToast = useCallback((id: string) => {
    // 先播放退出动画
    setToasts((prev) => prev.map((t) => t.id === id ? { ...t, exiting: true } : t));
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 250);
  }, []);

  const showToast = useCallback((type: ToastType, title: string, message: string) => {
    const now = Date.now();
    const dedupKey = `${type}::${title}`;
    const recent = recentRef.current.get(dedupKey);

    // 去重：同类 toast 在 DEDUP_WINDOW 内合并为计数+1
    if (recent && now - recent.ts < DEDUP_WINDOW) {
      recentRef.current.set(dedupKey, { id: recent.id, ts: now });
      setToasts((prev) =>
        prev.map((t) =>
          t.id === recent.id ? { ...t, message, count: t.count + 1, exiting: false } : t
        )
      );
      return;
    }

    const id = `toast-${now}-${Math.random().toString(36).slice(2, 6)}`;
    const newToast: ToastMessage = { id, type, title, message, count: 1 };

    recentRef.current.set(dedupKey, { id, ts: now });

    setToasts((prev) => {
      let next = [...prev, newToast];
      // 超过上限时移除最旧的
      while (next.length > MAX_VISIBLE) {
        next = next.slice(1);
      }
      return next;
    });

    // 自动移除（统一 4 秒）
    const duration = type === "error" ? 5000 : 4000;
    setTimeout(() => {
      removeToast(id);
      // 清理去重记录
      const cur = recentRef.current.get(dedupKey);
      if (cur?.id === id) recentRef.current.delete(dedupKey);
    }, duration);
  }, [removeToast]);

  const typeConfig = {
    success: { bg: "bg-green-500", icon: "✓" },
    error: { bg: "bg-red-500", icon: "✕" },
    warning: { bg: "bg-yellow-500", icon: "⚠" },
    info: { bg: "bg-blue-500", icon: "ℹ" },
  };

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}

      {/* Toast Container */}
      <div className="fixed top-4 right-4 z-50 space-y-2 pointer-events-none">
        {toasts.map((toast) => {
          const config = typeConfig[toast.type] || typeConfig.info;
          return (
            <div
              key={toast.id}
              className={`bg-white rounded-lg shadow-lg overflow-hidden min-w-[280px] max-w-sm pointer-events-auto transition-all duration-250 ${
                toast.exiting
                  ? "opacity-0 translate-x-8"
                  : "opacity-100 translate-x-0 animate-slide-in"
              }`}
            >
              <div className="flex items-start p-3">
                <div className={`${config.bg} text-white rounded-full w-6 h-6 flex items-center justify-center flex-shrink-0 text-xs`}>
                  {config.icon}
                </div>
                <div className="ml-2 flex-1 min-w-0">
                  <h4 className="text-xs font-semibold text-gray-900 flex items-center gap-1.5">
                    {toast.title}
                    {toast.count > 1 && (
                      <span className="inline-flex items-center justify-center px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-red-100 text-red-600 leading-none">
                        +{toast.count - 1}
                      </span>
                    )}
                  </h4>
                  <p className="text-xs text-gray-500 mt-0.5 truncate">{toast.message}</p>
                </div>
                <button
                  onClick={() => removeToast(toast.id)}
                  className="ml-1 text-gray-300 hover:text-gray-500 flex-shrink-0"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M6 18L18 6M6 6l12 12"
                    />
                  </svg>
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return context;
};

// 导出一个空的 Toast 组件以保持兼容性
export const Toast = () => null;
