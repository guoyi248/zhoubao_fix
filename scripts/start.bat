@echo off
REM ============================================================
REM 周报整合系统 — 一键启动（开发环境）
REM ============================================================
cd /d %~dp0\..

echo.
echo ========================================
echo   周报整合系统 - 开发环境启动
echo ========================================
echo.

REM ---- 1. 启动 Docker 基础设施 ----
echo [1/4] 启动 Docker 基础设施...
docker compose -f deploy/compose.yaml up -d postgres redis minio clamav 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker 启动失败，请确认 Docker Desktop 已运行
    pause
    exit /b 1
)
echo [OK] 基础设施已启动

REM ---- 2. 等待服务就绪 ----
echo [2/4] 等待服务就绪...
timeout /t 5 /nobreak >nul

REM ---- 3. 数据库迁移 ----
echo [3/4] 执行数据库迁移...
cd backend
pip install -e .. >nul 2>&1
python manage.py migrate --run-syncdb
if %errorlevel% neq 0 (
    echo [WARN] 迁移可能已有表，尝试普通迁移...
    python manage.py migrate
)
python manage.py shell -c "from accounts.models import User; print(f'Users: {User.objects.count()}')"
echo [OK] 数据库就绪
cd ..

REM ---- 4. 启动应用 ----
echo [4/4] 启动应用服务器...
echo.
echo   API:     http://localhost:8000/api/v1/
echo   Frontend: http://localhost:5173
echo   健康:    http://localhost:8000/health/live
echo.
echo Ctrl+C 停止所有服务
echo ========================================

REM 并行启动前后端
start "Weekly-Report-Backend" cmd /c "cd backend && python manage.py runserver 0.0.0.0:8000"
start "Weekly-Report-Frontend" cmd /c "cd frontend && npm install && npm run dev"

echo 服务已启动。按任意键关闭所有服务...
pause >nul

REM 清理
taskkill /FI "WINDOWTITLE eq Weekly-Report-Backend*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Weekly-Report-Frontend*" /T /F >nul 2>&1
echo 已停止
