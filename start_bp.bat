@echo off
title LOL Botlane BP Assistant
cd /d "E:\lol bp\lol-botlane-bp-mine"

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
