#!/bin/bash
set -e
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"

echo "========================================"
echo "  周报系统 一键部署"
echo "  目录: $PROJECT_DIR"
echo "========================================"

# ── 0. 环境检测 ──
echo "检测环境..."

# Python
if command -v python3 &>/dev/null; then
  PYTHON=python3
elif command -v python &>/dev/null; then
  PYTHON=python
else
  echo "ERROR: 未找到 Python，请先安装 Python 3.11+"
  exit 1
fi
echo "  Python: $($PYTHON --version)"

# pip
if ! $PYTHON -m pip --version &>/dev/null; then
  echo "安装 pip..."
  sudo apt update -qq && sudo apt install -y -qq python3-pip
fi
echo "  pip: OK"

# Docker
if ! docker info &>/dev/null; then
  echo "ERROR: Docker 未运行，请先启动 Docker"
  exit 1
fi
echo "  Docker: $(docker --version)"

# openssl
if ! command -v openssl &>/dev/null; then
  sudo apt install -y -qq openssl
fi

# ── 1. 创建目录和密钥 ──
mkdir -p data/postgres data/clamav deploy/secrets deploy/config

if [ ! -f deploy/secrets/postgres_password ]; then
  openssl rand -base64 24 | tr -d '\n' > deploy/secrets/postgres_password
fi
if [ ! -f deploy/secrets/django_secret_key ]; then
  openssl rand -base64 48 | tr -d '\n' > deploy/secrets/django_secret_key
fi
chmod 600 deploy/secrets/*

# ── 2. app.env ──
cat > deploy/config/app.env << EOF
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_ALLOWED_HOSTS=*
DJANGO_SECRET_KEY=$(cat deploy/secrets/django_secret_key)
CSRF_TRUSTED_ORIGINS=http://*
APP_TIME_ZONE=Asia/Shanghai
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=weekly_report
DATABASE_USER=weekly_app
DATABASE_PASSWORD=$(cat deploy/secrets/postgres_password)
REDIS_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=hjy
S3_SECRET_KEY=hjy12345678
S3_BUCKET_ORIGINALS=weekly-originals
S3_BUCKET_PREVIEWS=weekly-previews
S3_BUCKET_EXPORTS=weekly-exports
CLAMAV_HOST=clamav
CLAMAV_PORT=3310
GOTENBERG_URL=http://gotenberg:3000
MAX_UPLOAD_BYTES=104857600
ENABLE_LLM=false
EOF

# ── 3. MinIO Buckets ──
echo "MinIO Buckets..."
docker run --rm --network weekly-report_backend --entrypoint sh minio/mc -c "
  mc alias set local http://minio:9000 hjy hjy12345678 &&
  mc mb local/weekly-originals --ignore-existing &&
  mc mb local/weekly-previews --ignore-existing &&
  mc mb local/weekly-exports --ignore-existing &&
  echo '  Buckets OK'
" 2>/dev/null || echo "  Buckets 可能已存在"

# ── 4. 启动 Docker 服务 ──
echo "启动 Docker 服务..."
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d postgres clamav gotenberg 2>&1 | tail -3
echo "等待 PostgreSQL..."
for i in $(seq 1 20); do
  if docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml exec -T postgres pg_isready -U weekly_app 2>/dev/null; then
    echo "  PostgreSQL 就绪"
    break
  fi
  sleep 2
done

# ── 5. 安装 Python 依赖 ──
echo "安装 Python 依赖..."
$PYTHON -m pip install --quiet \
  django djangorestframework django-cors-headers \
  celery redis "psycopg[binary]" boto3 Pillow PyMuPDF \
  argon2-cffi django-otp python-magic requests \
  fpdf2 python-docx openpyxl python-pptx gunicorn \
  2>&1 | tail -1
echo "  依赖安装完成"

# ── 6. 数据库迁移 ──
echo "数据库迁移..."
export DJANGO_SETTINGS_MODULE=config.settings.production
export DATABASE_HOST=localhost DATABASE_PORT=5432 DATABASE_NAME=weekly_report DATABASE_USER=weekly_app
export DATABASE_PASSWORD=$(cat deploy/secrets/postgres_password)
$PYTHON backend/manage.py migrate --noinput 2>&1 | tail -3

# ── 7. 管理员 ──
$PYTHON backend/manage.py shell -c "
from accounts.models import User, UserRole, AccountStatus
from organizations.models import Department
dept, _ = Department.objects.get_or_create(name='技术部', defaults={'code':'tech'})
if not User.objects.filter(username='admin').exists():
    u = User.objects.create_user(username='admin', password='Admin123!', display_name='系统管理员', role='super_admin', account_status='active', department=dept)
    print('  Admin 已创建: admin / Admin123!')
else:
    print('  Admin 已存在')
"

# ── 8. 启动 Nginx ──
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d nginx 2>&1 | tail -2

# ── 9. 启动 Django ──
echo "启动 Django..."
set -a; source deploy/config/app.env; set +a
# 先杀掉旧进程
pkill -f "gunicorn.*config.wsgi" 2>/dev/null || true
nohup $PYTHON -m gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 --chdir backend \
  --workers 2 --threads 2 \
  --access-logfile /tmp/gunicorn-access.log \
  --error-logfile /tmp/gunicorn-error.log \
  > /dev/null 2>&1 &
echo "  Django PID: $!"

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo ""
echo "========================================"
echo "  ✅ 部署完成!"
echo "  访问: http://$IP:9527"
echo "  管理员: admin / Admin123!"
echo "========================================"
