@echo off
chcp 65001 >nul
title Registrar Suite - Windows Installer
echo ============================================
echo   OutlookRegister + Easy Proxies - Windows
echo ============================================
echo.

rem ---------- 0. 前置检查 ----------
where python >nul 2>nul || (
    echo [ERROR] Python not found. Install Python 3.10+ from https://www.python.org/downloads/
    echo         IMPORTANT: tick "Add python.exe to PATH" during install.
    pause & exit /b 1
)
where git >nul 2>nul || (
    echo [ERROR] Git not found. Install from https://git-scm.com/download/win
    pause & exit /b 1
)
where curl >nul 2>nul || echo [WARN] curl not found, downloads may fail

rem ---------- 1. easy_proxies (proxy pool) ----------
echo.
echo [1/3] easy_proxies (proxy pool) ...
if not exist "D:\easy_proxies" mkdir "D:\easy_proxies"
if not exist "D:\easy_proxies\easy_proxies.exe" (
    echo       downloading official v2.2.1 windows binary ...
    curl -L -o "D:\easy_proxies\easy_proxies.exe" ^
        "https://github.com/daimon3332/easy-proxies/releases/download/v2.2.1/easy_proxies-v2.2.1-windows-amd64.exe"
)
if not exist "D:\easy_proxies\config.yaml" (
    echo       generating config.yaml template ...
    (
      echo mode: multi-port
      echo listener:
      echo   address: 127.0.0.1
      echo   port: 2323
      echo   username: ""
      echo   password: ""
      echo multi_port:
      echo   address: 127.0.0.1
      echo   base_port: 24000
      echo   username: ""
      echo   password: ""
      echo pool:
      echo   mode: rotate
      echo   failure_threshold: 2
      echo   blacklist_duration: 600s
      echo   rotation_interval: 120s
      echo management:
      echo   enabled: true
      echo   listen: 0.0.0.0:9091
      echo   probe_target: https://www.gstatic.com/generate_204
      echo   password: "CHANGE_ME"
      echo   pprof_enabled: false
      echo subscription_refresh:
      echo   enabled: true
      echo   interval: 24h
      echo   timeout: 30s
      echo   health_check_timeout: 5s
      echo   drain_timeout: 30s
      echo   min_available_nodes: 1
      echo log:
      echo   output: stdout
      echo   file: logs\easy_proxies.log
      echo   max_size: 50
      echo   max_backups: 3
      echo   max_age: 7
      echo   compress: false
      echo subscriptions: []
      echo nodes: []
      echo skip_cert_verify: false
    ) > "D:\easy_proxies\config.yaml"
    echo       !! EDIT D:\easy_proxies\config.yaml : subscriptions + management.password
)

rem ---------- 2. OutlookRegister ----------
echo.
echo [2/3] OutlookRegister ...
if not exist "D:\OutlookRegister\.git" (
    git clone https://github.com/zhonggy/OutlookRegister.git "D:\OutlookRegister"
) else (
    cd /d "D:\OutlookRegister" && git pull
)
cd /d "D:\OutlookRegister"
if not exist ".venv" (
    echo       creating venv ...
    python -m venv .venv
)
echo       pip install ...
".venv\Scripts\python" -m pip install -q --upgrade pip
".venv\Scripts\pip" install -q -r requirements.txt
if not exist "config.json" (
    copy /y config.win.example.json config.json >nul
    echo       !! EDIT config.json : temp_mail (admin_password etc.) if needed
)
echo       installing chromium (patchright) ...
".venv\Scripts\patchright" install chromium

rem ---------- 3. 提示 ----------
echo.
echo [3/3] Done.
echo ============================================
echo  Next steps:
echo   1. Edit D:\easy_proxies\config.yaml
echo        - subscriptions:  paste your proxy subs
echo        - management.password: set a password
echo   2. Edit D:\OutlookRegister\config.json if needed
echo   3. Run start_all.bat  (starts proxy pool + web console)
echo   4. Open http://SERVER_IP:9090  (console, first-run admin)
echo      Open http://SERVER_IP:9091  (proxy pool WebUI, password)
echo ============================================
pause
