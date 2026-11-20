@echo off
cd /d "%~dp0"
title Data Agent

set PYTHONPATH=
set VIRTUAL_ENV=
set PYTHONSTARTUP=
set __PYVENV_LAUNCHER__=
set PIP_REQUIRE_VIRTUALENV=

set REAL_PYTHON=
set PYHOME=

if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    set REAL_PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe
    set PYHOME=%LOCALAPPDATA%\Programs\Python\Python313
)
if not defined REAL_PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set REAL_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
    set PYHOME=%LOCALAPPDATA%\Programs\Python\Python312
)
if not defined REAL_PYTHON if exist "C:\Python313\python.exe" (
    set REAL_PYTHON=C:\Python313\python.exe
    set PYHOME=C:\Python313
)
if not defined REAL_PYTHON (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        if not defined REAL_PYTHON set REAL_PYTHON=%%P
    )
)

if not defined REAL_PYTHON (
    echo [ERROR] Python not found
    echo Install Python 3.12+ from https://python.org
    pause
    goto :end
)

:: Derive PYHOME from REAL_PYTHON if not already set
if not defined PYHOME (
    for %%A in ("%REAL_PYTHON%") do set PYHOME=%%~dpA
    set PYHOME=%PYHOME:~0,-1%
)

set PYTHONHOME=%PYHOME%

echo.
echo ==== Data Agent ====
echo [OK] Python: %REAL_PYTHON%

node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js not found
    echo Install Node.js 18+ from https://nodejs.org
    pause
    goto :end
)

for /f "delims=" %%i in ('node --version 2^>^&1') do echo [OK] Node.js %%i

if not exist "data" (
    echo [1/3] Creating data folder...
    mkdir data
) else (
    echo [1/3] data folder exists
)

echo [2/3] Installing backend...
cd /d "%~dp0backend"
if exist ".venv" rmdir /s /q .venv 2>nul

"%REAL_PYTHON%" -m pip install --no-cache-dir -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] pip install failed
    cd /d "%~dp0"
    pause
    goto :end
)
echo [OK] Backend ready

echo     Starting backend...
start "Backend" cmd /k "set PYTHONHOME=%PYTHONHOME%&& set PYTHONPATH=&& set __PYVENV_LAUNCHER__=&& cd /d %~dp0backend&& "%REAL_PYTHON%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
cd /d "%~dp0"

echo [3/3] Setting up frontend...
cd /d "%~dp0frontend"

if not exist "node_modules" (
    echo     Installing frontend deps...
    call npm install --silent
    if %errorlevel% neq 0 (
        echo [ERROR] npm install failed
        cd /d "%~dp0"
        pause
        goto :end
    )
)
echo [OK] Frontend ready

echo     Starting frontend...
start "Frontend" cmd /k "cd /d %~dp0frontend&& npm run dev"
cd /d "%~dp0"

echo.
echo ==== Ready ====
echo Backend : http://localhost:8000
echo Frontend: http://localhost:3000
echo Docs    : http://localhost:8000/docs
echo.

:end
pause
