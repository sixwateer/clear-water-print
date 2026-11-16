@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo   净像 Watermark Studio - 后端服务一键启动
echo ============================================================
echo.
echo [说明] 本脚本做两件事：1) 首次运行时安装依赖  2) 启动 server.py
echo [修改点] 换端口请改 server.py 末尾 uvicorn.run(...)
echo [注意] 需 Python 3.9+ 且已加入 PATH；关闭本窗口即停止服务
echo.

python -c "import fastapi, uvicorn, cv2, PIL" 2>nul
if errorlevel 1 (
    echo [首次运行] 正在安装基础依赖，请稍候...
    python -m pip install -r requirements.txt
    echo.
)

echo [启动] 服务地址 http://127.0.0.1:8000
echo [启动] 接口文档 http://127.0.0.1:8000/docs
echo [提示] 看到 Uvicorn running on 即启动成功；Ctrl+C 或关闭窗口停止
echo.
python server.py
pause
