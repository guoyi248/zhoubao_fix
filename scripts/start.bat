@echo off
setlocal
cd /d "%~dp0\.."

rem Prefer the project's Python environment. Use the configured database if one is supplied.
if exist "venv\Scripts\python.exe" set "PATH=%CD%\venv\Scripts;%PATH%"
if exist ".venv\Scripts\python.exe" set "PATH=%CD%\.venv\Scripts;%PATH%"
if not exist "backend\.env" copy /Y "backend\.env.example" "backend\.env" >nul

python -c "import django,rest_framework,celery,fitz,omml2latex,ziamath" >nul 2>&1
if errorlevel 1 (
    python -m pip install -e ".[dev]"
    if errorlevel 1 exit /b 1
)

python backend\manage.py migrate --noinput
if errorlevel 1 exit /b 1

if not exist "frontend\node_modules\vite\bin\vite.js" (
    pushd frontend
    call npm ci
    if errorlevel 1 exit /b 1
    popd
)

set "WEEKLY_WEB_PORT=5173"
set "WEEKLY_API_PORT=8000"
call :port_available 5173
if errorlevel 1 set "WEEKLY_WEB_PORT=5174"
call :port_available 8000
if errorlevel 1 set "WEEKLY_API_PORT=8001"
call :port_available %WEEKLY_WEB_PORT%
if errorlevel 1 (
    echo Both preview ports 5173 and 5174 are in use.
    exit /b 1
)
call :port_available %WEEKLY_API_PORT%
if errorlevel 1 (
    echo Both API ports 8000 and 8001 are in use.
    exit /b 1
)
set "VITE_PROXY_TARGET=http://127.0.0.1:%WEEKLY_API_PORT%"
echo Weekly report workspace: http://127.0.0.1:%WEEKLY_WEB_PORT%
start "Weekly-Report-Backend-%WEEKLY_API_PORT%" /min cmd /c "python backend\manage.py runserver 127.0.0.1:%WEEKLY_API_PORT% --noreload"
start "Weekly-Report-Jobs-%WEEKLY_WEB_PORT%" /min cmd /c "python backend\manage.py run_weekly_jobs --watch"
start "Weekly-Report-Frontend-%WEEKLY_WEB_PORT%" /min /d frontend cmd /c "npm run dev -- --host 127.0.0.1 --port %WEEKLY_WEB_PORT% --strictPort"

echo Press any key to stop this local workspace.
pause >nul
taskkill /FI "WINDOWTITLE eq Weekly-Report-Backend-%WEEKLY_API_PORT%*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Weekly-Report-Jobs-%WEEKLY_WEB_PORT%*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Weekly-Report-Frontend-%WEEKLY_WEB_PORT%*" /T /F >nul 2>&1

exit /b 0

:port_available
python -c "import socket, sys; sock = socket.socket(); sock.bind(('127.0.0.1', int(sys.argv[1]))); sock.close()" %1 >nul 2>&1
exit /b %errorlevel%
