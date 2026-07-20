#!/bin/bash
set -e
cd "$(dirname "$0")/.."

echo "========================================"
echo "  周报系统 部署"
echo "  目录: $(pwd)"
echo "========================================"

# ── 1. 创建目录和密钥 ──
mkdir -p data/postgres data/clamav deploy/secrets deploy/config

if [ ! -f deploy/secrets/postgres_password ]; then
  openssl rand -base64 24 | tr -d '\n' > deploy/secrets/postgres_password
fi
if [ ! -f deploy/secrets/django_secret_key ]; then
  openssl rand -base64 48 | tr -d '\n' > deploy/secrets/django_secret_key
fi

# ── 2. app.env ──
cat > deploy/config/app.env << 'EOF'
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_ALLOWED_HOSTS=*
CSRF_TRUSTED_ORIGINS=http://*
APP_TIME_ZONE=Asia/Shanghai
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=weekly_report
DATABASE_USER=weekly_app
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

# ── 3. MinIO Buckets ──
echo "MinIO Buckets..."
docker run --rm --network host --entrypoint sh minio/mc -c "
  mc alias set local http://localhost:9100 hjy hjy12345678
  mc mb local/weekly-originals --ignore-existing
  mc mb local/weekly-previews --ignore-existing
  mc mb local/weekly-exports --ignore-existing
  echo Buckets OK
" 2>/dev/null || echo "已存在"

# ── 4. 启动 Docker 服务 ──
echo "启动 Docker 服务..."
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d postgres clamav gotenberg
sleep 10

# ── 5. 安装 Python 依赖 ──
echo "安装 Python 依赖..."
pip install django djangorestframework django-cors-headers celery redis "psycopg[binary]" boto3 Pillow PyMuPDF argon2-cffi django-otp python-magic requests fpdf2 python-docx openpyxl python-pptx gunicorn -q 2>&1 | tail -3

# ── 6. 数据库迁移 ──
echo "数据库迁移..."
export DJANGO_SETTINGS_MODULE=config.settings.production
export DATABASE_HOST=localhost
export DATABASE_PORT=5432
export DATABASE_NAME=weekly_report
export DATABASE_USER=weekly_app
export DATABASE_PASSWORD=$(cat deploy/secrets/postgres_password)
python backend/manage.py migrate --noinput

# ── 7. 管理员 ──
python backend/manage.py shell -c "
from accounts.models import User, UserRole, AccountStatus
from organizations.models import Department
dept, _ = Department.objects.get_or_create(name='技术部', defaults={'code':'tech'})
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser(username='admin', password='Admin123!', display_name='系统管理员', role='super_admin', account_status='active', department=dept)
    print('Admin: admin / Admin123!')
else:
    print('Admin 已存在')
"

# ── 8. 启动全部 ──
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d

# ── 9. 启动 Django ──
echo "启动 Django..."
set -a; source deploy/config/app.env; set +a
nohup gunicorn config.wsgi:application --bind 0.0.0.0:8000 --chdir backend --workers 2 --threads 2 --access-logfile /tmp/gunicorn.log --error-logfile /tmp/gunicorn-error.log > /dev/null 2>&1 &
echo "Django PID: $!"

IP=$(hostname -I | awk '{print $1}')
echo ""
echo "========================================"
echo "  部署完成!"
echo "  访问: http://$IP:9527"
echo "  admin / Admin123!"
echo "  Django PID: $!"
echo "  Docker: docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml ps"
echo "========================================"
