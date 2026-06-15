# 富途交易系统

面向港美股的实时行情、信号筛选、盘中狙击、交易决策和监控系统。后端采用 FastAPI + Socket.IO + SQLite，前端采用 Next.js + React。

## 技术栈

| 层级 | 内容 |
| --- | --- |
| 后端 | Python、FastAPI、python-socketio、SQLite |
| 行情/交易 | Futu OpenD / 富途 OpenAPI |
| 前端 | Next.js 15、React 19、TypeScript、Tailwind CSS v4 |
| 策略 | StockScorer V2、IntradaySniper、MomentumEngine、DecisionEngine |
| AI | Gemini / Vertex AI，可选 Claude 兼容接口 |

## 当前主链路

```text
Futu OpenD
  -> QuoteService / TickerPushHandler
  -> AsyncQuotePusher / QuotePipeline
  -> IntradaySniper + MomentumEngine + StockScorer V2
  -> UnifiedTradeDecisionEngine
  -> signal_pipeline / trade_signals / Socket.IO
  -> Next.js 实时看板、个股详情、策略页面
```

当前正在使用的主策略是 `StockScorer V2` 的三套评分：`TREND`、`BREAKOUT`、`MOMENTUM`。`StrategyDispatcher` / `StrategyRegistry` 属于旧 `BaseStrategy` 链路，已从启动注册路径下线，仅保留历史兼容和追溯。

## 启动

服务器部署、FutuOpenD 和 systemd 配置见 [SERVER_DEPLOYMENT.md](docs/SERVER_DEPLOYMENT.md)。

本地脚本入口：

```powershell
scripts\start.bat
scripts\stop.bat
```

后端 ASGI 应用为 `simple_trade.asgi:app`，默认 API 端口 `5001`。前端位于 `futu-trade-frontend/`，默认开发端口 `3000`。

## 文档

从 [docs/README.md](docs/README.md) 开始阅读：

- [ARCHITECTURE.md](docs/ARCHITECTURE.md)：系统架构
- [COMPLETE_SYSTEM_FLOW.md](docs/COMPLETE_SYSTEM_FLOW.md)：完整业务流
- [SCORING_ARCHITECTURE.md](docs/SCORING_ARCHITECTURE.md)：V2 策略评分
- [ROUTES.md](docs/ROUTES.md)：API 路由清单
- [CONFIG_REFERENCE.md](docs/CONFIG_REFERENCE.md)：配置参考
- [WEBSOCKET_PROTOCOL.md](docs/WEBSOCKET_PROTOCOL.md)：Socket.IO 事件
- [RUNBOOK.md](docs/RUNBOOK.md)：运维手册
