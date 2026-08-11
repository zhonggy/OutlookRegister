@echo off
chcp 65001 >nul
title 本地注册机一键启动
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 python，请确认已安装并加入 PATH
    pause
    exit /b 1
)
python start_local.py
