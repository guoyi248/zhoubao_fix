"""
Django 基础设置。
与具体环境无关的共享配置。
"""

import os
from datetime import time
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# 单机开发读取 backend/.env，系统环境变量优先。部署通过 Compose 的 env_file 注入。
if os.environ.get("DJANGO_SETTINGS_MODULE") == "config.settings.development":
    local_env = BASE_DIR.parent / ".env"
    if local_env.is_file():
        for line in local_env.read_text(encoding="utf-8-sig").splitlines():
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            key, sep, value = entry.partition("=")
            if not sep or not key.strip().isidentifier():
                raise ImproperlyConfigured("backend/.env 需要每行一个 KEY=value")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)

# Existing installations may have encrypted credentials with the environment value.
# Keep that exact value even when a file is also configured.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    secret_key_file = os.environ.get("DJANGO_SECRET_KEY_FILE")
    if secret_key_file:
        try:
            SECRET_KEY = Path(secret_key_file).read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeError) as exc:
            raise ImproperlyConfigured("无法读取 DJANGO_SECRET_KEY_FILE，请检查主钥文件和挂载权限。") from exc
        if not SECRET_KEY.strip():
            raise ImproperlyConfigured("DJANGO_SECRET_KEY_FILE 的主钥文件为空。")
    else:
        SECRET_KEY = "CHANGE-ME-IN-PRODUCTION"

DEBUG = False

AUDIT_LOCATION_NETWORKS = os.environ.get("AUDIT_LOCATION_NETWORKS", "")
AUDIT_TRUSTED_PROXIES = os.environ.get("AUDIT_TRUSTED_PROXIES", "")
AUDIT_TRUSTED_PROXY_HOSTS = os.environ.get("AUDIT_TRUSTED_PROXY_HOSTS", "")
AUDIT_GEOIP_DATABASE = os.environ.get("AUDIT_GEOIP_DATABASE", "")

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
    "knowledge",
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

STATIC_URL = "/static/"
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
    "DATETIME_FORMAT": "iso-8601",
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
CLAMAV_SCAN_UPLOADS = True
CLAMAV_HOST = os.environ.get("CLAMAV_HOST", "localhost")
CLAMAV_PORT = int(os.environ.get("CLAMAV_PORT", "3310"))

# LibreOffice
PREVIEW_TIMEOUT_SECONDS = int(os.environ.get("PREVIEW_TIMEOUT_SECONDS", "120"))

# 周报提醒
WEEKLY_REMINDERS_ENABLED = os.environ.get("ENABLE_WEEKLY_REMINDERS", "false").lower() == "true"
WEEKLY_SITE_URL = os.environ.get("WEEKLY_SITE_URL", "")
REMINDER_WEEKDAY = int(os.environ.get("REMINDER_WEEKDAY", "7"))
REMINDER_TIME = time.fromisoformat(os.environ.get("REMINDER_TIME", "18:00"))
if not 1 <= REMINDER_WEEKDAY <= 7:
    raise ImproperlyConfigured("REMINDER_WEEKDAY 应为 1（周一）到 7（周日）")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "true").lower() == "true"
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "false").lower() == "true"
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER)
EMAIL_TIMEOUT = 15
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "weekly-report-reminders": {"task": "reporting.tasks.send_weekly_reminders", "schedule": 300.0},
    "pending-progress-summaries": {"task": "analysis.tasks.dispatch_pending", "schedule": 60.0},
}

# LLM
LLM_ENABLED = os.environ.get("ENABLE_LLM", "false").lower() == "true"
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai_compatible")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY_ENCRYPTED = os.environ.get("LLM_API_KEY_ENCRYPTED", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
LLM_CONNECT_TIMEOUT_SECONDS = int(os.environ.get("LLM_CONNECT_TIMEOUT_SECONDS", "10"))
LLM_READ_TIMEOUT_SECONDS = int(os.environ.get("LLM_READ_TIMEOUT_SECONDS", "120"))
LLM_MAX_RETRIES = max(0, int(os.environ.get("LLM_MAX_RETRIES", "2")))
LLM_MAX_INPUT_CHARS = max(1, int(os.environ.get("LLM_MAX_INPUT_CHARS", "100000")))
