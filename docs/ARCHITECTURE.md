# 系统架构说明

## 架构概览

富途交易系统采用**事件驱动 + 分层架构**设计，基于 FastAPI + React 技术栈。

```
┌─────────────────────────────────────────────────────────┐
│           前端层 (React 19 + Next.js 15)                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │🎯 驾驶舱 │  │📡 选股台 │  │📊 复盘   │  │⚙️ 设置  │ │
│  │ 信号流   │  │ 盘后优选 │  │ 模拟交易 │  │ 系统配置│ │
│  │ 持仓面板 │  │ 板块热度 │  │ 信号总览 │  │ 股票池  │ │
│  │ 决策日志 │  │ 选股工作台│ │ 交易决策 │  │ 决策助理│ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │
└─────────────────────────────────────────────────────────┘
                          ↕ HTTP REST + Socket.IO
┌─────────────────────────────────────────────────────────┐
│                API 层 (FastAPI, 27 个路由模块)            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │ system/  │  │ market/  │  │ trading/ │  │  data/  │ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │
└─────────────────────────────────────────────────────────┘
                          ↕
┌─────────────────────────────────────────────────────────┐
│              服务层 (Services, 12 个子模块)               │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌───────┐ │
│  │ 交易   │ │Scalping│ │ 策略   │ │ 分析   │ │ 告警  │ │
│  └────────┘ └────────┘ └────────┘ └────────┘ └───────┘ │
└─────────────────────────────────────────────────────────┘
                          ↕
┌─────────────────────────────────────────────────────────┐
│                核心层 (Core)                              │
│  ┌────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │QuotePipeline│ │SystemCoor│ │StateManag│ │EventBus  │ │
│  └────────────┘ └──────────┘ └──────────┘ └──────────┘ │
└─────────────────────────────────────────────────────────┘
                          ↕
┌─────────────────────────────────────────────────────────┐
│              数据层 (Database + 外部 API)                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │SQLite WAL│  │ 富途API  │  │ Gemini   │              │
│  └──────────┘  └──────────┘  └──────────┘              │
└─────────────────────────────────────────────────────────┘
```

## 服务容器（三层架构）

ServiceContainer 按依赖顺序分三层初始化：

```
ServiceContainer
├── CoreServices（核心层，最先初始化）
│   ├── db_manager          — DatabaseManager（异步 SQLite）
│   ├── futu_client         — FutuClient（行情+交易连接）
│   ├── subscription_manager — SubscriptionManager（底层订阅）
│   ├── quote_service       — QuoteService（报价查询）
│   └── stock_data_service  — StockDataService（股票数据）
│
├── DataServices（数据层，依赖核心层）
│   ├── subscription_helper — SubscriptionHelper（高层订阅管理）
│   ├── realtime_query      — RealtimeQuery（实时数据查询）
│   ├── kline_service       — KlineDataService（K线）
│   ├── plate_manager       — PlateManager（板块）
│   ├── stock_pool_service  — StockPoolService（股票池）
│   └── data_initializer    — DataInitializer（初始化编排）
│
└── BusinessServices（业务层，依赖数据层）
    ├── trade_service           — TradeService（交易信号+自动交易）
    ├── futu_trade_service      — FutuTradeService（富途下单）
    ├── risk_coordinator        — RiskCoordinator（风控协调）
    ├── strategy_monitor_service — StrategyMonitorService（策略监控）
    ├── strategy_screening_service — StrategyScreeningService（策略筛选）
    ├── alert_service           — AlertChecker（预警）
    ├── hot_stock_service       — HotStockCoordinator（热门股票）
    ├── scalping_engine         — ScalpingEngine（日内超短线）
    ├── decision_advisor        — DecisionAdvisor（AI决策助理）
    └── ...（共 19 个业务服务）
```

**顶层服务（在 app.py lifespan 中创建，挂载到 container）**：

| 属性 | 类 | 说明 |
|------|---|------|
| `quote_pipeline` | QuotePipeline | 行情处理管道 |
| `system_coordinator` | SystemCoordinator | 系统协调器 |
| `quote_pusher` | AsyncQuotePusher | 行情推送循环 |
| `state_manager` | StateManager | 全局状态管理 |

## 核心数据流

### 1. 系统启动流程

```
FastAPI lifespan 启动
  → ConfigManager 加载配置
  → ServiceContainer 三层初始化（Core → Data → Business）
  → QuotePipeline 创建（显式注入依赖）
  → SystemCoordinator 创建
  → initialize_system_data()（同步持仓、初始化订阅）
  → AsyncQuotePusher 启动（后台任务）
  → auto_start_scalping()（后台任务）
  → HighTurnoverEnricher 启动（后台任务）
  → 自动恢复监控（如果上次未正常关闭）
```

### 2. 实时行情推送流程

```
AsyncQuotePusher（定时循环）
  → SubscriptionManager 获取已订阅股票
  → QuoteService 批量获取报价
  → QuotePipeline.run_pipeline()
    → 更新 QuoteCache
    → PriceMonitorService 检查价格条件
    → StrategyMonitorService 策略检测
    → AlertChecker 预警检查
    → RiskCoordinator 风控检查
    → PipelineBroadcast 广播到 WebSocket
  → SocketManager → 前端
```

### 3. Scalping 引擎数据流

支持 `inline`（单进程）和 `process`（子进程）两种模式。

```
ScalpingFactory（根据 config 选择模式）
  → inline: ScalpingEngine
  → process: ScalpingProcessManager → ScalpingWorker（子进程）

数据流:
  DataPoller（定时轮询 Tick + OrderBook）
    → DataDispatcher（分发到各计算器）
      ├→ DeltaCalculator（买卖 Delta）
      ├→ POCCalculator（价格聚集点）
      ├→ TapeVelocityMonitor（成交速度）
      ├→ OFICalculator（订单流失衡）
      └→ TickCredibilityFilter（数据可信度）
    → SignalEngine（综合判断）
      ├→ SpoofingFilter（虚假挂单检测）
      ├→ OrderFlowDivergenceDetector（订单流背离）
      ├→ BreakoutSurvivalMonitor（突破存活率）
      ├→ VwapExtensionGuard（VWAP 偏离保护）
      └→ StopLossMonitor（止损监控）
    → ScalpingPersistence（DatabaseWriteQueue 异步写入）
    → WebSocket 推送 → 前端 ScalpingChart
```

### 4. 策略筛选流程

```
用户请求 → strategy_screening.py 路由
  → StrategyScreeningService
    → StrategyDispatcher.dispatch_batch()
      → StrategyRegistry 获取策略实例
      → BaseStrategy.check_signal()（各策略实现）
      → SignalScorer 评分
    → DatabaseManager 保存信号
  → 返回结果
```

### 5. 风控检查流程

```
RiskCoordinator.check_all_risks(quotes, positions)
  按优先级依次检查：
  1. PriceMonitorService（用户设定的目标价，urgency=9）
  2. DynamicStopLossStrategy（动态止损，urgency=8）
  3. LotTakeProfitService（分仓止盈，urgency=7）
  4. LotOrderTakeProfitService（订单止盈，urgency=6）
  5. ScreeningEngine（策略止损，urgency=5）
  → 同一股票去重（保留最高优先级）
  → 频率控制（非价格监控模块间隔 ≥10s）
```

## 状态管理

StateManager 管理 6 个子状态：

| 子状态 | 职责 |
|--------|------|
| `QuoteCache` | 行情数据缓存（TTL 可配置） |
| `TradingState` | 交易状态（持仓、订单） |
| `PoolState` | 股票池状态 |
| `InitProgress` | 初始化进度 |
| `MonitorState` | 监控运行状态 |
| `SubscriptionState` | 订阅状态 |

## 策略体系

| 策略类 | 文件 | 说明 |
|--------|------|------|
| `PricePositionLiveStrategy` | `strategy/price_position_live_strategy.py` | 高抛低吸（主力策略） |
| `SwingStrategy` | `strategy/swing_strategy.py` | 波段交易 |
| `AggressiveStrategy` | `strategy/aggressive_strategy.py` | 激进龙头股 |
| `TrendReversalStrategy` | `strategy/trend_reversal/` | 趋势反转 |

所有策略继承 `BaseStrategy`，通过 `StrategyRegistry` 注册，由 `StrategyDispatcher` 调度。

## 数据库

- **引擎**: SQLite（WAL 模式）
- **路径**: `simple_trade/data/trade.db`
- **异步写入**: 通过 `DatabaseWriteQueue` 实现非阻塞写入
- **表定义**: `database/models/`
- **查询方法**: `database/queries/`
- **外键规范**: 核心交易表用 `stock_id INTEGER` 外键；辅助表用 `stock_code TEXT`

## 设计模式

| 模式 | 应用 |
|------|------|
| 依赖注入 | ServiceContainer 三层容器 |
| 事件驱动 | EventBus 解耦订阅/取消订阅事件 |
| 策略模式 | BaseStrategy + 各策略实现 |
| 装饰器 | `@handle_db_error`、`@handle_api_error`、`@retry_on_error` |
| 协调器 | SystemCoordinator（只协调，不含业务逻辑） |
| 工厂 | ScalpingFactory（根据配置创建引擎） |

## 前端架构（4 视图交易员驾驶舱）

> 2026-06 重构：从 30+ 独立页面精简为 4 视图 Tab 架构

### 导航结构

| 视图 | 路由 | 功能 |
|------|------|------|
| 🎯 驾驶舱 | `/` | 盘中单屏作战（不切页面） |
| 📡 选股台 | `/discovery` | 盘前/盘后选股研究（4 Tab） |
| 📊 复盘中心 | `/review` | 交易记录与信号追踪（4 Tab） |
| ⚙️ 系统设置 | `/settings` | 配置管理 + 股票池 + 决策助理 |

### 驾驶舱组件（`components/cockpit/`）

```
CockpitPage (app/page.tsx)
├── StatusBar        — WS连接 + 监控状态 + 启停按钮
├── StrategyPanel    — 策略面板
├── SignalFeed       — 统一信号流（筛选Tab + UnifiedSignalFeed）
├── PositionPanel    — 持仓面板（实时盈亏 + Sniper止盈状态）
└── DecisionLog      — 决策日志（DB持久化 + WS实时推送）
```

### 选股台 Tab（`discovery/page.tsx`）

| Tab | 数据源 |
|-----|--------|
| 🌙 盘后优选 | `OvernightScreenCard` |
| 🔥 板块热度 | `PlatesPage`（懒加载） |
| 🎯 选股工作台 | `StockPickerPage`（懒加载） |
| 🔍 个股分析 | `StockDetailPage`（懒加载） |

### 复盘中心 Tab（`review/page.tsx`）

| Tab | 数据源 |
|-----|--------|
| 💰 模拟交易 | `SimulatedTradesPage`（懒加载） |
| 🔫 信号总览 | `SniperSignalsPage`（懒加载） |
| ⚡ 交易决策 | `PreCheckPage`（懒加载） |
| 📰 热点新闻 | `NewsPage`（懒加载） |

### 前端数据流

```
后端 WebSocket → Socket.IO
  ├── quotes_update      → 实时价格 → PositionPanel 盈亏更新
  ├── signal_pipeline    → 决策流水 → DecisionLog 实时追加
  ├── sniper_signal      → 信号提示 → SignalFeed 信号卡片
  └── positions_update   → 持仓变动 → 触发 refetchPositions()

后端 REST API
  ├── /system/status          → StatusBar 系统状态
  ├── /monitor/health         → StatusBar 订阅/股票池数
  ├── /sniper/trailing-status → PositionPanel Sniper追踪状态
  └── /sniper/signal-pipeline → DecisionLog 历史记录（DB）
```

### 前端 API 层（`lib/api/`）

| 模块 | 端点前缀 |
|------|----------|
| `system.ts` | `/system/`, `/monitor/` |
| `sniper.ts` | `/sniper/` |
| `trade.ts` | `/trading/` |
| `stock.ts` | `/stocks/` |
| `strategy.ts` | `/strategy/` |
| `config.ts` | `/config/` |
| `analysis.ts` | `/analysis/` |

## 更多信息

- API 端点清单：[API_REFERENCE.md](API_REFERENCE.md)
- 部署指南：[DEPLOYMENT.md](DEPLOYMENT.md)
- 故障排查：[TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- Scalping Ticker 持久化设计：[ticker_persistence.md](ticker_persistence.md)
- 信号流水架构：[SIGNAL_PIPELINE.md](SIGNAL_PIPELINE.md)
