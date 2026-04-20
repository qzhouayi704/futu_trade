// 后端就绪检测 Hook
// 轮询后端 /health 端点，直到返回 200

import { useState, useEffect } from "react";

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:5001";
const MAX_ATTEMPTS = 60;
const RETRY_INTERVAL = 1000;

export function useBackendReady() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let attempts = 0;
    let timeoutId: ReturnType<typeof setTimeout>;
    let cancelled = false;

    const checkBackend = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/health`, {
          method: "GET",
          cache: "no-store",
        });

        if (!cancelled && response.ok) {
          setReady(true);
          return;
        }
      } catch {
        // 连接失败，继续重试
      }

      if (cancelled) return;

      attempts++;
      if (attempts >= MAX_ATTEMPTS) {
        setError("后端服务启动超时，请检查后端是否正常运行");
        return;
      }

      timeoutId = setTimeout(checkBackend, RETRY_INTERVAL);
    };

    checkBackend();

    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, []);

  return { ready, error };
}
