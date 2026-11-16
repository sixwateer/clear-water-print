@echo off
chcp 65001 >nul
REM ============================================================
REM 净像去水印项目 - 一键推送到 GitHub
REM 使用前：1) 确认已在 GitHub 网页创建空仓库 watermark-remover
REM         2) 本机 gh 已登录（gh auth status 可见 sixwateer）
REM ============================================================

cd /d "%~dp0"

echo.
echo [1/4] 检查登录状态...
gh auth status
if errorlevel 1 (
    echo [错误] gh 未登录，请先运行: gh auth login
    pause
    exit /b 1
)

echo.
echo [2/4] 配置可用的网络代理...
set HTTPS_PROXY=http://127.0.0.1:7897
set HTTP_PROXY=http://127.0.0.1:7897
git config --local http.proxy http://127.0.0.1:7897

echo.
echo [3/4] 推送到 GitHub (origin/main)...
git push -u origin main
if errorlevel 1 (
    echo.
    echo [错误] 推送失败。请确认：
    echo   1. GitHub 上已创建名为 watermark-remover 的空仓库
    echo   2. 代理 127.0.0.1:7897 正在运行（或改成你的代理端口）
    echo   3. gh 已登录且有该仓库写权限
    pause
    exit /b 1
)

echo.
echo [4/4] 完成！仓库地址：
echo https://github.com/sixwateer/watermark-remover
echo.
pause
