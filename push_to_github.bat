@echo off
chcp 65001 >nul
REM ============================================================
REM 净像去水印 · 一键清理 + 提交 + 推送
REM 仓库：https://github.com/sixwateer/clear-water-print
REM 用法：双击运行，按提示输入提交说明（直接回车用默认说明）
REM ============================================================

cd /d "%~dp0"

echo.
echo [1/5] 清理本地运行缓存...
if exist "05_后端引擎\__pycache__"                 rd /s /q "05_后端引擎\__pycache__"
if exist "05_后端引擎\engines\__pycache__"         rd /s /q "05_后端引擎\engines\__pycache__"
if exist "05_后端引擎\pipeline\__pycache__"        rd /s /q "05_后端引擎\pipeline\__pycache__"
if exist "05_后端引擎\tests\__pycache__"           rd /s /q "05_后端引擎\tests\__pycache__"
if exist "05_后端引擎\.pytest_cache"               rd /s /q "05_后端引擎\.pytest_cache"
if exist "08_自测\html\_tmp"                       rd /s /q "08_自测\html\_tmp"
echo     完成

echo.
echo [2/5] 当前待提交文件：
git status --short
echo.
echo     被忽略的本地文件（不会上传）：
git status --short --ignored | findstr /b "!!"

echo.
set "MSG="
set /p "MSG=请输入提交说明（回车用默认）："
if "%MSG%"=="" set "MSG=chore: 更新项目文件"

echo.
echo [3/5] 暂存改动...
git add -A

echo.
echo [4/5] 提交：%MSG%
git commit -m "%MSG%"
if errorlevel 1 (
    echo.
    echo [提示] 没有可提交的改动，或提交失败，跳过提交直接推送。
)

echo.
echo [5/5] 推送到 GitHub (origin/main)...
git push origin main
if errorlevel 1 (
    echo.
    echo [错误] 推送失败。常见原因与处理：
    echo   1. 提示 Invalid username or token / Bad credentials
    echo      =^> 凭据已失效，执行一次重新登录后重试：
    echo         gh auth login --hostname github.com --git-protocol https --web
    echo   2. 网络超时
    echo      =^> 确认代理可用，或为 git 单独设置：
    echo         git config --global http.proxy http://127.0.0.1:7897
    echo         git config --global --unset http.proxy   ^(取消^)
    echo   3. 远程地址不对 =^> git remote -v 核对
    pause
    exit /b 1
)

echo.
echo 完成！仓库地址：
echo https://github.com/sixwateer/clear-water-print
echo.
pause
