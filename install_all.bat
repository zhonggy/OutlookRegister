@echo off
title Registrar Suite - Full Auto Installer (Windows)
echo ============================================================
echo   One-click: Python + Git + Easy Proxies + OutlookRegister
echo   Run as Administrator for best results.
echo ============================================================
echo.

set "PY_VER=3.12.10"
set "PY_EXE_URL=https://www.python.org/ftp/python/%PY_VER%/python-%PY_VER%-amd64.exe"
set "GIT_EXE_URL=https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/Git-2.47.1-64-bit.exe"
set "EP_EXE_URL=https://github.com/daimon3332/easy-proxies/releases/download/v2.2.1/easy_proxies-v2.2.1-windows-amd64.exe"
set "REPO=https://github.com/zhonggy/OutlookRegister.git"
set "EP_DIR=D:\easy_proxies"
set "OR_DIR=D:\OutlookRegister"

rem ============ 1. Python ============
echo [1/5] Python ...
where python >nul 2>nul
if %errorlevel%==0 (
    echo       python already installed
) else (
    if not exist "%TEMP%\python-setup.exe" (
        echo       downloading Python %PY_VER% ...
        curl.exe -L -o "%TEMP%\python-setup.exe" "%PY_EXE_URL%"
    )
    echo       installing (silent, add to PATH) ...
    "%TEMP%\python-setup.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_launcher=1
    echo       waiting for installer ...
    timeout /t 25 /nobreak >nul
    set "PATH=%PATH%;C:\Program Files\Python312;C:\Program Files\Python312\Scripts"
)

rem ============ 2. Git ============
echo [2/5] Git ...
where git >nul 2>nul
if %errorlevel%==0 (
    echo       git already installed
) else (
    if not exist "%TEMP%\git-setup.exe" (
        echo       downloading Git ...
        curl.exe -L -o "%TEMP%\git-setup.exe" "%GIT_EXE_URL%"
    )
    echo       installing (silent) ...
    "%TEMP%\git-setup.exe" /VERYSILENT /NORESTART /SP- /SUPPRESSMSGBOXES
    echo       waiting for installer ...
    timeout /t 30 /nobreak >nul
    set "PATH=%PATH%;C:\Program Files\Git\cmd"
)

rem verify
where python >nul 2>nul || echo [ERROR] python not found after install!
where git >nul 2>nul || echo [ERROR] git not found after install!

rem ============ 3. Easy Proxies ============
echo [3/5] Easy Proxies (proxy pool) ...
if not exist "%EP_DIR%" mkdir "%EP_DIR%"
if not exist "%EP_DIR%\easy_proxies.exe" (
    echo       downloading easy_proxies v2.2.1 ...
    curl.exe -L -o "%EP_DIR%\easy_proxies.exe" "%EP_EXE_URL%"
)
if not exist "%EP_DIR%\config.yaml" (
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
    ) > "%EP_DIR%\config.yaml"
    echo       !! EDIT %EP_DIR%\config.yaml : subscriptions + password
)

rem ============ 4. OutlookRegister ============
echo [4/5] OutlookRegister ...
if not exist "%OR_DIR%\.git" (
    echo       cloning repo ...
    git clone "%REPO%" "%OR_DIR%"
) else (
    cd /d "%OR_DIR%" && git pull
)
cd /d "%OR_DIR%"
if not exist ".venv" (
    echo       creating venv ...
    python -m venv .venv
)
echo       pip install ...
".venv\Scripts\python" -m pip install -q --upgrade pip
".venv\Scripts\pip" install -q -r requirements.txt
if not exist "config.json" (
    copy /y config.win.example.json config.json >nul
    echo       !! EDIT config.json : temp_mail settings if needed
)
echo       installing chromium (patchright) - may take a while ...
".venv\Scripts\patchright" install chromium

rem ============ 5. Done ============
echo.
echo [5/5] Done.
echo ============================================================
echo  Next steps:
echo   1. Edit D:\easy_proxies\config.yaml
echo        - subscriptions:  paste your proxy sub URLs
echo        - password: set a password for 9091 WebUI
echo   2. Edit D:\OutlookRegister\config.json if needed
echo   3. Run start_all.bat  (starts proxy pool + web console)
echo   4. Open http://SERVER_IP:9090  (console, first-run admin)
echo      Open http://SERVER_IP:9091  (proxy pool, password)
echo ============================================================
pause
