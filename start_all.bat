@echo off
chcp 65001 >nul
title Registrar Suite - Start All
echo ============================================
echo   Starting proxy pool + web console ...
echo ============================================

rem ---------- 1. easy_proxies (proxy pool) ----------
tasklist /FI "IMAGENAME eq easy_proxies.exe" 2>nul | find /I "easy_proxies.exe" >nul
if %errorlevel%==0 (
    echo [easy_proxies] already running
) else (
    echo [easy_proxies] starting ...
    start "easy_proxies" /D "D:\easy_proxies" "D:\easy_proxies\easy_proxies.exe" --config "D:\easy_proxies\config.yaml"
)

rem ---------- 2. web console (9090) ----------
netstat -ano | findstr ":9090" | findstr LISTENING >nul
if %errorlevel%==0 (
    echo [console] already running (9090)
) else (
    echo [console] starting ...
    start "web_console" /D "D:\OutlookRegister" "D:\OutlookRegister\.venv\Scripts\python" web_console.py --host 0.0.0.0 --port 9090
)

echo.
echo   Console : http://SERVER_IP:9090
echo   ProxyWeb: http://SERVER_IP:9091
echo   (node pool test takes a few minutes)
echo.
echo   Opening console in browser ...
start http://127.0.0.1:9090
timeout /t 3 >nul
