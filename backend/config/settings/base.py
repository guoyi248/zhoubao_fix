"""
Django 基础设置。
与具体环境无关的共享配置。
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "CHANGE-ME-IN-PRODUCTION")

DEBUG = False

ALLOWED_HOSTS: list[str] = []

# ── 应用定义 ──────────────────────────────────────────────

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "corsheaders",
    "django_otp",
    "django_otp.plugins.otp_totp",
]

LOCAL_APPS = [
    "accounts",
    "organizations",
    "reporting",
    "attachments",
    "analysis",
    "meetings",
    "private_plans",
    "audit",
    "system_config",
    "common",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ── 中间件 ────────────────────────────────────────────────

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "audit.middleware.AuditLogMiddleware",
]

ROOT_URLCONF = "config.urls"

# ── 模板 ──────────────────────────────────────────────────

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ── 数据库 ────────────────────────────────────────────────

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DATABASE_NAME", "weekly_report"),
        "USER": os.environ.get("DATABASE_USER", "weekly_app"),
        "PASSWORD": os.environ.get("DATABASE_PASSWORD", ""),
        "HOST": os.environ.get("DATABASE_HOST", "localhost"),
        "PORT": os.environ.get("DATABASE_PORT", "5432"),
        "CONN_MAX_AGE": 300,
        "OPTIONS": {
            "connect_timeout": 10,
        },
    }
}

# ── 密码哈希 ──────────────────────────────────────────────

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_USER_MODEL = "accounts.User"

# ── 认证与会话 ────────────────────────────────────────────

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
]

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_COOKIE_AGE = 8 * 3600  # 8 小时

CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_TRUSTED_ORIGINS: list[str] = []

# ── 安全 ──────────────────────────────────────────────────

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "SAMEORIGIN"
SECURE_REFERRER_POLICY = "same-origin"

# ── 国际化 ────────────────────────────────────────────────

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = os.environ.get("APP_TIME_ZONE", "Asia/Shanghai")
USE_I18N = True
USE_TZ = True

# ── 静态文件 ──────────────────────────────────────────────

STATIC_URL = "/assets/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ── 文件上传 ──────────────────────────────────────────────

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024  # 2 MiB, 大文件走流式

# ── DRF ───────────────────────────────────────────────────

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    "DEFAULT_PAGINATION_CLASS": "common.pagination.CursorPagination",
    "DEFAULT_PAGINATION_CLASS_RESULTS": 50,
    "EXCEPTION_HANDLER": "common.exceptions.api_exception_handler",
    "DATETIME_FORMAT": "%Y-%m-%dT%H:%M:%SZ",
    "UNAUTHENTICATED_USER": None,
}

# ── 日志 ──────────────────────────────────────────────────

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        "celery": {
            "handlers": ["console"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}

# ── 业务配置 ──────────────────────────────────────────────

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 104_857_600))  # 100 MiB
MAX_REPORT_ATTACHMENT_BYTES = int(os.environ.get("MAX_REPORT_ATTACHMENT_BYTES", 314_572_800))  # 300 MiB
MAX_ATTACHMENTS_PER_REPORT = int(os.environ.get("MAX_ATTACHMENTS_PER_REPORT", "20"))

# S3 / MinIO
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:9000")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")
S3_BUCKET_ORIGINALS = os.environ.get("S3_BUCKET_ORIGINALS", "weekly-originals")
S3_BUCKET_PREVIEWS = os.environ.get("S3_BUCKET_PREVIEWS", "weekly-previews")
S3_BUCKET_EXPORTS = os.environ.get("S3_BUCKET_EXPORTS", "weekly-exports")
S3_REGION = os.environ.get("S3_REGION", "internal-1")
SIGNED_URL_TTL_SECONDS = int(os.environ.get("SIGNED_URL_TTL_SECONDS", "180"))

# ClamAV
CLAMAV_HOST = os.environ.get("CLAMAV_HOST", "localhost")
CLAMAV_PORT = int(os.environ.get("CLAMAV_PORT", "3310"))

# LibreOffice
PREVIEW_TIMEOUT_SECONDS = int(os.environ.get("PREVIEW_TIMEOUT_SECONDS", "120"))

# LLM
LLM_ENABLED = os.environ.get("ENABLE_LLM", "false").lower() == "true"
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai_compatible")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
LLM_CONNECT_TIMEOUT_SECONDS = int(os.environ.get("LLM_CONNECT_TIMEOUT_SECONDS", "10"))
LLM_READ_TIMEOUT_SECONDS = int(os.environ.get("LLM_READ_TIMEOUT_SECONDS", "120"))
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "2"))
LLM_MAX_INPUT_CHARS = int(os.environ.get("LLM_MAX_INPUT_CHARS", "100000"))
