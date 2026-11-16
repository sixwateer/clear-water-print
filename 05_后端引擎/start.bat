@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   净像 Watermark Studio - 启动后端服务
echo ============================================
echo.

python -c "import fastapi, uvicorn, cv2, PIL" 2>nul
if errorlevel 1 (
    echo [首次运行] 正在安装基础依赖，请稍候...
    python -m pip install -r requirements.txt
    echo.
)

echo [启动] 服务地址 http://127.0.0.1:8000
echo [提示] 关闭此窗口即可停止服务
echo.
python server.py
pause
