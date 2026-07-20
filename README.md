# 周报整合系统

Vue 3 + Django + PostgreSQL + Celery + MinIO + Gotenberg

## 一键部署（生产环境）

```bash
git clone -b dev https://github.com/guoyi248/zhoubao_fix.git weekly-report
cd weekly-report
chmod +x setup.sh
./setup.sh
```

部署完成后访问 `http://<服务器IP>:9527`，管理员 `admin` / `Admin123!`

### 前置要求

- Debian 11/12/13 或 Ubuntu 20.04+
- Docker 已安装运行（`docker ps` 能跑）
- Python 3.11+

### setup.sh 做了什么

1. 检测 Python、pip、Docker、openssl，缺失自动安装
2. 创建目录和密钥（`deploy/secrets/`）
3. 生成 `deploy/config/app.env` 环境变量
4. 启动 Docker 服务：PostgreSQL、Redis、MinIO、Gotenberg、ClamAV
5. 创建 MinIO 存储桶
6. 安装 Python 依赖
7. 数据库迁移
8. 创建管理员账号
9. 启动 Nginx（反向代理 + 前端静态文件）
10. 启动 Gunicorn（Django API）

### 服务端口

| 端口 | 服务 | 说明 |
|---|---|---|
| 9527 | Nginx | 用户访问入口 |
| 5432 | PostgreSQL | 数据库 |
| 6379 | Redis | 缓存和队列 |
| 9100 | MinIO S3 | 文件存储 |
| 3000 | Gotenberg | Word/Excel→PDF 转换 |
| 3310 | ClamAV | 病毒扫描 |

### 如果已有 MinIO/Redis

setup.sh 会自动检测容器名 `update-url-minio` 和 `geotrellis-redis`，如果存在就复用，不重复创建。

### 自定义端口

编辑 `deploy/compose.production.yaml`，修改 Nginx 的 `ports` 即可：

```yaml
nginx:
  ports:
    - "你的端口:80"
```

同时修改 `deploy/config/app.env` 中对应服务的连接地址。

## 开发环境

### 后端

```bash
cd backend
pip install django djangorestframework django-cors-headers celery redis psycopg[binary] boto3 Pillow PyMuPDF argon2-cffi django-otp python-magic requests fpdf2 python-docx openpyxl python-pptx
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

访问 `http://localhost:5173`

### Docker 基础设施（开发用）

```bash
docker compose -f deploy/compose.yaml up -d
```

## 技术栈

| 层级 | 技术 |
|---|---|
| 前端 | Vue 3 + TypeScript + Vite 8.x + Element Plus + Pinia |
| 后端 | Python 3.13 + Django + DRF |
| 异步 | Celery 5.6 + Redis 7 |
| 数据库 | PostgreSQL 17 |
| 存储 | MinIO (S3 兼容) |
| 转换 | Gotenberg (LibreOffice) |
| 安全 | ClamAV + Django Session + CSRF + Argon2 |
| 部署 | Docker Compose + Nginx + Gunicorn |

## 项目结构

```
├── backend/              # Django 模块化单体
│   ├── config/           # 设置、URL、Celery、WSGI
│   ├── accounts/         # 用户、角色、TOTP
│   ├── organizations/    # 部门
│   ├── reporting/        # 周期、周报、修订
│   ├── attachments/      # 上传、扫描、预览
│   ├── analysis/         # LLM 分析
│   ├── meetings/         # 组会
│   ├── private_plans/    # 个人计划
│   ├── audit/            # 审计
│   ├── system_config/    # 系统配置
│   └── common/           # 共享基础设施
├── frontend/             # Vue 3 SPA
├── docker/               # Dockerfile（可选）
├── deploy/               # Compose、Nginx 配置
├── setup.sh              # 一键部署脚本（入口）
└── README.md
```
