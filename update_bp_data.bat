@echo off
title LOL BP - Update Data (2-3 minutes)
cd /d "E:\lol bp\lol-botlane-bp-mine-v2"

REM 切 UTF-8 代码页并让 Python 也用 UTF-8 输出。
REM 不加的话 cmd 是 GBK(936)，pre_fetch 标题里的 emoji 编不出来会直接崩掉。
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

echo Starting data update, this takes 2-3 minutes.
echo Old data is backed up automatically. If anything fails, it rolls back.
echo.

"D:\python311\python.exe" update_data.py

echo.
echo ================================================
echo  Update finished. Check the messages above:
echo   - "Data update complete" = success, just refresh the web page.
echo   - If the page still shows an old time, close the
echo     server window and double-click Start_LOL_BP.bat again.
echo ================================================
pause
