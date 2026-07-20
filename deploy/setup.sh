#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "========================================"
echo "  周报整合系统 — 部署"
echo "  目录: $(pwd)"
echo "========================================"

# 1. 创建目录（compose 文件在 deploy/ 下，相对路径以 deploy/ 为准）
mkdir -p data/postgres data/clamav deploy/secrets deploy/config

# 2. 生成密钥
if [ ! -f deploy/secrets/django_secret_key ]; then
  openssl rand -base64 48 | tr -d '\n' > deploy/secrets/django_secret_key
fi
if [ ! -f deploy/secrets/postgres_password ]; then
  openssl rand -base64 24 | tr -d '\n' > deploy/secrets/postgres_password
fi
echo "hjy12345678" > deploy/secrets/s3_secret_key
chmod 600 deploy/secrets/*

# 3. 环境变量
cat > deploy/config/app.env << 'EOF'
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_ALLOWED_HOSTS=*
CSRF_TRUSTED_ORIGINS=http://*
APP_TIME_ZONE=Asia/Shanghai
DATABASE_HOST=postgres
DATABASE_PORT=5432
DATABASE_NAME=weekly_report
DATABASE_USER=weekly_app
REDIS_URL=redis://host.docker.internal:6379/0
CELERY_RESULT_BACKEND=redis://host.docker.internal:6379/1
S3_ENDPOINT=http://host.docker.internal:9100
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

# 4. MinIO Buckets
echo "创建 MinIO Buckets..."
docker run --rm --network host --entrypoint sh minio/mc -c "
  mc alias set local http://localhost:9100 hjy hjy12345678 &&
  mc mb local/weekly-originals --ignore-existing &&
  mc mb local/weekly-previews --ignore-existing &&
  mc mb local/weekly-exports --ignore-existing &&
  echo Buckets OK
" 2>/dev/null || echo "Buckets 可能已存在"

# 5. 启动数据库和依赖
echo "启动服务..."
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d postgres clamav gotenberg
echo "等待 PostgreSQL..."
sleep 15

# 6. 数据库迁移
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml run --rm api python manage.py migrate --noinput

# 7. 创建管理员
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml run --rm api python manage.py shell -c "
from accounts.models import User, UserRole, AccountStatus
from organizations.models import Department
dept, _ = Department.objects.get_or_create(name='技术部', defaults={'code':'tech'})
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser(username='admin', password='Admin123!', display_name='系统管理员', role='super_admin', account_status='active', department=dept)
    print('Admin: admin / Admin123!')
else:
    print('Admin exists')
"

# 8. 启动全部
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d

echo ""
echo "========================================"
echo "  部署完成！"
echo "  访问: http://$(hostname -I | awk '{print $1}'):9527"
echo "  管理员: admin / Admin123!"
echo "========================================"
