@echo off
title LOL Botlane BP Assistant
cd /d "E:\lol bp\lol-botlane-bp-mine-v2"

REM 统一用 UTF-8：cmd 默认是 GBK(936)，子进程继承了会编不出 emoji/中文，
REM 点"更新数据"时 pre_fetch 一打印标题就崩。
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

REM 确保 psutil 装好了 —— 没有它就读不到 League 客户端命令行
REM （PowerShell CIM / wmic 在国服 WeGame 环境下经常拿不到正确结果）
"D:\python311\python.exe" -c "import psutil" 2>nul
if errorlevel 1 (
    echo [setup] 正在安装 psutil（LCU 自动识别依赖）...
    "D:\python311\python.exe" -m pip install psutil
)

REM open browser after 2 seconds (give the server time to start)
start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8000/"

REM run the server (this window keeps showing logs)
"D:\python311\python.exe" app.py

echo.
echo ================================================
echo  Server stopped. If you see an error above:
echo   - "Address already in use" = server is already running,
echo     just open http://127.0.0.1:8000/ in your browser.
echo   - Other error = read the message above.
echo ================================================
pause
