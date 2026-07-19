# 周报整合系统

模块化单体架构，Django 5.2 LTS + Vue 3 + PostgreSQL 17 + Celery + MinIO。

## 快速开始（开发）

### 1. 启动基础设施

```bash
docker compose -f deploy/compose.yaml up -d postgres redis
```

### 2. 后端

```bash
cd backend
pip install -e ..
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

### 3. 前端

```bash
cd frontend
npm install
npm run dev
```

### 4. 访问

- 前端: http://localhost:5173
- API: http://localhost:8000/api/v1/

## 技术栈

| 层级 | 技术 |
|---|---|
| 前端 | Vue 3 + TypeScript + Vite 8.1.x + Element Plus + Pinia |
| 后端 | Python 3.13 + Django 5.2 LTS + DRF |
| 异步 | Celery 5.6.3 + Redis 7.4 |
| 数据库 | PostgreSQL 17 |
| 存储 | MinIO (S3 兼容) |
| 安全 | ClamAV + Django Session + CSRF + Argon2 + TOTP |
| 部署 | Docker Compose + Nginx |

## 项目结构

```
weekly-report/
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
├── docker/               # Dockerfile
├── deploy/               # Compose、Nginx 配置
├── tests/                # 测试
└── docs/                 # 文档
```

## 许可证

Proprietary — 内部使用
