@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal EnableDelayedExpansion

echo ============================================================
echo   净像 Watermark Studio - 后端服务一键启动
echo ============================================================
echo.
echo [说明] 自动探测可用 Python（跳过微软商店占位符）、安装依赖并启动 server.py
echo [修改点] 换端口请改 server.py 末尾 uvicorn.run(...)
echo [注意] 关闭本窗口即停止服务
echo.

set "PYEXE="

rem ---- 候选1：WorkBuddy 内置 Python（本环境实际装了依赖的解释器）----
for /d %%D in ("%USERPROFILE%\.workbuddy\binaries\python\versions\*") do (
    if exist "%%D\python.exe" (
        "%%D\python.exe" -c "import fastapi,uvicorn,cv2,PIL,numpy,multipart" >nul 2>&1
        if !errorlevel! equ 0 set "PYEXE=%%D\python.exe"
    )
)

rem ---- 候选2：py launcher（Windows 官方，能绕过商店占位符）----
if not defined PYEXE (
    py -3 -c "import fastapi,uvicorn,cv2,PIL,numpy,multipart" >nul 2>&1
    if !errorlevel! equ 0 set "PYEXE=py -3"
)

rem ---- 候选3：python（若为商店占位符，import 必然失败，自动跳过）----
if not defined PYEXE (
    python -c "import fastapi,uvicorn,cv2,PIL,numpy,multipart" >nul 2>&1
    if !errorlevel! equ 0 set "PYEXE=python"
)

rem ---- 候选4：python3 ----
if not defined PYEXE (
    python3 -c "import fastapi,uvicorn,cv2,PIL,numpy,multipart" >nul 2>&1
    if !errorlevel! equ 0 set "PYEXE=python3"
)

rem ---- 未找到装好依赖的解释器：找一个真实解释器并自动装依赖 ----
if not defined PYEXE (
    echo [首次运行] 未发现已装依赖的解释器，正在查找真实 Python...
    for /d %%D in ("%USERPROFILE%\.workbuddy\binaries\python\versions\*") do (
        if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
    )
    if not defined PYEXE (
        py -3 --version >nul 2>&1
        if !errorlevel! equ 0 set "PYEXE=py -3"
    )
    if not defined PYEXE (
        python --version >nul 2>&1
        if !errorlevel! equ 0 (
            python -c "import sys" >nul 2>&1
            if !errorlevel! equ 0 set "PYEXE=python"
        )
    )
    if defined PYEXE (
        echo [首次运行] 使用 !PYEXE! 安装基础依赖，请稍候...
        !PYEXE! -m pip install -r requirements.txt
        if errorlevel 1 (
            echo [错误] 依赖安装失败，请手动执行：!PYEXE! -m pip install -r requirements.txt
            pause
            exit /b 1
        )
        echo [完成] 依赖安装结束
        echo.
    )
)

if not defined PYEXE (
    echo [错误] 未找到可用的 Python 解释器。
    echo [原因] 系统 python 可能是微软商店占位符，或 Python 未安装。
    echo [处理] 1^) 安装官方 Python 3.9+：https://www.python.org/downloads/
    echo         2^) 安装后在本目录运行：py -3 -m pip install -r requirements.txt
    echo         3^) 或在 WorkBuddy 内置 Python 环境中运行本脚本
    pause
    exit /b 1
)

echo [OK] 使用解释器：!PYEXE!
echo [启动] 服务地址 http://127.0.0.1:8000
echo [启动] 接口文档 http://127.0.0.1:8000/docs
echo [提示] 看到 Uvicorn running on 即启动成功；Ctrl+C 或关闭窗口停止
echo.
!PYEXE! server.py
pause
