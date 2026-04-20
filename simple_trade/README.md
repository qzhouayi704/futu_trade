# 富途量化交易系统 - 后端

基于 FastAPI + SQLite 的量化交易后端服务。

## 技术栈

- **Python 3.11+**
- **FastAPI**：Web 框架（ASGI）
- **Socket.IO**：实时行情推送
- **SQLite**：WAL 模式，异步读写
- **富途 OpenAPI**：行情与交易接口
- **Gemini API**：AI 新闻分析 + 决策助理

## 启动

```bash
# 使用脚本启动（推荐）
./scripts/start.bat

# 或手动启动
cd .. && uv run uvicorn simple_trade.asgi:app --host 0.0.0.0 --port 8000
```

## 目录结构

```
simple_trade/
├── app.py              # FastAPI 入口 + lifespan 生命周期管理
├── asgi.py             # ASGI 入口（Socket.IO 挂载点）
├── dependencies.py     # FastAPI 依赖注入
├── config.json         # 运行时配置
├── api/                # 富途 API 封装（FutuClient、SubscriptionManager）
├── core/               # 核心框架（ServiceContainer、QuotePipeline、EventBus）
├── services/           # 业务服务（12 个子模块）
├── strategy/           # 策略实现（高抛低吸、波段、激进、趋势反转）
├── database/           # 数据库层（models/queries/migrations）
├── routers/            # API 路由（27 个模块，按 system/market/trading/data 分组）
├── websocket/          # Socket.IO 实时推送
├── config/             # 配置管理（ConfigManager）
└── utils/              # 工具函数
```

## 架构要点

- **三层服务容器**：CoreServices → DataServices → BusinessServices，按依赖顺序初始化
- **行情管道**：AsyncQuotePusher → QuotePipeline → 缓存/监控/策略/广播
- **Scalping 引擎**：支持 inline（单进程）和 process（子进程）两种模式
- **统一风控**：RiskCoordinator 按优先级协调 5 个风控模块

## 详细文档

- [架构说明](../docs/ARCHITECTURE.md)
- [API 端点清单](../docs/API_REFERENCE.md)
- [部署指南](../docs/DEPLOYMENT.md)
- [功能规格](../FUNCTION.md)
- [编码规范](../CLAUDE.md)
