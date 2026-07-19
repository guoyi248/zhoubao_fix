"""
测试环境设置。
使用 SQLite 内存数据库，关闭安全限制。
"""

from .base import *  # noqa: F403

DEBUG = False

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
}

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Celery 测试使用内存，不连接 Redis
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# 加速密码哈希
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]
