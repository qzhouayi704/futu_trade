// Socket.IO 客户端实例

import { io, Socket } from "socket.io-client";

let socket: Socket | null = null;
let isInitializing = false;

const socketUrl = typeof window !== "undefined" ? window.location.origin : (process.env.NEXT_PUBLIC_API_URL || "http://localhost:5000");

/**
 * 健康检查：轮询后端直到就绪
 */
async function waitForBackend(
  maxAttempts: number = 30,
  interval: number = 1000
): Promise<boolean> {
  console.log("[Socket.IO] Waiting for backend to be ready...");

  for (let i = 0; i < maxAttempts; i++) {
    try {
      const response = await fetch(`${socketUrl}/health`, {
        method: "GET",
        headers: { "Content-Type": "application/json" },
      });

      if (response.ok) {
        const data = await response.json();
        if (data.ready || data.status === "ok") {
          console.log("[Socket.IO] Backend is ready");
          return true;
        }
        console.log(`[Socket.IO] Backend not ready yet (attempt ${i + 1}/${maxAttempts})`);
      }
    } catch (error) {
      // 后端未启动，继续等待
    }

    await new Promise((resolve) => setTimeout(resolve, interval));
  }

  console.error("[Socket.IO] Backend not ready after timeout");
  return false;
}

/**
 * 获取或创建 Socket 实例（异步）
 */
export const getSocket = async (): Promise<Socket> => {
  if (socket && socket.connected) {
    return socket;
  }

  if (isInitializing) {
    // 等待初始化完成
    while (isInitializing) {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (socket) return socket;
  }

  isInitializing = true;

  try {
    // 先等待后端就绪
    const isReady = await waitForBackend();
    if (!isReady) {
      throw new Error("Backend not ready after 30 seconds");
    }

    console.log("[Socket.IO] Connecting to:", socketUrl);

    // 后端就绪后再建立连接
    socket = io(socketUrl, {
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 30000,
      transports: ["websocket", "polling"],
      timeout: 20000,
      autoConnect: false,
    });

    // 事件监听
    socket.on("connect", () => {
      console.log("[Socket.IO] Connected, ID:", socket?.id);
    });

    socket.on("disconnect", (reason) => {
      console.log("[Socket.IO] Disconnected:", reason);
    });

    socket.on("connect_error", (error) => {
      console.error("[Socket.IO] Connection error:", error.message);
    });

    socket.on("reconnect", (attemptNumber) => {
      console.log("[Socket.IO] Reconnected after", attemptNumber, "attempts");
      socket?.emit("request_snapshot_refresh");
    });

    // 手动连接
    socket.connect();

    return socket;
  } finally {
    isInitializing = false;
  }
};

export const disconnectSocket = () => {
  if (socket) {
    console.log("[Socket.IO] Disconnecting...");
    socket.disconnect();
    socket = null;
  }
};

export const isSocketConnected = (): boolean => {
  return socket?.connected || false;
};
