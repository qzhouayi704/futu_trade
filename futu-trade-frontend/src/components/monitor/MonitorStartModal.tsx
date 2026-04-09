"use client";

import React, { useState, useEffect } from "react";
import { Modal } from "@/components/common/Modal";
import { ProgressSteps, Step } from "@/components/common/ProgressSteps";
import { Button } from "@/components/common/Button";
import { systemApi } from "@/lib/api";

interface MonitorStartModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

type ErrorType =
  | "FUTU_NOT_CONNECTED"
  | "STOCK_POOL_EMPTY"
  | "ALREADY_RUNNING"
  | "TIMEOUT"
  | "NETWORK_ERROR"
  | "UNKNOWN";

interface ErrorInfo {
  type: ErrorType;
  message: string;
  suggestion: string;
  actionLabel: string;
  actionType: "retry" | "navigate" | "close" | "diagnose";
}

type ModalStep = "starting" | "success" | "error";

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export const MonitorStartModal: React.FC<MonitorStartModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
}) => {
  const [currentModalStep, setCurrentModalStep] = useState<ModalStep>("starting");
  const [steps, setSteps] = useState<Step[]>([
    { label: "检查系统状态", status: "pending" },
    { label: "连接富途API", status: "pending" },
    { label: "加载股票池", status: "pending" },
    { label: "启动监控线程", status: "pending" },
  ]);
  const [currentStep, setCurrentStep] = useState(0);
  const [error, setError] = useState<ErrorInfo | null>(null);
  const [isStarting, setIsStarting] = useState(false);

  const resetState = () => {
    setCurrentModalStep("starting");
    setSteps([
      { label: "检查系统状态", status: "pending" },
      { label: "连接富途API", status: "pending" },
      { label: "加载股票池", status: "pending" },
      { label: "启动监控线程", status: "pending" },
    ]);
    setCurrentStep(0);
    setError(null);
    setIsStarting(false);
  };

  const updateStep = (index: number, status: Step["status"], message?: string) => {
    setSteps((prev) =>
      prev.map((step, i) => (i === index ? { ...step, status, message } : step))
    );
    if (status === "loading") {
      setCurrentStep(index);
    }
  };

  const handleError = (err: any): ErrorInfo => {
    const errorMessage = err.message || "未知错误";
    if (errorMessage === "FUTU_NOT_CONNECTED") {
      return {
        type: "FUTU_NOT_CONNECTED",
        message: "富途API未连接",
        suggestion: "请检查富途客户端是否已启动",
        actionLabel: "重新检测",
        actionType: "retry",
      };
    } else if (errorMessage === "STOCK_POOL_EMPTY") {
      return {
        type: "STOCK_POOL_EMPTY",
        message: "股票池为空，无法启动监控",
        suggestion: "请先初始化股票池数据",
        actionLabel: "前往股票池管理",
        actionType: "navigate",
      };
    } else if (errorMessage === "ALREADY_RUNNING") {
      return {
        type: "ALREADY_RUNNING",
        message: "监控已在运行中",
        suggestion: "无需重复启动",
        actionLabel: "确定",
        actionType: "close",
      };
    } else if (errorMessage === "TIMEOUT") {
      return {
        type: "TIMEOUT",
        message: "启动超时",
        suggestion: "请检查系统状态或网络连接",
        actionLabel: "重试",
        actionType: "retry",
      };
    } else if (err.code === "ERR_NETWORK" || errorMessage.includes("网络")) {
      return {
        type: "NETWORK_ERROR",
        message: "网络连接失败",
        suggestion: "请检查网络连接",
        actionLabel: "重试",
        actionType: "retry",
      };
    } else {
      return {
        type: "UNKNOWN",
        message: errorMessage,
        suggestion: "请查看系统日志或联系技术支持",
        actionLabel: "查看诊断信息",
        actionType: "diagnose",
      };
    }
  };

  const startMonitor = async () => {
    setIsStarting(true);
    setError(null);

    try {
      // 步骤1: 检查系统状态
      updateStep(0, "loading");
      const statusRes = await systemApi.getStatus();
      if (!statusRes.success) throw new Error("系统状态检查失败");
      updateStep(0, "success");
      await delay(300);

      // 步骤2: 检查富途API
      updateStep(1, "loading");
      if (!statusRes.data?.futu_connected) {
        updateStep(1, "error", "富途API未连接");
        throw new Error("FUTU_NOT_CONNECTED");
      }
      updateStep(1, "success");
      await delay(300);

      // 步骤3: 检查股票池
      updateStep(2, "loading");
      const healthRes = await systemApi.getMonitorHealth();
      if (
        !healthRes.success ||
        !healthRes.data?.stock_pool ||
        healthRes.data?.stock_pool.total_count === 0
      ) {
        updateStep(2, "error", "股票池为空");
        throw new Error("STOCK_POOL_EMPTY");
      }
      updateStep(2, "success");
      await delay(300);

      // 步骤4: 启动监控
      updateStep(3, "loading");
      const startRes = await Promise.race([
        systemApi.startMonitor(),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error("TIMEOUT")), 30000)
        ),
      ]);

      if (!startRes.success) {
        const errorMsg = startRes.message || "启动失败";
        if (errorMsg.includes("已在运行") || errorMsg.includes("already running")) {
          throw new Error("ALREADY_RUNNING");
        }
        throw new Error(errorMsg);
      }

      updateStep(3, "success");
      setCurrentModalStep("success");
      await delay(2000);
      onSuccess?.();
      onClose();
    } catch (err: any) {
      const errorInfo = handleError(err);
      setError(errorInfo);
      setCurrentModalStep("error");
      updateStep(currentStep, "error", errorInfo.message);
    } finally {
      setIsStarting(false);
    }
  };

  const handleAction = () => {
    if (!error) return;
    switch (error.actionType) {
      case "retry":
        resetState();
        startMonitor();
        break;
      case "navigate":
        window.location.href = "/stock-pool";
        break;
      case "close":
        onClose();
        break;
      case "diagnose":
        console.log("显示诊断信息");
        break;
    }
  };

  useEffect(() => {
    if (isOpen) {
      resetState();
      startMonitor();
    }
  }, [isOpen]);

  const handleClose = () => {
    if (!isStarting) {
      resetState();
      onClose();
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="正在启动监控" size="md">
      <div className="min-h-[300px]">
        {currentModalStep === "starting" && (
          <div className="py-4">
            <ProgressSteps steps={steps} currentStep={currentStep} />
          </div>
        )}

        {currentModalStep === "success" && (
          <div className="flex flex-col items-center justify-center py-8">
            <div className="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center mb-4 animate-scale-in">
              <svg className="w-8 h-8 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold text-gray-900 mb-2">监控已启动</h3>
            <p className="text-sm text-gray-500">监控已成功启动</p>
          </div>
        )}

        {currentModalStep === "error" && error && (
          <div className="flex flex-col items-center justify-center py-8">
            <div className="w-16 h-16 rounded-full bg-red-100 flex items-center justify-center mb-4">
              <svg className="w-8 h-8 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold text-gray-900 mb-2">{error.message}</h3>
            <p className="text-sm text-gray-500 mb-6">{error.suggestion}</p>
            <div className="flex gap-3">
              <Button variant="secondary" onClick={handleClose}>取消</Button>
              <Button onClick={handleAction}>{error.actionLabel}</Button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
};
