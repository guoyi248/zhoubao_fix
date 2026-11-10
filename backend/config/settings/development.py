"""
开发环境设置。
本地自动用 SQLite，Docker 中检测 DATABASE_HOST 则用 PostgreSQL。
"""

import os
from importlib.util import find_spec
from .base import *  # noqa: F403

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "api", "*"]

# 自动检测：如果 DATABASE_HOST 存在（Docker 环境），用 PostgreSQL
if os.environ.get("DATABASE_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DATABASE_NAME", "weekly_report"),
            "USER": os.environ.get("DATABASE_USER", "weekly_app"),
            "PASSWORD": os.environ.get("DATABASE_PASSWORD", "dev_password"),
            "HOST": os.environ["DATABASE_HOST"],
            "PORT": os.environ.get("DATABASE_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
        },
    }

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
CSRF_COOKIE_HTTPONLY = False  # 前端需要读取 CSRF cookie

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]
CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]

if find_spec("django_extensions"):
    INSTALLED_APPS = [*INSTALLED_APPS, "django_extensions"]  # noqa: F405

# Celery：优先读环境变量中的 Redis URL；开发模式同步执行
CELERY_BROKER_URL = os.environ.get("REDIS_URL", "memory://")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "cache+memory://")
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "true").lower() == "true"

# 单机开发未配置对象存储时，使用已有的本地附件目录。
USE_LOCAL_STORAGE = not any(os.environ.get(key) for key in ("S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY"))
CLAMAV_SCAN_UPLOADS = bool(os.environ.get("CLAMAV_HOST"))
MEDIA_ROOT = os.path.join(BASE_DIR, "media")  # noqa: F405
