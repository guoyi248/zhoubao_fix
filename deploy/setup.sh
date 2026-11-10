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
mkdir -p data/postgres data/clamav deploy/config
umask 077
mkdir -p deploy/secrets
chmod 700 deploy/secrets

if [ ! -f deploy/secrets/postgres_password ]; then
  openssl rand -base64 24 | tr -d '\n' > deploy/secrets/postgres_password
fi
find deploy/secrets -maxdepth 1 -type f -exec chmod 600 {} +

minio_user_file=deploy/secrets/minio_root_user
minio_password_file=deploy/secrets/minio_root_password
old_minio=$(docker ps --all --quiet --filter label=com.docker.compose.project=weekly-report \
  --filter label=com.docker.compose.service=minio --filter label=com.docker.compose.oneoff=False)

prepare_minio_root() {
  # 已有文件是部署者的配置。成对缺失才允许初始化，部分丢失必须从备份恢复。
  if [ -s "$minio_user_file" ] && [ -s "$minio_password_file" ]; then return; fi
  if [ -e "$minio_user_file" ] || [ -e "$minio_password_file" ]; then
    echo "请补齐 deploy/secrets/minio_root_user 和 minio_root_password 中的原始凭据。" >&2
    return 1
  fi
  local root_user="" root_password="" stored_data=""
  if [ -d data/minio ]; then stored_data=$(find data/minio -mindepth 1 -maxdepth 1 -print -quit); fi
  if [ -n "$old_minio" ] || [ -n "$stored_data" ]; then
    if [ -n "$old_minio" ]; then
      # 升级旧版本时只从本 Compose 项目的 MinIO 读取原 root 值，不写入日志。
      root_user=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$old_minio" | sed -n 's/^MINIO_ROOT_USER=//p')
      root_password=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$old_minio" | sed -n 's/^MINIO_ROOT_PASSWORD=//p')
    fi
    if [ -z "$root_user" ] || [ -z "$root_password" ]; then
      echo "已有 MinIO 数据，无法自动恢复 root 凭据。请将原始值分别写入 $minio_user_file 和 $minio_password_file 后重试。" >&2
      return 1
    fi
  elif [ "$#" -eq 2 ]; then
    root_user=$1
    root_password=$2
  else
    root_user="weekly-$(openssl rand -hex 8)"
    root_password=$(openssl rand -hex 32)
  fi
  if [ "${#root_user}" -lt 3 ] || [ "${#root_password}" -lt 8 ]; then
    echo "请提供有效的 MinIO root 凭据。" >&2; return 1
  fi
  (set -C; printf '%s' "$root_user" > "$minio_user_file" && printf '%s' "$root_password" > "$minio_password_file")
}

# 双引号 dotenv 字面量，保留部署者提供的密码中的空格、引号和美元符。
dotenv_secret() {
  "$PYTHON" -c 'import json, sys; from pathlib import Path; print(json.dumps(Path(sys.argv[1]).read_text().rstrip("\r\n"), ensure_ascii=False).replace("$", "$$"))' "$1"
}

# ── 2. app.env ──
if [ ! -f deploy/config/app.env ]; then
  # A previous deployment may have used an env key that differs from the old key file.
  # Never choose a replacement for it when the original deployment config is missing.
  old_api=$(docker ps --all --quiet --filter label=com.docker.compose.project=weekly-report \
    --filter label=com.docker.compose.service=api)
  stored_db=$(find data/postgres -mindepth 1 -maxdepth 1 -print -quit)
  if [ -e deploy/secrets/django_secret_key ] || [ -n "$old_api" ] || [ -n "$stored_db" ]; then
    echo "检测到既有部署，请先恢复原 deploy/config/app.env 和它使用的主钥，再运行安装。" >&2
    exit 1
  fi
  prepare_minio_root
  # Only this subdirectory is mounted in Django containers (uid 10001).
  # Its parent on the host is private. A complete key is published without overwriting a concurrent install.
  key_dir=deploy/secrets/django
  mkdir -p "$key_dir"
  chmod 755 "$key_dir"
  if [ ! -e "$key_dir/key" ]; then
    (
      draft=$(mktemp "$key_dir/.key.XXXXXX")
      trap 'rm -f -- "$draft"' EXIT
      openssl rand -base64 -out "$draft" 48
      chmod 444 "$draft"
      ln "$draft" "$key_dir/key" || test -s "$key_dir/key"
    )
  fi
  if [ ! -f "$key_dir/key" ] || [ ! -s "$key_dir/key" ]; then
    echo "Django 主钥文件无效，请检查 $key_dir/key。" >&2
    exit 1
  fi
  chmod 444 "$key_dir/key"
  cat > deploy/config/app.env << EOF
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_ALLOWED_HOSTS=*
DJANGO_SECRET_KEY_FILE=/run/secrets/weekly-django/key
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
S3_ACCESS_KEY=$(dotenv_secret "$minio_user_file")
S3_SECRET_KEY=$(dotenv_secret "$minio_password_file")
S3_BUCKET_ORIGINALS=weekly-originals
S3_BUCKET_PREVIEWS=weekly-previews
S3_BUCKET_EXPORTS=weekly-exports
CLAMAV_HOST=clamav
CLAMAV_PORT=3310
GOTENBERG_URL=http://gotenberg:3000
MAX_UPLOAD_BYTES=104857600
EOF
  cat backend/.env.example >> deploy/config/app.env
fi
umask 022

# 由 Compose 解析 env_file，保留现有部署的引号、插值和自定义桶名。
mapfile -t storage < <(docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml config --format json | "$PYTHON" -c '
import json,sys
from urllib.parse import urlsplit
env=json.load(sys.stdin)["services"]["api"]["environment"]
endpoint=env.get("S3_ENDPOINT", "")
print("bundled" if urlsplit(endpoint).hostname == "minio" else "external")
for key, default in (("S3_ENDPOINT",""), ("S3_ACCESS_KEY",""), ("S3_SECRET_KEY",""), ("S3_BUCKET_ORIGINALS","weekly-originals"),
                     ("S3_BUCKET_PREVIEWS","weekly-previews"), ("S3_BUCKET_EXPORTS","weekly-exports")):
    # Compose config 转义字面量美元符，以便其输出可作为新的 Compose 文件读取。
    print(env.get(key, default).replace("$$", "$"))
')
if [ "${#storage[@]}" -ne 7 ] || [ -z "${storage[1]}" ]; then
  echo "请检查 deploy/config/app.env 中的 S3 配置。" >&2; exit 1
fi
infra=(postgres redis clamav gotenberg)
if [ "${storage[0]}" = bundled ] || [ -n "$old_minio" ]; then
  # 外部 S3 不获得本地 root 身份。升级时原有本地存储也重建为仅容器网络可见。
  if [ "${storage[0]}" = bundled ]; then
    (umask 077; prepare_minio_root "${storage[2]}" "${storage[3]}")
  else
    (umask 077; prepare_minio_root)
  fi
  infra+=(minio)
fi

# ── 3. 启动 Docker 服务 ──
echo "========================================"
echo "  [3/9] 启动基础设施容器"
echo "========================================"
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d "${infra[@]}"
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

# ── 4. MinIO Buckets ──
echo "  [4/9] 初始化 MinIO 存储桶"
if [ "${storage[0]}" = bundled ]; then
  export S3_ENDPOINT="${storage[1]}" S3_BUCKET_ORIGINALS="${storage[4]}" S3_BUCKET_PREVIEWS="${storage[5]}" S3_BUCKET_EXPORTS="${storage[6]}"
  docker run --rm --network weekly-report_backend --entrypoint sh \
    -v "$PROJECT_DIR/$minio_user_file:/run/secrets/root_user:ro" \
    -v "$PROJECT_DIR/$minio_password_file:/run/secrets/root_password:ro" \
    -e S3_ENDPOINT -e S3_BUCKET_ORIGINALS -e S3_BUCKET_PREVIEWS -e S3_BUCKET_EXPORTS minio/mc -ec '
    tries=0
    until mc alias set local "$S3_ENDPOINT" "$(cat /run/secrets/root_user)" "$(cat /run/secrets/root_password)" >/dev/null; do
      tries=$((tries + 1))
      [ "$tries" -lt 20 ] || { echo "无法连接 MinIO，请检查服务和凭据" >&2; exit 1; }
      sleep 2
    done
    mc mb --ignore-existing "local/$S3_BUCKET_ORIGINALS" "local/$S3_BUCKET_PREVIEWS" "local/$S3_BUCKET_EXPORTS"
  '
  unset S3_ENDPOINT S3_BUCKET_ORIGINALS S3_BUCKET_PREVIEWS S3_BUCKET_EXPORTS
  echo "  ✓ 存储桶就绪"
else
  echo "  使用现有外部 S3。请确保配置的存储桶已创建，并已授权应用读写。"
fi
unset storage

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
echo "收集静态文件..."
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml run --rm api python backend/manage.py collectstatic --noinput 2>&1 | tail -3
echo "  ✓ 静态文件收集完成"
echo ""

echo "========================================"
echo "  [8/9] 创建管理员"
echo "========================================"
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml run --rm api python backend/manage.py shell -c "
from secrets import token_urlsafe
from accounts.models import User, UserRole, AccountStatus
from organizations.models import Department
dept, _ = Department.objects.get_or_create(name='技术部', defaults={'code':'tech'})
if not User.objects.filter(username='admin').exists():
    password = token_urlsafe(18)
    User.objects.create_user(username='admin', password=password, display_name='系统管理员', role=UserRole.ADMIN, account_status=AccountStatus.ACTIVE, department=dept)
    print('  ✓ 初始管理员账号为 admin，首次登录密码为', password)
else:
    print('  ✓ 管理员已存在')
"
echo ""

echo "========================================"
echo "  [9/9] 构建并启动 Nginx（首次编译前端约需 3-5 分钟）"
echo "========================================"
echo "构建 Nginx 镜像（含 Vue 前端编译）..."
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml build nginx
echo "  ✓ Nginx 镜像构建完成"
echo "启动 Nginx 容器..."
docker compose -f deploy/compose.yaml -f deploy/compose.production.yaml up -d --build nginx worker scheduler
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
echo "  管理员:    admin"
echo "========================================"
echo ""
echo "运行状态检查: docker ps"
