@echo off
title Registrar Local Starter
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found. Install Python 3.10+ and tick "Add to PATH".
    pause
    exit /b 1
)
python start_local.py
