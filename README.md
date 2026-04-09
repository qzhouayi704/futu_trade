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
│   ├── api/                   # 富途API封装
│   ├── core/                  # 核心模块
│   │   ├── coordination/      # 协调器（广播、监控、策略调度）
│   │   ├── pipeline/          # 数据管道（行情处理）
│   │   ├── validation/        # 验证模块（风险、信号评分）
│   │   ├── exceptions/        # 异常处理
│   │   ├── state/             # 状态管理
│   │   ├── models/            # 数据模型
│   │   ├── events/            # 事件系统
│   │   └── container/         # 服务容器
│   ├── services/              # 业务服务
│   │   ├── initialization/    # 初始化服务
│   │   ├── core/              # 核心服务
│   │   ├── coordination/      # 协调服务
│   │   ├── trading/           # 交易服务
│   │   │   ├── execution/     # 订单执行
│   │   │   ├── risk/          # 风险管理
│   │   │   ├── profit/        # 止盈管理
│   │   │   └── aggressive/    # 激进策略
│   │   ├── analysis/          # 分析服务
│   │   │   ├── kline/         # K线分析
│   │   │   ├── heat/          # 热度分析
│   │   │   └── flow/          # 资金流向
│   │   ├── market_data/       # 行情数据
│   │   ├── realtime/          # 实时服务
│   │   ├── subscription/      # 订阅管理
│   │   ├── pool/              # 股票池
│   │   ├── alert/             # 告警服务
│   │   └── strategy/          # 策略服务
│   ├── strategy/              # 策略实现
│   ├── backtest/              # 回测系统
│   ├── database/              # 数据库
│   │   ├── core/              # 核心数据库
│   │   ├── models/            # 数据模型
│   │   └── migrations/        # 数据迁移
│   ├── routers/               # API路由
│   ├── websocket/             # WebSocket
│   ├── config/                # 配置管理
│   └── utils/                 # 工具函数
│       ├── converters.py      # 类型转换
│       ├── error_parsers.py   # 错误解析
│       ├── error_handling.py  # 错误处理装饰器
│       ├── base_model.py      # 数据转换基类
│       └── script_helper.py   # 脚本工具
├── futu-trade-frontend/       # 前端代码
├── scripts/                   # 脚本工具
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

1. **文件大小限制**
   - Python文件不超过300行
   - 每个目录不超过8个文件

2. **架构原则**
   - 避免循环依赖
   - 使用事件驱动解耦
   - 单一职责原则
   - 依赖注入

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
