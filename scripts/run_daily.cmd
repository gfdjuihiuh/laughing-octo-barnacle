@echo off
REM 新闻之眼 · 每日运行脚本
REM 由 Windows 任务计划程序在每天 08:00 触发

cd /d C:\Users\Blue\Desktop\git

REM Set PYTHONPATH for module resolution
set PYTHONPATH=src

REM Activate venv and run
call .venv\Scripts\activate.bat
python -m eyes

REM 记录退出码
if %ERRORLEVEL% NEQ 0 (
    echo [%date% %time%] eyes 运行失败，退出码: %ERRORLEVEL% >> logs\cron.log
)
