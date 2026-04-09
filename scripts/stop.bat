@echo off
setlocal enabledelayedexpansion

echo ========================================
echo 富途量化交易系统 - 停止脚本
echo ========================================
echo.

:: 切换到项目根目录
cd /d "%~dp0.."
set "PROJECT_ROOT=%CD%"

echo [信息] 正在停止服务...
echo.

:: ========================================
:: 1. 通过端口关闭进程
:: ========================================

:: 停止后端 (端口 5001)
echo [1/3] 检查后端服务 (端口 5001)...
set "FOUND_5001=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5001 ^| findstr LISTENING 2^>nul') do (
    set "PID=%%a"
    set "FOUND_5001=1"
    echo   发现进程 PID: !PID!
    taskkill /F /PID !PID! /T >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        echo   [成功] 后端服务已停止
    ) else (
        echo   [警告] 无法停止进程 !PID!
    )
)
if !FOUND_5001! EQU 0 (
    echo   [信息] 未发现后端服务
)

:: 停止前端 (端口 3000)
echo [2/3] 检查前端服务 (端口 3000)...
set "FOUND_3000=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :3000 ^| findstr LISTENING 2^>nul') do (
    set "PID=%%a"
    set "FOUND_3000=1"
    echo   发现进程 PID: !PID!
    taskkill /F /PID !PID! /T >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        echo   [成功] 前端服务已停止
    ) else (
        echo   [警告] 无法停止进程 !PID!
    )
)
if !FOUND_3000! EQU 0 (
    echo   [信息] 未发现前端服务
)

:: ========================================
:: 2. 通过窗口标题关闭
:: ========================================
echo [3/3] 关闭相关窗口...
taskkill /FI "WINDOWTITLE eq Backend-FastAPI*" /F /T >nul 2>&1
taskkill /FI "WINDOWTITLE eq Frontend-Next*" /F /T >nul 2>&1
echo   [完成]

:: ========================================
:: 3. 清理 Python 缓存
:: ========================================
echo.
echo [清理] Python 缓存...
cd /d "%PROJECT_ROOT%"
for /d /r %%d in (__pycache__) do (
    if exist "%%d" rd /s /q "%%d" 2>nul
)
for /r %%f in (*.pyc) do (
    if exist "%%f" del /f /q "%%f" 2>nul
)
echo   [完成]

:: ========================================
:: 验证
:: ========================================
echo.
set "STILL_RUNNING=0"
netstat -ano | findstr :5001 | findstr LISTENING >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [警告] 端口 5001 仍在使用中
    set "STILL_RUNNING=1"
)
netstat -ano | findstr :3000 | findstr LISTENING >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [警告] 端口 3000 仍在使用中
    set "STILL_RUNNING=1"
)

if !STILL_RUNNING! EQU 0 (
    echo [成功] 所有服务已停止
)

echo.
pause
