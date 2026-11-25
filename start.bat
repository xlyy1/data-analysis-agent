@echo off
setlocal
cd /d "%~dp0"
title Data Agent - 本地一键启动

echo.
echo ============================================
echo   对话式数据分析 Agent - 本地启动
echo ============================================
echo.

rem ---- 1. 找 Python -------------------------------------------------------
set "REAL_PYTHON="
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "REAL_PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined REAL_PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "REAL_PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined REAL_PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "REAL_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined REAL_PYTHON (
    for /f "delims=" %%P in ('where python 2^>nul') do if not defined REAL_PYTHON set "REAL_PYTHON=%%P"
)
if not defined REAL_PYTHON (
    echo [ERROR] 没找到 Python。请安装 Python 3.12+ : https://python.org
    pause & exit /b 1
)
echo [OK] Python: %REAL_PYTHON%

node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 没找到 Node.js。请安装 Node 20+ : https://nodejs.org
    pause & exit /b 1
)
for /f "delims=" %%i in ('node --version') do echo [OK] Node.js %%i

rem ---- 2. .env ------------------------------------------------------------
if not exist ".env" (
    echo [1/5] 未发现 .env，从 .env.example 复制
    copy /y ".env.example" ".env" >nul
    echo       默认 LLM_PROVIDER=mock（无需 API Key 即可跑通）
) else (
    echo [1/5] .env 已存在
)
if not exist "data" mkdir data

rem ---- 3. 后端依赖 --------------------------------------------------------
echo [2/5] 安装后端依赖 ...
pushd backend
"%REAL_PYTHON%" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install 失败
    popd & pause & exit /b 1
)
echo [OK] 后端依赖就绪
popd

rem ---- 4. 前端依赖 --------------------------------------------------------
echo [3/5] 检查前端依赖 ...
pushd frontend
if not exist "node_modules" (
    call npm install --silent
    if errorlevel 1 (
        echo [ERROR] npm install 失败
        popd & pause & exit /b 1
    )
)
echo [OK] 前端依赖就绪
popd

rem ---- 5. 启动三个进程 ----------------------------------------------------
echo [4/5] 启动 任务服务 (8001) ...
start "Task Worker :8001" cmd /k "cd /d "%~dp0backend" && set TASK_SERVICE_URL=http://127.0.0.1:8001 && "%REAL_PYTHON%" -m uvicorn worker_service.main:app --host 127.0.0.1 --port 8001"

echo [5/5] 启动 API (8000) 与 前端 (5199) ...
start "API :8000" cmd /k "cd /d "%~dp0backend" && set TASK_SERVICE_URL=http://127.0.0.1:8001 && "%REAL_PYTHON%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
start "Frontend :5199" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo ============================================
echo  启动完成（首次启动会自动建库、迁移、播种样例数据）
echo.
echo  Web      : http://localhost:5199
echo  API 文档 : http://localhost:8000/docs
echo  探针     : http://localhost:8000/healthz  /readyz  /metrics
echo.
echo  演示账号 : admin / admin12345
echo  想用真模型：编辑 .env，设 LLM_PROVIDER=deepseek 与 DEEPSEEK_API_KEY
echo ============================================
echo.
echo  提示：想一条命令起全部（含前端打包），用 Docker：
echo    docker compose up -d --build --wait
echo.
pause
endlocal
