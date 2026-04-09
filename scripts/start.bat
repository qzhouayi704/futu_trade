@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   富途量化交易系统 - 启动脚本
echo ========================================
echo.

:: 切换到项目根目录
cd /d "%~dp0.."
set "PROJECT_ROOT=%CD%"

:: ========================================
:: 选择启动模式
:: ========================================
echo 请选择启动模式:
echo   [1] 开发模式 - 后端热重载 + 前端热重载 (默认)
echo   [2] 生产模式 - 无热重载
echo   [3] 仅后端 - 开发模式(热重载)
echo   [4] 仅后端 - 生产模式
echo   [5] 仅前端
echo.
set "CHOICE=1"
set /p "CHOICE=请输入选项 [1-5]: "

set "START_BACKEND=1"
set "START_FRONTEND=1"
set "RELOAD=1"

if "%CHOICE%"=="2" (
    set "RELOAD=0"
)
if "%CHOICE%"=="3" (
    set "START_FRONTEND=0"
)
if "%CHOICE%"=="4" (
    set "START_FRONTEND=0"
    set "RELOAD=0"
)
if "%CHOICE%"=="5" (
    set "START_BACKEND=0"
)

echo.

:: ========================================
:: 环境检查
:: ========================================
if "!START_BACKEND!"=="1" (
    if not exist ".venv" (
        echo [错误] 未找到虚拟环境 .venv
        echo 请先运行: uv venv
        pause
        exit /b 1
    )
)

:: 创建日志目录
if not exist "logs" mkdir logs

:: ========================================
:: 启动后端服务
:: ========================================
if "!START_BACKEND!"=="1" (
    if "!RELOAD!"=="1" (
        echo [后端] 开发模式（热重载）
        start "Backend-FastAPI-Dev" cmd /k "cd /d "%PROJECT_ROOT%" && uv run uvicorn simple_trade.asgi:app --host 0.0.0.0 --port 5001 --reload --reload-delay 2 --log-level info"
    ) else (
        echo [后端] 生产模式
        start "Backend-FastAPI-Prod" cmd /k "cd /d "%PROJECT_ROOT%" && uv run uvicorn simple_trade.asgi:app --host 0.0.0.0 --port 5001 --log-level info"
    )
    timeout /t 3 /nobreak >nul
    echo [后端] 已启动 - http://localhost:5001
    echo         API文档: http://localhost:5001/docs
    echo.
)

:: ========================================
:: 启动前端服务
:: ========================================
if "!START_FRONTEND!"=="1" (
    set "FRONTEND_PATH=%PROJECT_ROOT%\futu-trade-frontend"

    if not exist "!FRONTEND_PATH!" (
        echo [前端] 未找到前端目录: !FRONTEND_PATH!
        echo [前端] 跳过前端启动
        goto :end
    )

    if not exist "!FRONTEND_PATH!\node_modules" (
        echo [前端] 未找到 node_modules，正在安装依赖...
        cd /d "!FRONTEND_PATH!"
        call npm install
        if !ERRORLEVEL! NEQ 0 (
            echo [前端] 依赖安装失败
            cd /d "%PROJECT_ROOT%"
            goto :end
        )
        cd /d "%PROJECT_ROOT%"
    )

    echo [前端] 启动中...
    start "Frontend-Next-Dev" cmd /k "cd /d "!FRONTEND_PATH!" && npm run dev"
    timeout /t 3 /nobreak >nul
    echo [前端] 已启动 - http://localhost:3000
    echo.
)

:end
echo ========================================
echo [完成] 系统启动完成
echo ========================================
echo.
if "!START_BACKEND!"=="1" echo   后端: http://localhost:5001
if "!START_FRONTEND!"=="1" echo   前端: http://localhost:3000
echo.
echo   停止服务: scripts\stop.bat
echo.

pause
