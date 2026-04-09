// 系统配置管理页面

"use client";

import { useState, useEffect } from "react";
import { Card } from "@/components/common";
import { ConfigForm } from "./components/ConfigForm";
import { ConfigActions } from "./components/ConfigActions";
import { useConfig } from "./hooks/useConfig";
import { formatTime } from "@/lib/utils";
import { useToast } from "@/components/common/Toast";
import { Modal } from "@/components/common";

export default function ConfigPage() {
  const {
    config,
    meta,
    loading,
    error,
    setConfig,
    saveConfig,
    resetConfig,
    validateConfig,
    hasChanges,
  } = useConfig();

  const { showToast } = useToast();
  const [showResetModal, setShowResetModal] = useState(false);
  const [showSaveModal, setShowSaveModal] = useState(false);

  // 处理保存配置
  const handleSave = () => {
    if (!config) return;

    // 验证配置
    const validation = validateConfig(config);
    if (!validation.valid) {
      showToast("error", "验证失败", validation.message || "配置验证失败");
      return;
    }

    // 检查是否有变化
    if (!hasChanges()) {
      showToast("info", "提示", "配置没有变化");
      return;
    }

    // 显示确认对话框
    setShowSaveModal(true);
  };

  // 确认保存
  const confirmSave = async () => {
    if (!config) return;

    setShowSaveModal(false);

    try {
      const result = await saveConfig(config);

      if (result.success) {
        showToast("success", "成功", "配置保存成功");

        if (result.requires_restart) {
          showToast("warning", "提示", "部分配置更改需要重启系统后生效");
        }
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "保存配置失败";
      showToast("error", "错误", message);
    }
  };

  // 处理重置配置
  const handleReset = () => {
    setShowResetModal(true);
  };

  // 确认重置
  const confirmReset = async () => {
    setShowResetModal(false);

    try {
      await resetConfig();
      showToast("success", "成功", "已恢复默认配置");
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "重置配置失败";
      showToast("error", "错误", message);
    }
  };

  // 页面离开前检查未保存的更改
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (hasChanges()) {
        e.preventDefault();
        e.returnValue = "您有未保存的配置更改，确定要离开吗？";
      }
    };

    window.addEventListener("beforeunload", handleBeforeUnload);

    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [hasChanges]);

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <i className="fas fa-wrench text-blue-600"></i>
          系统配置管理
        </h1>

        <ConfigActions
          onSave={handleSave}
          onReset={handleReset}
          hasChanges={hasChanges()}
          loading={loading}
        />
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">
          <div className="flex items-center gap-2 text-red-800">
            <i className="fas fa-exclamation-circle"></i>
            <span className="font-medium">加载配置失败</span>
          </div>
          <p className="text-sm text-red-600 mt-1">{error}</p>
        </div>
      )}

      {/* 配置表单 */}
      <Card className="mb-6">
        <ConfigForm config={config} onChange={setConfig} />
      </Card>

      {/* 当前配置状态 */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <i className="fas fa-info-circle text-blue-600"></i>
          <h3 className="text-lg font-medium text-gray-900">当前配置状态</h3>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div>
            <p className="text-sm text-gray-500 mb-1">配置文件路径</p>
            <p className="font-medium text-gray-900">
              {meta.config_path || "simple_trade/config.json"}
            </p>
          </div>

          <div>
            <p className="text-sm text-gray-500 mb-1">最后修改时间</p>
            <p className="font-medium text-gray-900">
              {meta.last_modified ? formatTime(new Date(meta.last_modified)) : "未知"}
            </p>
          </div>

          <div>
            <p className="text-sm text-gray-500 mb-1">配置状态</p>
            <div className="font-medium">
              {loading ? (
                <span className="text-yellow-600 flex items-center gap-1">
                  <i className="fas fa-spinner fa-spin"></i>
                  加载中...
                </span>
              ) : error ? (
                <span className="text-red-600 flex items-center gap-1">
                  <i className="fas fa-exclamation-circle"></i>
                  加载失败
                </span>
              ) : (
                <span className="text-green-600 flex items-center gap-1">
                  <i className="fas fa-check-circle"></i>
                  已加载
                </span>
              )}
            </div>
          </div>
        </div>
      </Card>

      {/* 保存确认对话框 */}
      <Modal
        isOpen={showSaveModal}
        onClose={() => setShowSaveModal(false)}
        title="保存配置"
      >
        <p className="text-gray-700 mb-6">
          确定要保存配置更改吗？保存后将立即生效。
        </p>

        <div className="flex justify-end gap-3">
          <button
            onClick={() => setShowSaveModal(false)}
            className="px-4 py-2 text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors"
          >
            取消
          </button>
          <button
            onClick={confirmSave}
            className="px-4 py-2 text-white bg-blue-600 rounded-md hover:bg-blue-700 transition-colors"
          >
            确认保存
          </button>
        </div>
      </Modal>

      {/* 重置确认对话框 */}
      <Modal
        isOpen={showResetModal}
        onClose={() => setShowResetModal(false)}
        title="恢复默认配置"
      >
        <p className="text-gray-700 mb-6">
          确定要恢复默认配置吗？这将清除所有自定义设置。
        </p>

        <div className="flex justify-end gap-3">
          <button
            onClick={() => setShowResetModal(false)}
            className="px-4 py-2 text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors"
          >
            取消
          </button>
          <button
            onClick={confirmReset}
            className="px-4 py-2 text-white bg-red-600 rounded-md hover:bg-red-700 transition-colors"
          >
            确认重置
          </button>
        </div>
      </Modal>
    </div>
  );
}
