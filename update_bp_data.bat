@echo off
title LOL BP - Update Data (2-3 minutes)
cd /d "E:\lol bp\lol-botlane-bp-mine"

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
