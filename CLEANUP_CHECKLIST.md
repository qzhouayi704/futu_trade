# 冗余代码与文件清理清单

> **生成时间**：2026-04-23  
> **目标**：删除未使用的 Phase 4-6 组件、过程文档、冗余别名

---

## 🗑️ 立即删除的文件（无依赖）

### 1. Phase 4-6 未使用组件

- [ ] **删除 GlobalAPIScheduler**
  - 文件：`simple_trade/core/api/global_api_scheduler.py`
  - 原因：从未被调用，已在 core_services.py 中注释掉
  - 影响：无，已确认无外部依赖

- [ ] **删除 ProgressiveDataRecovery**
  - 文件：`simple_trade/core/recovery/progressive_data_recovery.py`
  - 原因：`_load_quote_from_db()` 空实现，从未被调用
  - 影响：无，已在 core_services.py 中注释掉

- [ ] **删除 AdaptiveTickerQueue**
  - 文件：`simple_trade/core/cache/adaptive_ticker_queue.py`
  - 原因：Scalping 已关闭，该队列仅为 Scalping 设计
  - 影响：需检查 core_services.py 中的条件创建逻辑

- [ ] **删除 EnhancedWriteQueue**
  - 文件：`simple_trade/database/core/enhanced_write_queue.py`
  - 原因：批量合并未实现，且从未被实际使用
  - 影响：需删除 core_services.py 中的创建代码

- [ ] **删除 ScalpingMetrics**
  - 文件：`simple_trade/core/state/scalping_metrics.py`
  - 原因：Scalping 已关闭
  - 影响：需检查 state_manager.py 中的引用

### 2. 空目录清理

删除文件后，检查以下目录是否为空，如果为空则删除：

- [ ] `simple_trade/core/api/` — 删除 global_api_scheduler.py 后检查
- [ ] `simple_trade/core/recovery/` — 删除 progressive_data_recovery.py 后检查

---

## 📝 清理导入和引用

### 3. core_services.py 清理

文件：`simple_trade/core/container/core_services.py`

- [ ] **删除导入语句（L21-27）**
  ```python
  # 删除这些行：
  from ..api.global_api_scheduler import GlobalAPIScheduler
  from ..cache.adaptive_ticker_queue import AdaptiveTickerQueue
  from ..recovery.progressive_data_recovery import ProgressiveDataRecovery
  from ...database.core.enhanced_write_queue import EnhancedWriteQueue
  ```

- [ ] **删除属性声明（L48, 53-55）**
  ```python
  # 删除这些行：
  self.global_api_scheduler: Optional[GlobalAPIScheduler] = None
  self.enhanced_write_queue: Optional[EnhancedWriteQueue] = None
  self.adaptive_ticker_queue: Optional[AdaptiveTickerQueue] = None
  self.progressive_recovery: Optional[ProgressiveDataRecovery] = None
  ```

- [ ] **删除初始化代码（L100-101, 112-127, 216-217, 227-242）**
  - 删除所有已注释的初始化代码
  - 删除 `EnhancedWriteQueue` 和 `AdaptiveTickerQueue` 的条件创建代码

### 4. __init__.py 清理

- [ ] **core/api/__init__.py**
  ```python
  # 删除：
  from .global_api_scheduler import GlobalAPIScheduler
  __all__ = ['GlobalAPIScheduler']
  ```
  - 如果删除后文件为空，删除整个 `core/api/` 目录

- [ ] **core/recovery/__init__.py**
  ```python
  # 删除：
  from .progressive_data_recovery import ProgressiveDataRecovery
  __all__ = ['ProgressiveDataRecovery']
  ```
  - 如果删除后文件为空，删除整个 `core/recovery/` 目录

- [ ] **core/cache/__init__.py**
  ```python
  # 删除：
  from .adaptive_ticker_queue import AdaptiveTickerQueue
  # 修改 __all__：
  __all__ = ['UnifiedDataCache']  # 移除 AdaptiveTickerQueue
  ```

### 5. 冗余别名清理

- [ ] **删除重复的别名定义**
  - 文件：`simple_trade/core/subscription/subscription_recovery_helper.py:75`
  - 删除：`GlobalSubscriptionCoordinator = SubscriptionRecoveryHelper`
  - 原因：已在 `__init__.py` 中定义，无需重复

---

## 📄 过程文档清理

### 6. 删除根目录下的过程文档

这些是开发过程中的阶段性文档，已完成的工作应该体现在代码中，不需要保留：

- [ ] `INTEGRATION_COMPLETE.md`
- [ ] `PHASE_0_6_COMPLETE.md`
- [ ] `PHASE_1_3_PROGRESS.md`
- [ ] `PHASE_4_COMPLETE.md`

**保留的文档**：
- `README.md` — 项目说明
- `TODO.md` — 原有的 TODO（如果还在用）
- `OPTIMIZATION_TODO.md` — 当前优化计划
- `CLEANUP_CHECKLIST.md` — 本清单（完成后可删除）

---

## 🔍 验证步骤

完成清理后，执行以下验证：

### 验证 1：导入检查
```bash
cd "d:\Program Files\futu_trade_sys"
python -c "from simple_trade.core.container.core_services import CoreServices; print('Import OK')"
```

### 验证 2：启动测试
```bash
# 启动系统，检查日志中是否有错误
python -m simple_trade.main
```

### 验证 3：搜索残留引用
```bash
# 检查是否还有对已删除组件的引用
git grep "GlobalAPIScheduler" --include="*.py"
git grep "ProgressiveDataRecovery" --include="*.py"
git grep "AdaptiveTickerQueue" --include="*.py"
git grep "EnhancedWriteQueue" --include="*.py"
git grep "ScalpingMetrics" --include="*.py"
```

如果搜索结果只在 `__pycache__` 或已删除的文件中，说明清理成功。

---

## 📊 清理统计

| 类型 | 数量 | 说明 |
|------|------|------|
| 删除的 Python 文件 | 5 | 未使用的 Phase 4-6 组件 |
| 删除的 Markdown 文件 | 4 | 过程文档 |
| 清理的导入语句 | ~15 | core_services.py 和 __init__.py |
| 删除的属性声明 | 4 | core_services.py |
| 删除的初始化代码 | ~30 行 | core_services.py |
| 删除的冗余别名 | 1 | subscription_recovery_helper.py |

**预计减少代码行数**：~800 行

---

## ⚠️ 注意事项

1. **备份当前代码**
   ```bash
   git add -A
   git commit -m "backup: 清理前备份"
   ```

2. **分批清理**
   - 先删除文件
   - 再清理导入
   - 最后验证

3. **如果遇到问题**
   - 检查是否有遗漏的引用
   - 使用 `git diff` 查看修改
   - 必要时回滚：`git reset --hard HEAD`

---

## ✅ 完成标志

- [ ] 所有文件已删除
- [ ] 所有导入已清理
- [ ] 验证步骤全部通过
- [ ] 系统启动正常
- [ ] 无残留引用

完成后，可以删除本清单文件。
