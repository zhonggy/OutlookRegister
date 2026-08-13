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
if not errorlevel 1 goto py_done
if exist "%TEMP%\python-setup.exe" goto py_run
echo       downloading Python %PY_VER% ...
curl.exe -L -o "%TEMP%\python-setup.exe" "%PY_EXE_URL%"
if errorlevel 1 goto py_fail
:py_run
echo       installing (silent, add to PATH) ...
"%TEMP%\python-setup.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_launcher=1
echo       waiting for installer ...
timeout /t 25 /nobreak >nul
set "PATH=%PATH%;C:\Program Files\Python312;C:\Program Files\Python312\Scripts"
goto py_done
:py_fail
echo [ERROR] python download/install failed. Check network and retry.
pause
exit /b 1
:py_done
where python >nul 2>nul
if not errorlevel 1 echo       python OK
if errorlevel 1 echo [WARN] python not in PATH yet - reopen this window after install

rem ============ 2. Git ============
echo [2/5] Git ...
where git >nul 2>nul
if not errorlevel 1 goto git_done
if exist "%TEMP%\git-setup.exe" goto git_run
echo       downloading Git ...
curl.exe -L -o "%TEMP%\git-setup.exe" "%GIT_EXE_URL%"
if errorlevel 1 goto git_fail
:git_run
echo       installing (silent) ...
"%TEMP%\git-setup.exe" /VERYSILENT /NORESTART /SP- /SUPPRESSMSGBOXES
echo       waiting for installer ...
timeout /t 30 /nobreak >nul
set "PATH=%PATH%;C:\Program Files\Git\cmd"
goto git_done
:git_fail
echo [ERROR] git download/install failed. Check network and retry.
pause
exit /b 1
:git_done
where git >nul 2>nul
if not errorlevel 1 echo       git OK
if errorlevel 1 echo [WARN] git not in PATH yet - reopen this window after install

rem ============ 3. Easy Proxies ============
echo [3/5] Easy Proxies (proxy pool) ...
if not exist "D:\easy_proxies" mkdir "D:\easy_proxies"
if exist "D:\easy_proxies\easy_proxies.exe" goto ep_done
echo       downloading easy_proxies v2.2.1 ...
curl.exe -L -o "D:\easy_proxies\easy_proxies.exe" "%EP_EXE_URL%"
:ep_done
if exist "D:\easy_proxies\config.yaml" goto ep_cfg_done
echo       generating config.yaml template ...
> "D:\easy_proxies\config.yaml" echo mode: multi-port
>> "D:\easy_proxies\config.yaml" echo listener:
>> "D:\easy_proxies\config.yaml" echo   address: 127.0.0.1
>> "D:\easy_proxies\config.yaml" echo   port: 2323
>> "D:\easy_proxies\config.yaml" echo   username: ""
>> "D:\easy_proxies\config.yaml" echo   password: ""
>> "D:\easy_proxies\config.yaml" echo multi_port:
>> "D:\easy_proxies\config.yaml" echo   address: 127.0.0.1
>> "D:\easy_proxies\config.yaml" echo   base_port: 24000
>> "D:\easy_proxies\config.yaml" echo   username: ""
>> "D:\easy_proxies\config.yaml" echo   password: ""
>> "D:\easy_proxies\config.yaml" echo pool:
>> "D:\easy_proxies\config.yaml" echo   mode: rotate
>> "D:\easy_proxies\config.yaml" echo   failure_threshold: 2
>> "D:\easy_proxies\config.yaml" echo   blacklist_duration: 600s
>> "D:\easy_proxies\config.yaml" echo   rotation_interval: 120s
>> "D:\easy_proxies\config.yaml" echo management:
>> "D:\easy_proxies\config.yaml" echo   enabled: true
>> "D:\easy_proxies\config.yaml" echo   listen: 0.0.0.0:9091
>> "D:\easy_proxies\config.yaml" echo   probe_target: https://www.gstatic.com/generate_204
>> "D:\easy_proxies\config.yaml" echo   password: "CHANGE_ME"
>> "D:\easy_proxies\config.yaml" echo   pprof_enabled: false
>> "D:\easy_proxies\config.yaml" echo subscription_refresh:
>> "D:\easy_proxies\config.yaml" echo   enabled: true
>> "D:\easy_proxies\config.yaml" echo   interval: 24h
>> "D:\easy_proxies\config.yaml" echo   timeout: 30s
>> "D:\easy_proxies\config.yaml" echo   health_check_timeout: 5s
>> "D:\easy_proxies\config.yaml" echo   drain_timeout: 30s
>> "D:\easy_proxies\config.yaml" echo   min_available_nodes: 1
>> "D:\easy_proxies\config.yaml" echo log:
>> "D:\easy_proxies\config.yaml" echo   output: stdout
>> "D:\easy_proxies\config.yaml" echo   file: logs\easy_proxies.log
>> "D:\easy_proxies\config.yaml" echo   max_size: 50
>> "D:\easy_proxies\config.yaml" echo   max_backups: 3
>> "D:\easy_proxies\config.yaml" echo   max_age: 7
>> "D:\easy_proxies\config.yaml" echo   compress: false
>> "D:\easy_proxies\config.yaml" echo subscriptions: []
>> "D:\easy_proxies\config.yaml" echo nodes: []
>> "D:\easy_proxies\config.yaml" echo skip_cert_verify: false
echo       !! EDIT D:\easy_proxies\config.yaml : subscriptions + password
:ep_cfg_done
echo       easy_proxies ready

rem ============ 4. OutlookRegister ============
echo [4/5] OutlookRegister ...
if exist "D:\OutlookRegister\.git" goto or_pull
echo       cloning repo ...
git clone "%REPO%" "D:\OutlookRegister"
if errorlevel 1 goto clone_fail
goto or_deps
:or_pull
cd /d "D:\OutlookRegister"
git pull
:clone_fail
if not exist "D:\OutlookRegister\.git" goto or_fail
:or_deps
cd /d "D:\OutlookRegister"
if exist ".venv" goto or_pip
echo       creating venv ...
python -m venv .venv
:or_pip
echo       pip install ...
".venv\Scripts\python" -m pip install -q --upgrade pip
".venv\Scripts\pip" install -q -r requirements.txt
if exist "config.json" goto or_cfg
copy /y config.win.example.json config.json >nul
echo       !! EDIT config.json : temp_mail settings if needed
:or_cfg
echo       installing chromium (patchright) - may take a while ...
".venv\Scripts\patchright" install chromium
goto or_done
:or_fail
echo [ERROR] clone failed. Check network and git.
pause
exit /b 1
:or_done
echo       OutlookRegister ready

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
