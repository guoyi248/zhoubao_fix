#!/bin/bash
# ============================================================
# 周报整合系统 — 一键部署脚本
# 适用: Debian 11/12/13, Ubuntu 20.04+
# 用法: chmod +x setup.sh && ./setup.sh
# ============================================================
set -e
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"

echo "========================================"
echo "  周报整合系统 一键部署"
echo "  目录: $PROJECT_DIR"
echo "========================================"

# ── 0. 环境检测与安装 ──
echo "检测环境..."

# 更新 apt
sudo apt update -qq

# Python3 + pip
if ! command -v python3 &>/dev/null; then
  echo "安装 Python3..."
  sudo apt install -y -qq python3 python3-pip
fi
PYTHON=python3
echo "  Python: $($PYTHON --version)"

if ! $PYTHON -m pip --version &>/dev/null; then
  sudo apt install -y -qq python3-pip
fi
echo "  pip: OK"

# Git
if ! command -v git &>/dev/null; then
  echo "安装 Git..."
  sudo apt install -y -qq git
fi
echo "  Git: $(git --version)"

# Docker
if ! command -v docker &>/dev/null; then
  echo "安装 Docker..."
  sudo apt install -y -qq docker.io docker-compose-v2
  sudo systemctl enable --now docker
fi
if ! docker info &>/dev/null; then
  echo "启动 Docker..."
  sudo systemctl start docker
  sleep 3
fi
echo "  Docker: $(docker --version)"

# openssl
if ! command -v openssl &>/dev/null; then
  sudo apt install -y -qq openssl
fi

# 确保 docker 命令可用
if docker info &>/dev/null; then
  DOCKER="docker"
elif sudo docker info &>/dev/null; then
  DOCKER="sudo docker"
  sudo usermod -aG docker $USER 2>/dev/null || true
  echo "  提示: 已加入 docker 组，下次登录后无需 sudo"
else
  echo "ERROR: Docker 无法连接"
  exit 1
fi

# ── 1. 创建目录和密钥 ──
mkdir -p data/postgres data/clamav data/redis data/minio deploy/secrets deploy/config

if [ ! -f deploy/secrets/postgres_password ]; then
  openssl rand -base64 24 | tr -d '\n' > deploy/secrets/postgres_password
fi
if [ ! -f deploy/secrets/django_secret_key ]; then
  openssl rand -base64 48 | tr -d '\n' > deploy/secrets/django_secret_key
fi
chmod 600 deploy/secrets/*

# ── 2. 环境变量 ──
DJANGO_SECRET=$(cat deploy/secrets/django_secret_key)
PG_PASS=$(cat deploy/secrets/postgres_password)

cat > deploy/config/app.env << EOF
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_ALLOWED_HOSTS=*
DJANGO_SECRET_KEY=$DJANGO_SECRET
CSRF_TRUSTED_ORIGINS=http://*
APP_TIME_ZONE=Asia/Shanghai
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=weekly_report
DATABASE_USER=weekly_app
DATABASE_PASSWORD=$PG_PASS
REDIS_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
S3_ENDPOINT=http://localhost:9100
S3_ACCESS_KEY=hjy
S3_SECRET_KEY=hjy12345678
S3_BUCKET_ORIGINALS=weekly-originals
S3_BUCKET_PREVIEWS=weekly-previews
S3_BUCKET_EXPORTS=weekly-exports
CLAMAV_HOST=localhost
CLAMAV_PORT=3310
GOTENBERG_URL=http://localhost:3000
MAX_UPLOAD_BYTES=104857600
ENABLE_LLM=false
EOF

# ── 3. 判断是否复用已有 MinIO / Redis ──
if $DOCKER ps --format '{{.Names}}' | grep -q "update-url-minio"; then
  echo "复用已有 MinIO"
else
  echo "创建 MinIO..."
  $DOCKER compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d minio
fi

if $DOCKER ps --format '{{.Names}}' | grep -q "geotrellis-redis"; then
  echo "复用已有 Redis"
else
  echo "创建 Redis..."
  $DOCKER compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d redis
fi

# ── 4. 启动 Docker 服务 ──
echo "启动服务..."
$DOCKER compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d postgres clamav gotenberg

echo "等待 PostgreSQL..."
for i in $(seq 1 20); do
  if $DOCKER compose -f deploy/compose.yaml -f deploy/compose.production.yaml exec -T postgres pg_isready -U weekly_app 2>/dev/null; then
    echo "  PostgreSQL 就绪"
    break
  fi
  sleep 2
done

# ── 5. MinIO Buckets ──
echo "MinIO Buckets..."
$DOCKER run --rm --network host --entrypoint sh minio/mc -c "
  mc alias set local http://localhost:9100 hjy hjy12345678 &&
  mc mb local/weekly-originals --ignore-existing &&
  mc mb local/weekly-previews --ignore-existing &&
  mc mb local/weekly-exports --ignore-existing &&
  echo '  Buckets OK'
" 2>/dev/null || echo "  已存在"

# ── 6. 安装 Python 依赖 ──
echo "安装 Python 依赖..."
$PYTHON -m pip install --quiet \
  django djangorestframework django-cors-headers \
  celery redis "psycopg[binary]" boto3 Pillow PyMuPDF \
  argon2-cffi django-otp python-magic requests \
  fpdf2 python-docx openpyxl python-pptx gunicorn \
  2>&1 | tail -1
echo "  OK"

# ── 7. 数据库迁移 ──
echo "数据库迁移..."
export DJANGO_SETTINGS_MODULE=config.settings.production
export DATABASE_HOST=localhost DATABASE_PORT=5432 DATABASE_NAME=weekly_report DATABASE_USER=weekly_app
export DATABASE_PASSWORD=$PG_PASS
$PYTHON backend/manage.py migrate --noinput 2>&1 | tail -1

# ── 8. 管理员 ──
echo "创建管理员..."
$PYTHON backend/manage.py shell -c "
from accounts.models import User, UserRole, AccountStatus
from organizations.models import Department
dept, _ = Department.objects.get_or_create(name='技术部', defaults={'code':'tech'})
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser(username='admin', password='Admin123!', display_name='系统管理员', role='super_admin', account_status='active', department=dept)
    print('  admin / Admin123!')
else:
    print('  已存在')
"

# ── 9. 启动 Nginx ──
$DOCKER compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d nginx 2>&1 | tail -1

# ── 10. 启动 Django ──
echo "启动 Django..."
set -a; source deploy/config/app.env; set +a
pkill -f "gunicorn.*config.wsgi" 2>/dev/null || true
nohup $PYTHON -m gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 --chdir backend \
  --workers 2 --threads 2 \
  --access-logfile /tmp/gunicorn-access.log \
  --error-logfile /tmp/gunicorn-error.log \
  > /dev/null 2>&1 &
echo "  PID: $!"

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo ""
echo "========================================"
echo "  ✅ 部署完成!"
echo "  访问: http://$IP:9527"
echo "  管理员: admin / Admin123!"
echo "========================================"
