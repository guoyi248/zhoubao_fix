"""
生产环境设置。
所有敏感值从环境变量读取，不允许硬编码。
"""

from .base import *  # noqa: F403

DEBUG = False

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")  # noqa: F405

CSRF_TRUSTED_ORIGINS = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")  # noqa: F405

CORS_ALLOWED_ORIGINS = CSRF_TRUSTED_ORIGINS
CORS_ALLOW_CREDENTIALS = True

# HTTPS
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False  # 内网应用不提交 HSTS preload

# 静态文件
STATIC_ROOT = BASE_DIR / "staticfiles"  # noqa: F405
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"

# Celery
CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")  # noqa: F405
CELERY_RESULT_BACKEND = os.environ.get(  # noqa: F405
    "CELERY_RESULT_BACKEND",
    "redis://redis:6379/1",
)
