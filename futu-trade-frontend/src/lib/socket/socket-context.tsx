// Socket.IO React Context

"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { Socket } from "socket.io-client";
import { getSocket, disconnectSocket } from "./socket-client";

export type ConnectionState =
  | "idle"
  | "checking"
  | "connecting"
  | "connected"
  | "error";

interface SocketContextType {
  socket: Socket | null;
  isConnected: boolean;
  connectionState: ConnectionState;
  retryCount: number;
  errorMessage: string | null;
  reconnect: () => void;
}

const SocketContext = createContext<SocketContextType>({
  socket: null,
  isConnected: false,
  connectionState: "idle",
  retryCount: 0,
  errorMessage: null,
  reconnect: () => {},
});

export const SocketProvider = ({ children }: { children: ReactNode }) => {
  const [socket, setSocket] = useState<Socket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionState, setConnectionState] = useState<ConnectionState>("idle");
  const [retryCount, setRetryCount] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const initSocket = async () => {
    setConnectionState("checking");
    setErrorMessage(null);

    try {
      const socketInstance = await getSocket();
      setSocket(socketInstance);
      setConnectionState("connected");
      setIsConnected(socketInstance.connected);

      // 监听连接状态
      const handleConnect = () => {
        console.log("[SocketProvider] Connected");
        setIsConnected(true);
        setConnectionState("connected");
        setRetryCount(0);
        setErrorMessage(null);
      };

      const handleDisconnect = () => {
        console.log("[SocketProvider] Disconnected");
        setIsConnected(false);
        setConnectionState("connecting");
      };

      const handleConnectError = (error: Error) => {
        console.error("[SocketProvider] Connection error:", error.message);
        setConnectionState("error");
        setErrorMessage(error.message);
        setRetryCount((prev) => prev + 1);
      };

      socketInstance.on("connect", handleConnect);
      socketInstance.on("disconnect", handleDisconnect);
      socketInstance.on("connect_error", handleConnectError);

      // 如果已经连接，更新状态
      if (socketInstance.connected) {
        setIsConnected(true);
        setConnectionState("connected");
      }

      return () => {
        socketInstance.off("connect", handleConnect);
        socketInstance.off("disconnect", handleDisconnect);
        socketInstance.off("connect_error", handleConnectError);
      };
    } catch (error) {
      console.error("[SocketProvider] Init failed:", error);
      setConnectionState("error");
      setErrorMessage(error instanceof Error ? error.message : "Unknown error");
      setRetryCount((prev) => prev + 1);
    }
  };

  const reconnect = () => {
    console.log("[SocketProvider] Manual reconnect triggered");
    disconnectSocket();
    setSocket(null);
    setIsConnected(false);
    setConnectionState("idle");
    setRetryCount(0);
    setErrorMessage(null);
    initSocket();
  };

  useEffect(() => {
    let cleanup: (() => void) | undefined;

    initSocket().then((cleanupFn) => {
      cleanup = cleanupFn;
    });

    return () => {
      if (cleanup) cleanup();
    };
  }, []);

  return (
    <SocketContext.Provider
      value={{
        socket,
        isConnected,
        connectionState,
        retryCount,
        errorMessage,
        reconnect,
      }}
    >
      {children}
    </SocketContext.Provider>
  );
};

export const useSocket = () => {
  const context = useContext(SocketContext);
  if (context === undefined) {
    throw new Error("useSocket must be used within a SocketProvider");
  }
  return context;
};
