@echo off
title LOL BP - Sync to GitHub
cd /d "%~dp0"

echo [1/3] Checking for changes...
"D:\Git\cmd\git.exe" add .

echo [2/3] Committing changes (skip if nothing changed)...
"D:\Git\cmd\git.exe" diff --cached --quiet
if %errorlevel%==0 (
    echo    Nothing to commit. Already up to date.
    goto :push
)
"D:\Git\cmd\git.exe" commit -m "update %date% %time%"

:push
echo [3/3] Pushing to GitHub...
"D:\Git\cmd\git.exe" push
if %errorlevel%==0 (
    echo.
    echo ===== Sync OK =====
    echo https://github.com/leo241/lol-botlane-bp-mine
) else (
    echo.
    echo ===== Push FAILED - check messages above =====
)
pause
