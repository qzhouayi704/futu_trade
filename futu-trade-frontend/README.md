# 富途量化交易系统 - Next.js 前端

基于 Next.js 15.4 + React 19 + TypeScript 的现代化量化交易前端。

## 技术栈

- **框架**: Next.js 15.4 (App Router)
- **UI 库**: React 19
- **语言**: TypeScript 5.x
- **样式**: Tailwind CSS v4
- **状态管理**: Zustand 4.x
- **数据获取**: React Query 5.x
- **HTTP 客户端**: Axios 1.x
- **实时通信**: Socket.IO Client 4.7.x
- **图表库**: Lightweight Charts 4.x (TradingView)

## 项目结构

```
src/
├── app/                    # Next.js App Router
│   ├── api/               # API 代理层（转发到 Flask）
│   ├── layout.tsx         # 根布局
│   ├── page.tsx           # 首页
│   └── providers.tsx      # 全局 Provider
├── components/            # React 组件
│   └── common/           # 通用组件
├── lib/                   # 工具库
│   ├── api/              # API 客户端
│   ├── socket/           # Socket.IO 集成
│   ├── stores/           # Zustand 状态管理
│   └── utils/            # 工具函数
└── types/                 # TypeScript 类型定义
```

## 开发指南

### 安装依赖

```bash
npm install
```

### 启动开发服务器

```bash
npm run dev
```

访问 http://localhost:3001

### 构建生产版本

```bash
npm run build
npm start
```

## 环境变量

创建 `.env.local` 文件：

```env
# Flask 后端 API 地址
NEXT_PUBLIC_API_URL=http://localhost:5000
FLASK_API_URL=http://localhost:5000
```

## API 代理层

前端通过 Next.js API Routes 代理所有请求到 Flask 后端，解决跨域问题：

- `/api/stocks/*` → Flask `/api/stocks/*`
- `/api/quotes/*` → Flask `/api/quotes/*`
- `/api/trading/*` → Flask `/api/trading/*`
- `/api/strategy/*` → Flask `/api/strategy/*`
- `/api/system/*` → Flask `/api/system/*`
- `/api/config/*` → Flask `/api/config/*`

## 状态管理

使用 Zustand 管理全局状态：

- `useMonitorStore`: 监控状态（策略、信号、股票池）
- `useStockPoolStore`: 股票池状态（板块、股票、分页）
- `useTradingStore`: 交易状态（信号、持仓、记录）

## 实时通信

使用 Socket.IO 连接 Flask 后端，接收实时数据推送：

```typescript
import { useSocket } from "@/lib/socket";

const { socket, isConnected } = useSocket();

useEffect(() => {
  if (!socket) return;

  socket.on("signals_update", (data) => {
    // 处理信号更新
  });

  return () => {
    socket.off("signals_update");
  };
}, [socket]);
```

## 通用组件

- `Button`: 按钮组件（支持多种样式和加载状态）
- `Card`: 卡片容器
- `Table`: 表格组件（支持排序、分页）
- `Modal`: 模态框
- `Toast`: 消息提示（通过 `useToast` Hook 使用）
- `Loading`: 加载动画

## 工具函数

```typescript
import { formatPrice, formatPercent, formatTime } from "@/lib/utils";

// 格式化价格
formatPrice(123.456); // "123.46"

// 格式化百分比
formatPercent(12.345); // "12.35%"

// 格式化时间
formatTime(new Date()); // "14:30:25"
```

## 开发规范

- 文件不超过 300 行
- 每个文件夹不超过 8 个文件
- 使用 TypeScript 严格模式
- 组件使用函数式组件 + Hooks
- 状态管理使用 Zustand
- 数据获取使用 React Query

## 下一步计划

- [ ] 页面迁移（9个页面）
- [ ] 性能优化
- [ ] 响应式设计
- [ ] 单元测试
- [ ] E2E 测试

## License

ISC
