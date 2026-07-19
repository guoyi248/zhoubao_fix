#!/bin/bash
# ============================================================
# 周报系统 — 一键部署脚本 (Debian 12)
# 用法: chmod +x setup.sh && ./setup.sh
# ============================================================
set -e

echo "========================================"
echo "  周报整合系统 — 一键部署"
echo "========================================"

# 1. 创建目录
mkdir -p /srv/weekly-report/{data/postgres,data/clamav,secrets,config,certs}
chmod 700 /srv/weekly-report/secrets

# 2. 生成密钥
if [ ! -f /srv/weekly-report/secrets/django_secret_key ]; then
  openssl rand -base64 48 | tr -d '\n' > /srv/weekly-report/secrets/django_secret_key
fi
if [ ! -f /srv/weekly-report/secrets/postgres_password ]; then
  openssl rand -base64 24 | tr -d '\n' > /srv/weekly-report/secrets/postgres_password
fi
echo "hjy12345678" > /srv/weekly-report/secrets/s3_secret_key
chmod 600 /srv/weekly-report/secrets/*

# 3. 环境变量（共用已有 Redis + MinIO）
cat > /srv/weekly-report/config/app.env << 'EOF'
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_ALLOWED_HOSTS=*
CSRF_TRUSTED_ORIGINS=http://localhost:9527
APP_TIME_ZONE=Asia/Shanghai
DATABASE_HOST=postgres
DATABASE_PORT=5432
DATABASE_NAME=weekly_report
DATABASE_USER=weekly_app
REDIS_URL=redis://host.docker.internal:6379/0
CELERY_RESULT_BACKEND=redis://host.docker.internal:6379/1
S3_ENDPOINT=http://host.docker.internal:9000
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

# 4. MinIO 创建 Bucket（用你已有的 MinIO）
echo "创建 MinIO Bucket..."
cd /srv/weekly-report
docker run --rm --network host --entrypoint sh minio/mc -c "
  mc alias set local http://localhost:9000 hjy hjy12345678 &&
  mc mb local/weekly-originals --ignore-existing &&
  mc mb local/weekly-previews --ignore-existing &&
  mc mb local/weekly-exports --ignore-existing &&
  echo 'Buckets ready'
" 2>/dev/null || echo "Bucket 可能已存在，跳过"

# 5. 启动（postgres 先起来）
docker compose -f compose.yaml -f compose.production.yaml up -d postgres clamav gotenberg
echo "等待 PostgreSQL 就绪..."
sleep 10

# 6. 数据库迁移
docker compose -f compose.yaml -f compose.production.yaml run --rm api python manage.py migrate --noinput

# 7. 创建管理员
docker compose -f compose.yaml -f compose.production.yaml run --rm api python manage.py shell -c "
from accounts.models import User, UserRole, AccountStatus
from organizations.models import Department
dept, _ = Department.objects.get_or_create(name='技术部', defaults={'code':'tech'})
if not User.objects.filter(username='admin').exists():
    admin = User.objects.create_user(username='admin', password='Admin123!', display_name='系统管理员', role='super_admin', account_status='active', department=dept)
    print('Admin created: admin / Admin123!')
else:
    print('Admin exists')
"

# 8. 启动全部
docker compose -f compose.yaml -f compose.production.yaml up -d

echo ""
echo "========================================"
echo "  部署完成！"
echo "  访问: http://<服务器IP>:9527"
echo "  管理员: admin / Admin123!"
echo "========================================"
