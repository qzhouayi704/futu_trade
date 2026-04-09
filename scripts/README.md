# 富途量化交易系统 - 启动脚本说明

本目录包含系统的所有启动、停止和管理脚本。

## 📋 脚本清单

### FastAPI 版本（推荐使用）

#### 1. `start_new_prod.bat` - 完整启动（生产模式）⭐ 推荐
**用途**: 一键启动完整系统，包括 FastAPI 后端服务和前端服务（生产模式，无热重载）

**端口**:
- 后端 (FastAPI): `5001`
- 前端 (Next.js): `3000`

**功能**:
- ✅ 自动检查虚拟环境
- ✅ 自动安装缺失的依赖 (uvicorn, fastapi, python-socketio)
- ✅ 自动检查前端依赖 (node_modules)
- ✅ 在新窗口中启动服务
- ✅ 显示详细的启动信息和访问地址
- ✅ 无热重载，稳定性优先
- ✅ 不会出现 `asyncio.CancelledError` 错误

**使用方法**:
```batch
cd scripts
start_new_prod.bat
```

**访问地址**:
- 后端 API 文档: http://localhost:5001/docs
- 后端健康检查: http://localhost:5001/health
- 前端应用: http://localhost:3000

---

#### 2. `start_new_dev.bat` - 完整启动（开发模式）
**用途**: 一键启动完整系统，包括 FastAPI 后端服务和前端服务（开发模式，支持热重载）

**端口**:
- 后端 (FastAPI): `5001`
- 前端 (Next.js): `3000`

**功能**:
- ✅ 自动检查虚拟环境
- ✅ 自动安装缺失的依赖
- ✅ 自动检查前端依赖
- ✅ 在新窗口中启动服务
- ✅ 支持热重载（代码修改后自动重启）
- ✅ 添加 `--reload-delay 2` 延迟重载，减少资源清理问题

**使用方法**:
```batch
cd scripts
start_new_dev.bat
```

**注意事项**:
- 热重载可能导致资源未完全清理
- 如遇到 `asyncio.CancelledError` 错误，请使用生产模式 `start_new_prod.bat`

---

#### 3. `start_new.bat` - 完整启动（兼容旧版）
**用途**: 一键启动完整系统（兼容旧版，使用热重载）

**说明**: 这是原有的启动脚本，保留用于兼容性。建议使用 `start_new_prod.bat` 或 `start_new_dev.bat`。

**使用方法**:
```batch
cd scripts
start_new.bat
```

---

#### 4. `quick_start_fastapi.bat` - 快速启动后端
**用途**: 快速启动 FastAPI 后端服务（仅后端，不启动前端）

**端口**: `5001`

**特点**:
- 在当前窗口中运行
- 适合调试和开发
- 启动速度快

**使用方法**:
```batch
cd scripts
quick_start_fastapi.bat
```

---

#### 5. `stop_new.bat` - 停止所有服务
**用途**: 一键停止所有正在运行的服务

**功能**:
- 停止 Flask 后端服务 (端口 5000)
- 停止 FastAPI 后端服务 (端口 5001)
- 停止前端服务 (端口 3000)
- 关闭相关窗口

**使用方法**:
```batch
cd scripts
stop_new.bat
```

---

### Flask 版本（兼容性保留）

#### 6. `start.bat` - Flask 版本启动
**用途**: 启动原始的 Flask 版本后端 + 前端

**端口**:
- 后端 (Flask): `5000`
- 前端 (Next.js): `3000`

**使用方法**:
```batch
cd scripts
start.bat
```

---

#### 7. `stop.bat` - Flask 版本停止
**用途**: 停止 Flask 版本的服务

**使用方法**:
```batch
cd scripts
stop.bat
```

---

### 单独启动脚本

#### 8. `start_fastapi.bat` - FastAPI 生产模式启动（仅后端）
**用途**: FastAPI 的生产模式启动脚本（无热重载，稳定性优先）

**端口**: `5001`

**特点**:
- 无热重载，避免 lifespan 重复执行导致的资源泄漏
- 适合生产环境或稳定性要求高的场景
- 修改代码后需要手动重启服务

**使用方法**:
```batch
cd scripts
start_fastapi.bat
```

---

#### 9. `start_fastapi_dev.bat` - FastAPI 开发模式启动（仅后端）
**用途**: FastAPI 的开发模式启动脚本（支持热重载）

**端口**: `5001`

**特点**:
- 启用热重载，代码修改后自动重启
- 适合开发调试
- 添加了 `--reload-delay 2` 延迟重载，减少资源清理问题

**使用方法**:
```batch
cd scripts
start_fastapi_dev.bat
```

**注意事项**:
- 热重载可能导致资源未完全清理
- 如遇到 `asyncio.CancelledError` 错误，请使用生产模式 `start_fastapi.bat`

---

## 🚀 快速开始指南

### 第一次使用（推荐）

1. **启动完整系统（生产模式）**:
   ```batch
   cd d:\Program Files\futu_trade_sys\scripts
   start_new_prod.bat
   ```

2. **等待服务启动** (约 5-10 秒)

3. **访问应用**:
   - 打开浏览器访问: http://localhost:3000
   - API 文档: http://localhost:5001/docs

4. **停止系统**:
   ```batch
   cd scripts
   stop_new.bat
   ```

### 开发调试（支持热重载）

如果需要代码修改后自动重启:
```batch
cd scripts
start_new_dev.bat
```

### 只调试后端 API

如果只需要调试后端 API（生产模式）:
```batch
cd scripts
start_fastapi.bat
```

如果需要热重载（开发模式）:
```batch
cd scripts
start_fastapi_dev.bat
```

然后在浏览器访问 http://localhost:5001/docs 查看 API 文档。

---

## 📊 版本对比

| 特性 | Flask 版本 | FastAPI 版本 |
|------|-----------|-------------|
| 端口 | 5000 | 5001 |
| 异步支持 | ❌ | ✅ |
| API 文档 | ❌ | ✅ (Swagger/ReDoc) |
| 性能 | 一般 | 高 |
| WebSocket | Socket.IO | Socket.IO (异步) |
| 类型检查 | ❌ | ✅ (Pydantic) |
| 维护状态 | 兼容保留 | 主要开发 |

---

## ⚠️ 注意事项

1. **端口冲突**:
   - Flask (5000) 和 FastAPI (5001) 使用不同端口，可以同时运行
   - 如需同时运行，确保两个端口都未被占用

2. **虚拟环境**:
   - 所有脚本都会自动检查和使用 `.venv` 虚拟环境
   - 首次运行前确保已创建虚拟环境: `uv venv`

3. **依赖安装**:
   - `start_new.bat` 会自动安装缺失的依赖
   - 如遇到依赖问题，手动运行: `uv pip install -r simple_trade/requirements.txt`

4. **日志文件**:
   - 所有日志存储在项目根目录的 `logs/` 文件夹
   - 后端日志: 查看后端窗口输出

5. **前端开发**:
   - 前端使用 Next.js 15.4 和 React 19
   - 如前端依赖有更新，先运行: `cd futu-trade-frontend && npm install`

---

## 🔧 故障排查

### 问题: 启动失败，提示找不到虚拟环境

**解决**: 在项目根目录创建虚拟环境
```batch
cd d:\Program Files\futu_trade_sys
uv venv
```

### 问题: 端口被占用

**解决**: 运行 `stop_new.bat` 停止所有服务，或手动结束占用端口的进程
```batch
# 查看端口占用
netstat -ano | findstr :5001
netstat -ano | findstr :3000

# 结束进程 (替换 <PID> 为实际进程ID)
taskkill /F /PID <PID>
```

### 问题: uvicorn 未安装

**解决**: `start_new.bat` 会自动安装，或手动安装
```batch
.venv\Scripts\activate
pip install uvicorn fastapi python-socketio
```

### 问题: 前端依赖缺失

**解决**:
```batch
cd futu-trade-frontend
npm install
```

---

## 📝 开发建议

1. **日常开发**: 使用 `start_new.bat` 启动完整系统
2. **API 调试**: 使用 `quick_start_fastapi.bat` 只启动后端
3. **前端开发**:
   ```batch
   # 启动后端
   quick_start_fastapi.bat

   # 另开终端启动前端
   cd futu-trade-frontend
   npm run dev
   ```
4. **生产部署**: 建议使用 systemd 或 supervisor 管理服务

---

## 📚 相关文档

- [FastAPI 迁移指南](../FASTAPI_MIGRATION.md)
- [项目任务清单](../TODO.md)
- [API 测试脚本](../test_fastapi.py)

---

## 更新日志

- **2026-02-10**:
  - 修复 FastAPI 启动时的 `asyncio.CancelledError` 错误
  - 创建生产模式和开发模式的启动脚本
  - 添加 `start_new_prod.bat` - 完整启动（生产模式，无热重载）
  - 添加 `start_new_dev.bat` - 完整启动（开发模式，支持热重载）
  - 添加 `start_fastapi_dev.bat` - 仅后端（开发模式，支持热重载）
  - 修改 `start_fastapi.bat` - 仅后端（生产模式，无热重载）
  - 改进异常处理和资源清理逻辑

- **2026-02-02**:
  - 创建 FastAPI 版本启动脚本 (`start_new.bat`, `stop_new.bat`, `quick_start_fastapi.bat`)
  - 添加自动依赖检查和安装功能
  - 支持 Flask 和 FastAPI 双版本共存
