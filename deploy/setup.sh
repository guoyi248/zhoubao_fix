#!/bin/bash
# ============================================================
# 周报系统 — 一键部署脚本
# 用法: chmod +x setup.sh && ./setup.sh
# ============================================================
set -e

echo "========================================"
echo "  周报整合系统 — 一键部署"
echo "========================================"

# 1. 创建目录
mkdir -p /srv/weekly-report/{data/{postgres,redis,minio,clamav},secrets,config,certs}
chmod 700 /srv/weekly-report/secrets

# 2. 生成密钥
if [ ! -f /srv/weekly-report/secrets/django_secret_key ]; then
  openssl rand -base64 48 | tr -d '\n' > /srv/weekly-report/secrets/django_secret_key
fi
if [ ! -f /srv/weekly-report/secrets/postgres_password ]; then
  openssl rand -base64 24 | tr -d '\n' > /srv/weekly-report/secrets/postgres_password
fi
echo "minioadmin" > /srv/weekly-report/secrets/minio_root_user
openssl rand -base64 24 | tr -d '\n' > /srv/weekly-report/secrets/minio_root_password
echo "weekly-app-key-change-me" > /srv/weekly-report/secrets/s3_secret_key
chmod 600 /srv/weekly-report/secrets/*

# 3. 环境变量
cat > /srv/weekly-report/config/app.env << 'EOF'
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_ALLOWED_HOSTS=*
APP_TIME_ZONE=Asia/Shanghai
DATABASE_HOST=postgres
DATABASE_PORT=5432
DATABASE_NAME=weekly_report
DATABASE_USER=weekly_app
REDIS_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_BUCKET_ORIGINALS=weekly-originals
S3_BUCKET_PREVIEWS=weekly-previews
S3_BUCKET_EXPORTS=weekly-exports
CLAMAV_HOST=clamav
CLAMAV_PORT=3310
GOTENBERG_URL=http://gotenberg:3000
MAX_UPLOAD_BYTES=104857600
ENABLE_LLM=false
EOF

# 4. 启动
cd /srv/weekly-report
docker compose -f compose.yaml -f compose.production.yaml up -d postgres redis minio
sleep 10

# 5. MinIO buckets
docker compose -f compose.yaml -f compose.production.yaml exec -T minio mc alias set local http://localhost:9000 minioadmin minioadmin
docker compose -f compose.yaml -f compose.production.yaml exec -T minio mc mb local/weekly-originals --ignore-existing
docker compose -f compose.yaml -f compose.production.yaml exec -T minio mc mb local/weekly-previews --ignore-existing
docker compose -f compose.yaml -f compose.production.yaml exec -T minio mc mb local/weekly-exports --ignore-existing

# 6. 数据库
docker compose -f compose.yaml -f compose.production.yaml run --rm api python manage.py migrate --noinput

# 7. 创建管理员
docker compose -f compose.yaml -f compose.production.yaml run --rm api python manage.py shell -c "
from accounts.models import User, UserRole, AccountStatus
from organizations.models import Department
dept, _ = Department.objects.get_or_create(name='技术部', defaults={'code':'tech'})
User.objects.create_superuser(username='admin', password='Admin123!', display_name='系统管理员', role='super_admin', account_status='active', department=dept)
print('Admin created: admin / Admin123!')
"

# 8. 启动全部
docker compose -f compose.yaml -f compose.production.yaml up -d

echo ""
echo "========================================"
echo "  部署完成！"
echo "  访问: http://<服务器IP>"
echo "  管理员: admin / Admin123!"
echo "========================================"
