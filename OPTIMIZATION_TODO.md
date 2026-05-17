# 国内服务器部署 · 数据链路稳定性优化 TODO

> **目标**：将系统部署到国内服务器，解决报价推送延迟高、偶发卡顿、潜在 BUG 不好查的问题
> 
> **当前状态**：OpenD 与交易系统同机部署（本地回环），Scalping 已关闭
> 
> **实施原则**：先观测、再加固、再降级、再隔离、最后演练

---

## 🔧 收尾清理（当前优先级最高）

**目标**：清理已完成重构中的残留、双轨、歧义，确保代码唯一真相

### 收尾-1：清理 GlobalSubscriptionCoordinator 双轨

**问题**：目前同时存在旧文件和新文件，容易混淆

- [ ] **删除旧文件或改为单行转发**
  - 文件：`simple_trade/core/subscription/global_subscription_coordinator.py`
  - 当前状态：与 `subscription_recovery_helper.py` 并存
  - **方案 A（推荐）**：删除旧文件，统一使用新文件
    - 检查所有 import：`from ..subscription.global_subscription_coordinator import GlobalSubscriptionCoordinator`
    - 全部改为：`from ..subscription.subscription_recovery_helper import SubscriptionRecoveryHelper`
    - 删除 `global_subscription_coordinator.py`
  - **方案 B**：保留旧文件作为兼容壳
    - 将 `global_subscription_coordinator.py` 改为：
      ```python
      # 向后兼容：已重构为 SubscriptionRecoveryHelper
      from .subscription_recovery_helper import SubscriptionRecoveryHelper as GlobalSubscriptionCoordinator
      __all__ = ['GlobalSubscriptionCoordinator']
      ```
    - 文件只保留 3 行
  - 验证：
    - `git grep "global_subscription_coordinator" | grep -v ".pyc"` 只返回兼容壳或无结果
    - 启动系统，日志显示 `SubscriptionRecoveryHelper` 而非 `GlobalSubscriptionCoordinator`

### 收尾-2：Scalping 路由改为真正按需导入

**问题**：虽然注册时有条件判断，但 import 仍在顶层发生

- [ ] **改为条件导入**
  - 文件：`simple_trade/routers/__init__.py:38, 83-86`
  - 修改前：
    ```python
    from .trading.scalping import router as scalping_router
    # ...
    if config.scalping_enabled:
        app.include_router(scalping_router)
    ```
  - 修改后：
    ```python
    # 删除顶层 import
    # ...
    if config.scalping_enabled:
        from .trading.scalping import router as scalping_router
        app.include_router(scalping_router)
    ```
  - 验证：
    - `config.scalping_enabled=false` 时，`import simple_trade.routers` 不会触发 `scalping.py` 的加载
    - 可通过在 `scalping.py` 顶部加 `print("scalping module loaded")` 测试

### 收尾-3：清理 Scalping 残留文案与事件

**问题**：代码中仍有 Scalping 相关提示，容易误导

- [ ] **清理 AsyncQuotePusher 中的 Scalping 文案**
  - 文件：`simple_trade/services/core/async_quote_pusher.py:208`
  - 修改：
    ```python
    # 原：print_status("【行情推送】首次报价获取成功，通知 Scalping 引擎", "ok")
    # 改：
    print_status("【行情推送】首次报价获取成功，系统已就绪", "ok")
    ```

- [ ] **检查并清理其他 Scalping 残留文案**
  - 搜索：`git grep -i "scalping" --include="*.py" | grep -v "routers/trading/scalping.py" | grep -v "services/scalping/"`
  - 逐个检查是否为残留文案或注释
  - 清理原则：
    - 功能代码保留（如 `scalping_enabled` 配置项）
    - 提示文案改为中性说法
    - 注释中的历史说明可保留但标注"已废弃"

### 收尾-4：确认 ProgressiveDataRecovery 不接入主链路

**问题**：组件仍在容器中创建，但功能未实现

- [ ] **检查启动链路是否调用**
  - 文件：`simple_trade/app.py`
  - 搜索：`progressive_recovery.start_recovery`
  - 确认：该方法未被调用，或已被注释

- [ ] **容器中条件创建或标注未完成**
  - 文件：`simple_trade/core/container/core_services.py:126, 240`
  - **方案 A（推荐）**：条件创建
    ```python
    # 仅在配置启用时创建（当前未启用）
    if getattr(config, 'progressive_recovery_enabled', False):
        self.progressive_recovery = ProgressiveDataRecovery(...)
    else:
        self.progressive_recovery = None
    ```
  - **方案 B**：保留但标注
    ```python
    # Phase 4 组件：渐进式数据恢复（未完成，暂不启用）
    self.progressive_recovery = ProgressiveDataRecovery(...)
    ```
  - 验证：启动日志中不再出现 `ProgressiveDataRecovery` 相关初始化信息

### 收尾-5：明确 DegradationManager 与 UnifiedDataCache 的职责边界

**问题**：两个组件都有降级决策能力，容易冲突

- [ ] **在代码注释中明确职责分工**
  - 文件：`simple_trade/core/cache/degradation_manager.py:1-16`
  - 补充注释：
    ```python
    """
    多层降级策略管理器（P3-3）
    
    职责边界：
    - DegradationManager: 全局降级等级决策（功能开关、推送频率）
    - UnifiedDataCache: 缓存清理策略（内存压力响应）
    
    协作方式：
    - DegradationManager 不直接操作缓存
    - UnifiedDataCache 不决定全局降级等级
    - 两者通过配置和事件解耦
    """
    ```

- [ ] **检查是否有交叉决策**
  - 搜索：`DegradationManager` 是否调用 `UnifiedDataCache` 的方法
  - 搜索：`UnifiedDataCache` 是否调用 `DegradationManager` 的方法
  - 确认：两者只通过配置和状态查询交互，不直接控制对方

- [ ] **补充集成测试用例**
  - 文件：`tests/integration/test_degradation.py`（新建）
  - 测试场景：
    - 内存 85% 时，`UnifiedDataCache` 清理缓存，`DegradationManager` 保持 NORMAL
    - API 连续失败 15 次时，`DegradationManager` 进入 DEGRADED，`UnifiedDataCache` 不受影响
    - 两者同时触发时，行为符合预期（缓存清理 + 功能降级）

---

## Phase 0：紧急清理（必须先做，避免误触发）⚠️

### P0-1：禁用未实现的组件

**目标**：避免空壳组件在启动时被调用，导致延迟或异常

- [ ] **禁用 UnifiedDataCache 的自动降级**
  - 文件：`simple_trade/core/cache/unified_data_cache.py:190-220`
  - 修改：注释掉 `_memory_monitor_loop` 中的降级逻辑（L197-205）
  - 原因：L2 缓存未实现，降级时会导致缓存雪崩
  - 验证：启动系统，内存超 80% 时不会清空 L1 缓存

- [ ] **禁用 ProgressiveDataRecovery 的启动调用**
  - 文件：`simple_trade/app.py`（搜索 `progressive_recovery`）
  - 修改：注释掉 `progressive_recovery.start_recovery()` 的调用
  - 原因：数据加载未实现，启动时白等 30 秒
  - 验证：启动时间减少 30 秒

- [ ] **删除 EnhancedWriteQueue 的空壳批量合并代码**
  - 文件：`simple_trade/database/core/enhanced_write_queue.py:188-205`
  - 修改：删除 `_group_by_table` 和 `_extract_table_name` 方法
  - 原因：从未使用，避免误导
  - 验证：代码编译通过

### P0-2：删除 Scalping 残留组件

**目标**：减少启动开销，避免无效对象占用内存

- [ ] **条件创建 Scalping 相关缓存**
  - 文件：`simple_trade/core/container/core_services.py:52-56`
  - 修改：
    ```python
    if config.scalping_enabled:
        self.adaptive_ticker_queue = AdaptiveTickerQueue()
    else:
        self.adaptive_ticker_queue = None
    ```
  - 同样处理：`scalping_metrics_state`、`ticker_df_cache`
  - 验证：启动日志中不再出现 Scalping 相关组件初始化

- [ ] **条件注册 Scalping 路由**
  - 文件：`simple_trade/routers/__init__.py:79`
  - 修改：
    ```python
    if config.scalping_enabled:
        app.include_router(scalping_router)
    ```
  - 验证：访问 `/api/scalping/*` 返回 404

### P0-3：统一重连入口

**目标**：避免双层重连竞态冲突

- [ ] **删除 FutuClient 的自动重连逻辑**
  - 文件：`simple_trade/api/futu_client.py:213-260`
  - 修改：删除 `_try_reconnect()` 方法和 `_on_reconnect_callbacks`
  - 保留：`connect()` 和 `is_connected` 方法
  - 原因：统一到 `GlobalConnectionManager` 作为唯一重连入口
  - 验证：重连时只有 `GlobalConnectionManager` 的日志，没有 `FutuClient` 的重连日志

- [ ] **GlobalConnectionManager 补齐重连机制**
  - 文件：`simple_trade/core/connection/global_connection_manager.py:125-136`
  - 修改：
    - 单次重连加 30s 超时
    - 指数退避：2s → 4s → 8s → 上限 60s
    - 重连成功后调用 OpenD `query_subscription` 校验订阅一致性
  - 验证：断开 OpenD 后，重连日志显示退避时间和订阅校验

---

## Phase 1：可观测性建设（3 天）

**目标**：让"偶发卡顿"和"潜在 BUG"可被量化

### P1-1：数据链路埋点

- [ ] **FutuClient API 调用埋点**
  - 文件：`simple_trade/api/futu_client.py`（在 `_execute_with_retry` 或全局 QPS 限流处）
  - 新增：结构化日志输出到 `logs/futu_api.log`
  - 格式：`{"flow": "futu_api", "api": "get_stock_quote", "duration_ms": 123, "retry": 0, "success": true, "timestamp": "..."}`
  - 验证：`tail -f logs/futu_api.log | grep futu_api`

- [ ] **AsyncQuotePusher 推送循环埋点**
  - 文件：`simple_trade/services/core/async_quote_pusher.py:_push_loop`
  - 新增：每轮记录 `fetch_ms`、`broadcast_ms`、`quote_count`、`consecutive_failures`
  - 输出：`logs/quote_cycle.log`
  - 验证：定位延迟是在拉取还是广播

- [ ] **SubscriptionManager 订阅动作埋点**
  - 文件：`simple_trade/api/subscription_manager.py`（`subscribe_quote`、`unsubscribe_quote`）
  - 新增：记录订阅/取消订阅的股票数、成功数、失败数、耗时
  - 输出：`logs/subscription.log`
  - 验证：重连后订阅恢复日志完整

- [ ] **GlobalConnectionManager 重连埋点**
  - 文件：`simple_trade/core/connection/global_connection_manager.py:_handle_disconnection`
  - 新增：记录重连触发原因、重连耗时、订阅恢复耗时
  - 输出：`logs/reconnect.log`
  - 验证：断开 OpenD 后，日志显示完整重连链路

### P1-2：链路健康监控

- [ ] **新增 LinkHealthMonitor**
  - 文件：`simple_trade/core/monitoring/link_health.py`（新建）
  - 功能：
    - 每 10s 计算 P50/P95/P99 延迟、成功率、重连频率
    - 暴露 HTTP 端点 `/api/monitoring/link-health`
  - 验证：浏览器访问端点，返回 JSON 指标

- [ ] **订阅一致性巡检**
  - 文件：`simple_trade/core/monitoring/subscription_checker.py`（新建）
  - 功能：
    - 每 5 分钟从 OpenD 拉取实际订阅列表
    - 与 `SubscriptionManager` 内存状态对比
    - 不一致即日志 + 告警
  - 验证：手动取消订阅后，5 分钟内检测到漂移

### P1-3：日志轮转配置

- [ ] **配置日志轮转**
  - 文件：`simple_trade/utils/logger.py`
  - 修改：单文件最大 50MB，保留最近 7 天
  - 验证：日志文件不会无限增长

---

## Phase 2：连接与推送加固（5 天）

**目标**：直接缓解"报价推送延迟高 / 偶发卡顿"

### P2-1：推送循环拆分

- [ ] **广播改为 fire-and-forget**
  - 文件：`simple_trade/core/pipeline/quote_pipeline.py:run_quote_cycle`
  - 修改：
    ```python
    # 原：await self._broadcaster.broadcast(...)
    # 改：
    task = asyncio.create_task(self._broadcaster.broadcast(...))
    self._pending_tasks.add(task)
    task.add_done_callback(self._pending_tasks.discard)
    ```
  - 验证：广播卡顿时，下一轮拉取不受影响

- [ ] **广播加超时保护**
  - 文件：`simple_trade/core/pipeline/pipeline_broadcast.py:broadcast`
  - 修改：
    ```python
    try:
        await asyncio.wait_for(self.socket_manager.emit_to_all(...), timeout=3.0)
    except asyncio.TimeoutError:
        logger.warning("广播超时，丢弃本轮")
    ```
  - 验证：慢客户端不影响推送周期

### P2-2：订阅恢复分级

- [ ] **实现分级订阅恢复**
  - 文件：`simple_trade/api/subscription_manager.py`（新增方法 `restore_subscriptions_by_priority`）
  - 逻辑：
    - P0 批：持仓股（从 `trade_signals` 表查）
    - P1 批：策略监控目标股
    - P2 批：其他订阅股
    - 每批间隔 200ms
  - 验证：重连后持仓股报价 <1s 恢复

- [ ] **订阅状态持久化到 SQLite**
  - 文件：`simple_trade/api/subscription_manager.py`
  - 新增表：`subscription_snapshot (type TEXT, codes TEXT, updated_at INTEGER)`
  - 逻辑：订阅成功后写入，系统启动时优先恢复
  - 验证：重启后订阅列表从 DB 恢复

### P2-3：自适应超时

- [ ] **实现动态超时计算**
  - 文件：`simple_trade/api/futu_client.py`（新增 `AdaptiveTimeoutManager`）
  - 逻辑：
    - 报价类：`max(5s, P95 延迟 × 3)`，上限 30s
    - 交易类：固定 30s
    - 历史 K 线：固定 60s
    - 每小时滚动重算
  - 验证：P0 监控数据显示超时自动调整

---

## Phase 3：缓存与多级降级（4 天）

**目标**：OpenD 抖动时仍能提供可用服务

### P3-1：L2 缓存实现（SQLite）

- [ ] **实现 UnifiedDataCache 的 L2 方法**
  - 文件：`simple_trade/core/cache/unified_data_cache.py:175-188`
  - 新增表：`cache_entries (key TEXT PRIMARY KEY, value BLOB, expire_at INTEGER, updated_at INTEGER)`
  - 实现：`_get_from_db`、`_put_db`、`_delete_from_db`
  - 序列化：`pickle` + zlib
  - 验证：降级时 L2 写入成功，恢复时 L2 读取成功

### P3-2：分级内存降级

- [ ] **改进内存降级策略**
  - 文件：`simple_trade/core/cache/unified_data_cache.py:_check_memory_usage`
  - 修改：
    - 70% → 清理已过期条目
    - 80% → LFU 清理最低频 20%
    - 90% → LRU 清理最久未访问 50%
    - 95% → 清空 L1 但保留 L2
  - 验证：内存压力测试，不会一次性清空

### P3-3：多层降级策略

- [ ] **实现 DegradationManager**
  - 文件：`simple_trade/core/degradation/degradation_manager.py`（新建）
  - 降级等级：
    - L0 正常 → L1 缓存降级 → L2 K 线降级 → L3 只读 → L4 熔断
  - 触发条件：连续失败次数、重连频率
  - 广播：通过 WebSocket 通知前端（新增 `SocketEvent.DEGRADATION_CHANGED`）
  - 验证：模拟 OpenD 断连 5 分钟，降级等级切换符合预期

---

## Phase 4：链路隔离与优先级（3 天）

**目标**：交易链路不被监控 / 分析链路拖累

### P4-1：请求优先级

- [ ] **RateLimiter 增加优先级支持**
  - 文件：`simple_trade/utils/rate_limiter.py`
  - 修改：P0（交易）独享 100 QPS，P1-P3 共享剩余
  - 验证：压测时 P0 请求成功率 >99%

### P4-2：熔断器接口级隔离

- [ ] **按接口独立熔断**
  - 文件：`simple_trade/core/circuit_breaker/circuit_breaker.py`（或新建）
  - 修改：`get_history_kline` 熔断不影响 `get_stock_quote`
  - 验证：K 线接口熔断时，报价接口正常

---

## Phase 5：架构简化（2 天）

**目标**：减少启动开销和维护复杂度

### P5-1：启动链路瘦身

- [ ] **关键服务立即启动，非关键后台启动**
  - 文件：`simple_trade/app.py:lifespan`
  - 修改：
    - 阻塞启动：数据库、富途连接、HTTP API
    - 后台启动：QuotePusher、监控任务、预热、通知
  - 验证：HTTP API <5 秒就绪

### P5-2：删除未使用的组件

- [ ] **删除 GlobalAPIScheduler**
  - 文件：`simple_trade/core/container/core_services.py`（删除创建）
  - 原因：从未使用
  - 验证：启动日志中不再出现

- [ ] **删除 GlobalMonitoringDashboard 或改懒加载**
  - 文件：`simple_trade/core/container/core_services.py`
  - 修改：改为 `@property` 懒加载
  - 验证：启动时不创建，访问 `/api/monitoring/global` 时才创建

- [ ] **简化 GlobalSubscriptionCoordinator（方案 A）**
  - 文件：`simple_trade/core/subscription/global_subscription_coordinator.py`
  - **步骤 1：删除未使用的功能**
    - 删除方法：
      - `request_subscription()` — 从未调用
      - `release_subscription()` — 从未调用
      - `get_subscription_status()` — 从未调用
      - `set_quota_limits()` — 从未调用
      - `request_subscription_sync()` — 从未调用
      - `_try_cleanup_low_priority()` — 从未调用
      - `_do_subscribe()` — 从未调用
      - `_do_unsubscribe()` — 从未调用
    - 删除属性：
      - `_quota_limits`
      - `_subscriptions`
      - `_subscription_times`
      - `_subscription_priorities`
      - `_lock`
      - `_sync_lock`
    - 保留方法：
      - `force_clear_all()` — GlobalConnectionManager 使用
      - `restore_all_subscriptions()` — GlobalConnectionManager 使用
      - `_get_subscription_count()` — global_monitoring.py 使用
  - **步骤 2：重命名类**
    - 类名：`GlobalSubscriptionCoordinator` → `SubscriptionRecoveryHelper`
    - 文件名：`global_subscription_coordinator.py` → `subscription_recovery_helper.py`
  - **步骤 3：简化实现**
    - `force_clear_all()` 直接调用 `subscription_manager.force_clear_subscriptions()`
    - `restore_all_subscriptions()` 直接调用 `subscription_manager` 的订阅方法
    - `_get_subscription_count()` 直接读取 `subscription_manager.subscribed_count`
  - **步骤 4：更新引用**
    - `core_services.py`：更新 import 和变量名
    - `global_connection_manager.py`：更新变量名
    - `global_monitoring.py`：更新变量名
    - `subscription_helper.py`：删除未使用的引用
  - 验证：
    - 重连流程正常（断开 OpenD 后自动恢复）
    - 监控端点 `/api/global-monitoring/subscription/stats` 正常返回
    - 启动日志显示 `SubscriptionRecoveryHelper` 而非 `GlobalSubscriptionCoordinator`

---

## Phase 6：数据层优化（2 天）

**目标**：提升写入性能和缓存命中率

### P6-1：QuoteCache 优化

- [ ] **读写分离 + 浅拷贝**
  - 文件：`simple_trade/services/market_data/quote_cache.py`
  - 修改：
    - 读操作不加锁
    - `get_all_quotes` 改为 `self._cache.copy()`
  - 验证：高频更新时锁竞争减少

### P6-2：ConnectionManager 连接健康检查

- [ ] **每次 get_connection 前检查连接**
  - 文件：`simple_trade/database/core/connection_manager.py:get_connection`
  - 修改：
    ```python
    if hasattr(self._local, 'connection') and self._local.connection:
        try:
            self._local.connection.execute("SELECT 1")
        except sqlite3.Error:
            self._close_thread_connection()
    ```
  - 验证：网络抖动后连接自动重建

### P6-3：EnhancedWriteQueue 降级策略

- [ ] **分级降级而非直接拒绝**
  - 文件：`simple_trade/database/core/enhanced_write_queue.py:submit`
  - 修改：
    - 队列 > 1000 且 priority <= 2：强制插入，丢弃最低优先级
    - 队列 > 1000 且 priority > 2：拒绝
  - 验证：高优先级任务不会被拒绝

---

## Phase 7：压测演练与灰度上线（5 天）

**目标**：验证系统在极端场景下的表现

### P7-1：混沌工程测试

- [ ] **网络延迟测试**
  - 工具：Clumsy（Windows）或 tc（Linux）
  - 场景：+500ms 延迟
  - 验证：自适应超时生效，降级到 L1

- [ ] **网络丢包测试**
  - 场景：10% 丢包率
  - 验证：重试 + 缓存，成功率 >85%

- [ ] **OpenD 断连测试**
  - 场景：kill OpenD 进程 5 分钟
  - 验证：降级到 L2/L3，自动恢复

### P7-2：24 小时稳定性测试

- [ ] **长期运行测试**
  - 负载：500 只股订阅、50 QPS 报价、10 次/min 交易
  - 验证：无崩溃、无内存泄漏、成功率 >99%

### P7-3：灰度上线

- [ ] **阶段 1：单机验证**（1 天）
  - 部署到 1 台测试服务器，50 只股，跑满 24h

- [ ] **阶段 2：小流量灰度**（3 天）
  - 生产 1 台服务器，10% 流量，对比新旧监控指标

- [ ] **阶段 3：全量上线**（7 天）
  - 50% → 100%，旧系统保留 7 天做回滚

---

## 补充优化（可选，按需实施）

### 补充 1：WebSocket 广播背压保护

- [ ] **每个客户端独立发送队列**
  - 文件：`simple_trade/websocket/socket_manager.py`
  - 修改：队列满时丢弃旧消息或断开慢客户端
  - 验证：慢客户端不影响其他客户端

### 补充 2：订阅批处理动态调整

- [ ] **根据成功率动态调整批大小**
  - 文件：`simple_trade/api/subscription_optimizer.py`
  - 修改：成功率 >95% → 300，80-95% → 200，<80% → 100
  - 验证：网络抖动时自动降低批大小

### 补充 3：报价缓存 TTL 分级

- [ ] **持仓股 5s、策略股 10s、其他 15s**
  - 文件：`simple_trade/services/market_data/quote_cache.py`
  - 修改：按股票类型设置不同 TTL
  - 验证：持仓股报价始终最新

### 补充 4：连接健康主动探测

- [ ] **每 30s 发送心跳请求**
  - 文件：`simple_trade/core/connection/global_connection_manager.py`
  - 修改：调用 `get_global_state`，超时 5s 未响应即重连
  - 验证：更快发现僵尸连接

### 补充 5：错误码精细化处理

- [ ] **区分可重试 / 限流 / 不可重试错误**
  - 文件：`simple_trade/api/futu_client.py:_execute_with_retry`
  - 修改：限流错误等待 60s，参数错误立即失败
  - 验证：减少无效重试

---

## 验证清单

每个 Phase 完成后，执行以下验证：

1. **回归测试** — `python run_tests.py`
2. **链路健康面板** — 浏览器打开 `/api/monitoring/link-health`
3. **日志完整性** — `tail -f logs/*.log` 确认埋点生效
4. **降级演练** — 关停 OpenD 5min，前端收到降级通知
5. **性能对比** — 对比 P0 基线指标，P95 延迟应下降

---

## 参数调优（部署后跑 3 天 P0 再调整）

| 位置 | 当前 | 建议（国内部署） | 依据 |
|------|------|------------------|------|
| `futu_client.py` 重连冷却 | 10s | 2s 起步 + 指数退避 → 60s | 首次重连不该等 10s |
| `_execute_with_retry` 默认超时 | 15s | 动态 5–30s | 国内抖动大 |
| `subscription_optimizer.py` 批大小 | 300 | 200 | 降低单批失败面 |
| `subscription_optimizer.py` 批间延迟 | 0.5s | 0.3s | 加速恢复 |
| `async_quote_pusher.py` 首次报价超时 | 60s | 90s | 冷启动更慢 |
| `unified_data_cache.py` 内存阈值 | 80% 清空 | 70/80/90/95 分级 | 避免雪崩 |
| `quote_push_interval` | 5s | 保持 5s，但广播改异步 | 问题在广播阻塞 |

---

## 风险与回滚

**触发回滚条件**：
- 请求成功率 <95%
- 重连失败率 >10%
- 出现资金安全相关 BUG

**回滚步骤**：
1. LB 切换到旧系统（<5 分钟）
2. 停止新系统所有策略
3. 导出新系统的订单日志与持仓快照
4. 分析故障原因，修复后重新灰度

---

## 进度追踪

- [x] Phase 0：紧急清理（必须先做）✅ 2026-04-23
- [x] Phase 1：可观测性建设 ✅ 2026-04-23
- [x] Phase 2：连接与推送加固 ✅ 2026-04-23
- [x] Phase 3：缓存与多级降级 ✅ 2026-04-23
- [x] Phase 4：链路隔离与优先级 ✅ 2026-04-23
- [x] Phase 5：架构简化 ✅ 2026-04-23
- [x] Phase 6：数据层优化 ✅ 2026-04-23
- [ ] Phase 7：压测演练与灰度上线（需人工操作）

**总工期**：约 24 天（不含补充优化）

---

**最后更新**：2026-04-23  
**方案来源**：`C:\Users\ZHOUYICAN\.claude\plans\scalable-marinating-simon.md`

