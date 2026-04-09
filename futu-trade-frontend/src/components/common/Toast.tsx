// Toast 组件

"use client";

import { createContext, useContext, useState, ReactNode, useCallback } from "react";

type ToastType = "success" | "error" | "warning" | "info";

interface ToastMessage {
  id: string;
  type: ToastType;
  title: string;
  message: string;
}

interface ToastContextType {
  showToast: (type: ToastType, title: string, message: string) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const ToastProvider = ({ children }: { children: ReactNode }) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const showToast = useCallback((type: ToastType, title: string, message: string) => {
    const id = `toast-${Date.now()}-${Math.random()}`;
    const newToast: ToastMessage = { id, type, title, message };

    setToasts((prev) => [...prev, newToast]);

    // 自动移除
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, type === "error" ? 8000 : 5000);
  }, []);

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

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
      <div className="fixed top-4 right-4 z-50 space-y-2">
        {toasts.map((toast) => {
          const config = typeConfig[toast.type] || typeConfig.info;
          return (
            <div
              key={toast.id}
              className="bg-white rounded-lg shadow-lg overflow-hidden min-w-[300px] max-w-md animate-slide-in"
            >
              <div className="flex items-start p-4">
                <div className={`${config.bg} text-white rounded-full w-8 h-8 flex items-center justify-center flex-shrink-0`}>
                  {config.icon}
                </div>
                <div className="ml-3 flex-1">
                  <h4 className="text-sm font-semibold text-gray-900">{toast.title}</h4>
                  <p className="text-sm text-gray-600 mt-1">{toast.message}</p>
                </div>
                <button
                  onClick={() => removeToast(toast.id)}
                  className="ml-2 text-gray-400 hover:text-gray-600"
                >
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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
