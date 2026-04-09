// 配置操作按钮组件

"use client";

import { Button } from "@/components/common";

interface ConfigActionsProps {
  onSave: () => void;
  onReset: () => void;
  hasChanges: boolean;
  loading: boolean;
}

export function ConfigActions({
  onSave,
  onReset,
  hasChanges,
  loading,
}: ConfigActionsProps) {
  return (
    <div className="flex items-center gap-3">
      <Button
        variant="secondary"
        onClick={onReset}
        disabled={loading}
        className="flex items-center gap-2"
      >
        <i className="fas fa-undo"></i>
        恢复默认
      </Button>

      <Button
        variant="primary"
        onClick={onSave}
        disabled={loading || !hasChanges}
        loading={loading}
        className="flex items-center gap-2"
      >
        <i className="fas fa-save"></i>
        保存配置
      </Button>
    </div>
  );
}
