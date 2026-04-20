# 富途交易系统 (Futu Trade System)

基于富途OpenAPI的智能量化交易系统，提供实时行情监控、策略筛选、信号生成和自动交易功能。

## 📋 目录

- [系统概述](#系统概述)
- [核心功能](#核心功能)
- [技术架构](#技术架构)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [配置说明](#配置说明)
- [开发指南](#开发指南)

## 系统概述

富途交易系统是一个完整的量化交易解决方案，集成了：

- **实时行情监控**：WebSocket实时推送，支持港股/美股/A股
- **策略筛选引擎**：多策略并行筛选，智能信号生成
- **风险控制系统**：动态止损、仓位管理、风险评估
- **自动交易执行**：订单管理、持仓跟踪、交易确认
- **回测分析系统**：历史数据回测、策略优化、绩效分析

## 核心功能

### 1. 实时行情服务
- WebSocket实时行情推送
- 多市场支持（港股/美股/A股）
- 智能订阅管理（自动额度控制）
- 行情缓存与分发

### 2. 策略筛选系统
- 高抛低吸策略
- 波段交易策略
- 激进策略（龙头股筛选）
- 自定义策略扩展

### 3. 信号生成与评分
- 多维度信号评分
- 板块强度分析
- 资金流向分析
- 技术指标综合评估

### 4. 风险控制
- 动态止损策略
- 仓位限制管理
- 风险等级评估
- 紧急风控触发

### 5. 交易执行
- 自动下单执行
- 订单状态跟踪
- 持仓实时更新
- 交易确认机制

### 6. 回测分析
- 历史数据回测
- 策略参数优化
- 绩效指标分析
- 回测报告导出

## 技术架构

### 后端技术栈
- **Python 3.11+**
- **FastAPI**: 高性能Web框架
- **SQLite**: 轻量级数据库
- **富途OpenAPI**: 行情与交易接口
- **WebSocket**: 实时通信

### 前端技术栈
- **React 19**: UI框架
- **TypeScript**: 类型安全
- **Tailwind CSS v4**: 样式框架
- **Socket.IO**: 实时通信

### 架构模式
- **事件驱动架构**: 解耦服务间依赖
- **分层架构**: API → Service → Core → Database
- **依赖注入**: 服务容器管理
- **装饰器模式**: 错误处理与重试

## 快速开始

### 环境要求
- Python 3.11+
- Node.js 18+
- 富途牛牛客户端
- 富途OpenAPI账号

### 后端启动

```bash
# 1. 安装依赖（使用 uv）
uv sync

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入富途API配置

# 3. 启动后端服务
./scripts/start_backend.sh
```

### 前端启动

```bash
# 1. 进入前端目录
cd futu-trade-frontend

# 2. 安装依赖
npm install

# 3. 启动开发服务器
npm run dev
```

### 访问系统
- 前端界面: http://localhost:5173
- 后端API: http://localhost:8000
- API文档: http://localhost:8000/docs

## 项目结构

```
futu_trade_sys/
├── simple_trade/              # 后端核心代码
│   ├── app.py                 # FastAPI 入口 + lifespan
│   ├── api/                   # 富途 API 封装（FutuClient、SubscriptionManager）
│   ├── core/                  # 核心框架层
│   │   ├── container/         # ServiceContainer（三层服务容器）
│   │   ├── pipeline/          # QuotePipeline（行情处理管道）
│   │   ├── coordination/      # SystemCoordinator + StrategyDispatcher
│   │   ├── state/             # StateManager（全局状态）
│   │   ├── events/            # EventBus（事件总线）
│   │   ├── validation/        # 风险验证、信号评分
│   │   ├── models/            # 核心数据模型
│   │   └── exceptions/        # 统一异常处理
│   ├── services/              # 业务服务层（12 个子模块）
│   │   ├── core/              # AsyncQuotePusher、数据初始化
│   │   ├── trading/           # 交易执行、风控、止盈、激进策略
│   │   │   ├── execution/     # 订单执行（OrderManager、PositionManager）
│   │   │   ├── risk/          # 风险管理（RiskCoordinator、动态止损）
│   │   │   ├── profit/        # 止盈管理（分仓止盈、订单止盈）
│   │   │   └── aggressive/    # 激进策略（自动交易）
│   │   ├── scalping/          # 日内超短线引擎
│   │   │   ├── calculators/   # Delta、POC、VWAP、OFI 等计算器
│   │   │   ├── detectors/     # 虚假挂单、背离、突破等检测器
│   │   │   └── scheduler/     # 调度器（轮询、健康监控）
│   │   ├── strategy/          # 多策略管理、筛选引擎
│   │   ├── market_data/       # 热门股票、板块、K线、盘口
│   │   ├── analysis/          # 分析服务（热度、资金流、K线）
│   │   ├── alert/             # 价格预警 + 企业微信告警
│   │   ├── advisor/           # AI 决策助理（Gemini）
│   │   ├── news/              # 新闻爬虫 + Gemini 分析
│   │   ├── pool/              # 股票池管理
│   │   ├── realtime/          # 实时数据查询
│   │   └── subscription/      # 订阅管理
│   ├── strategy/              # 策略实现（高抛低吸、波段、激进、趋势反转）
│   ├── database/              # SQLite 数据库层
│   ├── routers/               # API 路由（27 个路由模块）
│   │   ├── system/            # 系统管理
│   │   ├── market/            # 行情
│   │   ├── trading/           # 交易
│   │   └── data/              # 数据管理
│   ├── websocket/             # Socket.IO（实时推送）
│   ├── config/                # 配置管理
│   └── utils/                 # 工具函数
├── futu-trade-frontend/       # 前端代码（React 19 + Next.js 15 + Tailwind v4）
├── scripts/                   # 运维脚本
├── tests/                     # 测试代码
└── docs/                      # 文档
```

## 配置说明

### 环境变量配置 (.env)

```bash
# 富途API配置
FUTU_HOST=127.0.0.1
FUTU_PORT=11111
FUTU_TRADE_PASSWORD=your_password

# 数据库配置
DATABASE_PATH=./data/trading.db

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=./logs/app.log

# 服务配置
API_HOST=0.0.0.0
API_PORT=8000
```

### 策略配置

在 `simple_trade/config/service_configs.py` 中配置各个服务的参数：

```python
from simple_trade.config.service_configs import (
    RiskConfig,
    TradingConfig,
    ScreeningConfig
)

# 风险控制配置
risk_config = RiskConfig(
    max_position_ratio=0.3,
    stop_loss_ratio=0.05,
    take_profit_ratio=0.15
)

# 交易配置
trading_config = TradingConfig(
    enable_auto_trade=False,
    max_order_amount=100000.0
)
```

## 开发指南

### 代码规范

遵循 `CLAUDE.md` 中的编码规范：

1. **文件拆分原则**
   - 核心原则：功能颗粒度拆分，而非固定行数
   - 超过约 400 行时审视是否存在职责混杂
   - 每层文件夹中的文件尽可能不超过 12 个

2. **架构原则**
   - 避免循环依赖
   - 使用事件驱动解耦
   - 单一职责原则
   - 依赖注入（ServiceContainer）

3. **错误处理**
   - 使用装饰器统一处理错误
   - 记录详细日志
   - 返回标准错误格式

### 添加新策略

1. 在 `simple_trade/strategy/` 创建策略类
2. 继承 `BaseStrategy` 基类
3. 实现 `check_signal()` 方法
4. 在 `strategy_registry.py` 注册策略

示例：

```python
from simple_trade.strategy.base_strategy import BaseStrategy

class MyStrategy(BaseStrategy):
    def check_signal(self, stock_data, kline_data):
        # 实现策略逻辑
        if condition:
            return {
                'signal_type': 'BUY',
                'signal_price': price,
                'reason': '策略触发原因'
            }
        return None
```

### 运行测试

```bash
# 运行所有测试
python run_tests.py

# 运行数据库测试
python run_tests.py --db

# 运行API测试
python run_tests.py --api
```

### 提交代码

```bash
# 1. 运行测试确保通过
python run_tests.py

# 2. 提交代码
git add .
git commit -m "feat: 添加新功能"

# 3. 推送到远程
git push origin feature/your-feature
```

## 文档

- [API参考文档](docs/API_REFERENCE.md)
- [系统架构说明](docs/ARCHITECTURE.md)
- [部署指南](docs/DEPLOYMENT.md)
- [故障排查](docs/TROUBLESHOOTING.md)

## 许可证

MIT License

## 联系方式

如有问题或建议，请提交 Issue 或 Pull Request。
