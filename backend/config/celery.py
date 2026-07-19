"""
Celery 应用配置。
Worker 启动：celery -A config worker -Q <queues> --loglevel=INFO
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

app = Celery("weekly_report")

app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# ── 队列定义 ──────────────────────────────────────────────

app.conf.task_queues = {
    "default": {"exchange": "default", "routing_key": "default"},
    "preview": {"exchange": "preview", "routing_key": "preview"},
    "ai": {"exchange": "ai", "routing_key": "ai"},
}

app.conf.task_default_queue = "default"
app.conf.task_default_exchange = "default"
app.conf.task_default_routing_key = "default"

# ── 任务路由 ──────────────────────────────────────────────

app.conf.task_routes = {
    "attachments.tasks.scan.*": {"queue": "preview"},
    "attachments.tasks.convert.*": {"queue": "preview"},
    "attachments.tasks.extract.*": {"queue": "preview"},
    "attachments.tasks.thumbnail.*": {"queue": "preview"},
    "attachments.tasks.compatibility.*": {"queue": "preview"},
    "analysis.tasks.*": {"queue": "ai"},
    "analysis.tasks.rebuild_team_summary": {"queue": "ai"},
}

# ── 重试策略 ──────────────────────────────────────────────

app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True
app.conf.task_track_started = True

# AI 任务指数退避
app.conf.task_annotations = {
    "analysis.tasks.analyze_report": {
        "max_retries": 3,
        "default_retry_delay": 60,
        "retry_backoff": True,
        "autoretry_for": (Exception,),
    },
}
