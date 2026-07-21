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

# 虚拟环境（Debian 13 禁止 pip 直接装到系统 Python）
if [ ! -d venv ]; then
  echo "创建虚拟环境..."
  $PYTHON -m venv venv
fi
source venv/bin/activate
PYTHON=python
echo "  venv: OK"

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

# ── 0.5 检测服务器 IP ──
echo "检测服务器 IP..."
LOCAL_IPS=$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -v '^$' || true)
PUBLIC_IP=$(curl -s --connect-timeout 3 ifconfig.me 2>/dev/null || curl -s --connect-timeout 3 icanhazip.com 2>/dev/null || true)

# 构建 CSRF_TRUSTED_ORIGINS
CSRF_ORIGINS="http://localhost:9527,http://127.0.0.1:9527"
for ip in $LOCAL_IPS; do
  CSRF_ORIGINS="$CSRF_ORIGINS,http://$ip:9527"
done
if [ -n "$PUBLIC_IP" ]; then
  CSRF_ORIGINS="$CSRF_ORIGINS,http://$PUBLIC_IP:9527"
fi
echo "  CSRF Origins: $CSRF_ORIGINS"

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
DJANGO_CSRF_TRUSTED_ORIGINS=$CSRF_ORIGINS
APP_TIME_ZONE=Asia/Shanghai
DATABASE_HOST=postgres
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
echo "========================================"
echo "  [3/9] MinIO 存储桶"
echo "========================================"
docker run --rm --network weekly-report_backend --entrypoint sh minio/mc -c "
  mc alias set local http://minio:9000 hjy hjy12345678 &&
  mc mb local/weekly-originals --ignore-existing &&
  mc mb local/weekly-previews --ignore-existing &&
  mc mb local/weekly-exports --ignore-existing &&
  echo '  ✓ 存储桶就绪'
" 2>/dev/null || echo "  ✓ 存储桶已存在"

# ── 4. 启动 Docker 服务 ──
echo "========================================"
echo "  [4/9] 启动基础设施容器"
echo "========================================"
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d postgres redis minio clamav gotenberg
echo ""
echo "等待 PostgreSQL 就绪..."
for i in $(seq 1 20); do
  if docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml exec -T postgres pg_isready -U weekly_app -d weekly_report 2>/dev/null; then
    echo "  ✓ PostgreSQL 就绪"
    break
  fi
  printf "  ."
  sleep 2
done
echo ""

# ── 5. 安装 Python 依赖 ──
echo "========================================"
echo "  [5/9] 安装 Python 依赖"
echo "========================================"
$PYTHON -m pip install \
  django djangorestframework django-cors-headers \
  celery redis "psycopg[binary]" boto3 Pillow PyMuPDF \
  argon2-cffi django-otp python-magic requests \
  fpdf2 python-docx openpyxl python-pptx gunicorn
echo "  ✓ 依赖安装完成"
echo ""

echo "========================================"
echo "  [6/9] 构建并启动 API 容器（首次约需 5-10 分钟）"
echo "========================================"
echo "构建 API 镜像..."
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml build api
echo "  ✓ 镜像构建完成"
echo "启动 API 容器..."
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d api
echo "  ✓ API 容器已启动"
echo ""

# ── 7. 数据库迁移 ──
echo "========================================"
echo "  [7/9] 数据库迁移"
echo "========================================"
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml run --rm api python backend/manage.py migrate --noinput
echo "  ✓ 迁移完成"
echo ""

echo "========================================"
echo "  [8/9] 创建管理员"
echo "========================================"
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml run --rm api python backend/manage.py shell -c "
from accounts.models import User, UserRole, AccountStatus
from organizations.models import Department
dept, _ = Department.objects.get_or_create(name='技术部', defaults={'code':'tech'})
if not User.objects.filter(username='admin').exists():
    u = User.objects.create_user(username='admin', password='Admin123!', display_name='系统管理员', role='super_admin', account_status='active', department=dept)
    print('  ✓ 管理员已创建: admin / Admin123!')
else:
    print('  ✓ 管理员已存在')
"
echo ""

echo "========================================"
echo "  [9/9] 启动 Nginx"
echo "========================================"
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d nginx
echo "  ✓ Nginx 已启动"

# 取第一个 IP 用于显示
ACCESS_IP=$(echo "$LOCAL_IPS" | head -1)
[ -z "$ACCESS_IP" ] && ACCESS_IP="$PUBLIC_IP"
echo ""
echo "========================================"
echo "  ✅ 部署完成!"
echo "========================================"
echo "  内网访问:  http://$ACCESS_IP:9527"
[ -n "$PUBLIC_IP" ] && echo "  公网访问:  http://$PUBLIC_IP:9527"
echo "  管理员:    admin / Admin123!"
echo "========================================"
echo ""
echo "运行状态检查: docker ps"
