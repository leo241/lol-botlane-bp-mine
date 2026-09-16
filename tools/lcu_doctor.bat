@echo off
title LOL BP - LCU Doctor
cd /d "%~dp0\.."

echo ================================================
echo  LCU 探测诊断
echo  请先打开 LOL 客户端（进入主界面），再运行这个脚本
echo ================================================
echo.

"D:\python311\python.exe" tools\lcu_doctor.py

echo.
pause
