import hashlib
import json
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from system_config.integrations import get_config
from attachments.tasks import read_attachment_text
from common.exceptions import ObjectNotFound
from system_config.credentials import CredentialUnavailable
from reporting.models import WeeklyReportRevision
from .llm_client import llm_client
from .models import AnalysisRun, AnalysisItem, AnalysisItemSource

logger = logging.getLogger(__name__)


@transaction.atomic
def _reserve(revision, force=False):
    WeeklyReportRevision.objects.select_for_update().get(pk=revision.pk)
    latest = AnalysisRun.objects.filter(revision=revision).order_by("-created_at").first()
    if latest and (not force or latest.status in {"queued", "running"}):
        return latest, False
    run = AnalysisRun.objects.create(revision=revision, model_name=get_config("model")["model"],
        prompt_version="v2", schema_version="v1.0", input_text_hash="", output_json={}, status="queued")
    return run, True


def queue_revision(revision, force=False):
    run, created = _reserve(revision, force)
    if created and not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        transaction.on_commit(lambda: analyze_report.delay(str(revision.pk), str(run.pk)), robust=True)
    return run


def _has_text(value):
    if isinstance(value, dict):
        return any(_has_text(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_text(item) for item in value)
    return value is not None and bool(str(value).strip())


def _inputs(revision):
    sources = []
    warnings = []
    content = revision.structured_content_json
    if _has_text(content):
        sources.append(("周报正文", json.dumps(content, ensure_ascii=False)))
    files = list(revision.attachments.order_by("created_at", "id"))
    if revision.confirmed_pdf_attachment_id and all(f.pk != revision.confirmed_pdf_attachment_id for f in files):
        files.append(revision.confirmed_pdf_attachment)
    for file in files:
        try:
            text = read_attachment_text(file)
        except (ObjectNotFound, FileNotFoundError):
            warnings.append(f"未找到文件：{file.original_filename}")
            continue
        if text.strip():
            sources.append((f"附件 {file.pk} · {file.original_filename}", text))
        else:
            warnings.append(f"未提取到文字：{file.original_filename}")
    if not sources:
        return "", [], warnings
    # 优先分配短文档，每份可读附件均保留输入份额。
    remaining = settings.LLM_MAX_INPUT_CHARS
    portions = {}
    for i, (label, text) in enumerate(sorted(sources, key=lambda pair: len(pair[1]))):
        allowance = remaining // (len(sources) - i)
        portions[label] = text[:allowance]
        remaining -= len(portions[label])
        if len(text) > allowance:
            warnings.append(f"内容已截取：{label}")
    body = portions.pop("周报正文", "")
    return body, [f"{label}\n{text}" for label, text in portions.items()], warnings


@shared_task(ignore_result=True)
def analyze_report(revision_id: str, run_id=None):
    if not get_config("model")["enabled"]:
        return
    revision = WeeklyReportRevision.objects.filter(pk=revision_id).select_related("confirmed_pdf_attachment").first()
    if not revision:
        return
    if run_id is None:
        run_id = _reserve(revision)[0].pk
    claim = timezone.now()
    runs = AnalysisRun.objects.filter(pk=run_id, revision=revision)
    if not runs.filter(status="queued").update(status="running", updated_at=claim):
        return
    owned = runs.filter(status="running", updated_at=claim)
    error = "解析失败，请检查文件和模型服务后重试。"
    try:
        body, files, warnings = _inputs(revision)
        if not body and not files:
            error = "这版周报没有可提取的文字。请上传含文本层的文件后重新提交。"
            owned.update(status="failed", error_message=error, updated_at=timezone.now())
            return
        result = llm_client.analyze_report(body, files)
        digest = hashlib.sha256(json.dumps([body, files], ensure_ascii=False).encode()).hexdigest()
        with transaction.atomic():
            run = owned.select_for_update().first()
            if not run:
                return
            _save_items(run, result["output"])
            run.status = "completed"
            run.input_text_hash = digest
            run.output_json = {**result["output"], "input_warnings": warnings}
            run.model_name = result["model"]
            run.tokens_used = result.get("tokens_used") or 0
            run.save()
    except Exception as exc:
        # 日志和 API 都不回显请求正文、密钥或模型服务响应。
        if isinstance(exc, CredentialUnavailable):
            error = str(exc)
        logger.warning("Analysis %s failed (%s)", run_id, type(exc).__name__)
        owned.update(status="failed", error_message=error, updated_at=timezone.now())


@shared_task(ignore_result=True)
def dispatch_pending():
    """重投漏发的任务，并接管中断的工作进程；通过条件更新防止重复落库。"""
    if not get_config("model")["enabled"]:
        return
    now = timezone.now()
    wait = (settings.LLM_CONNECT_TIMEOUT_SECONDS + settings.LLM_READ_TIMEOUT_SECONDS + 15) * (settings.LLM_MAX_RETRIES + 1)
    AnalysisRun.objects.filter(status="running", updated_at__lt=now - timedelta(seconds=wait+300)).update(status="queued", updated_at=now)
    queued = AnalysisRun.objects.filter(status="queued").order_by("created_at")
    if not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        queued = queued.filter(updated_at__lt=now-timedelta(minutes=2))
    for revision_id, run_id in list(queued.values_list("revision_id", "pk")[:25]):
        analyze_report.delay(str(revision_id), str(run_id))


def _save_items(analysis_run: AnalysisRun, output: dict) -> None:
    """保存分析条目和来源。"""
    mapping = {
        "achievements": AnalysisItem.ItemType.ACHIEVEMENT,
        "risks": AnalysisItem.ItemType.RISK,
        "blockers": AnalysisItem.ItemType.BLOCKER,
        "coordination_requests": AnalysisItem.ItemType.COORDINATION,
        "next_week_plans": AnalysisItem.ItemType.NEXT_PLAN,
        "meeting_topics": AnalysisItem.ItemType.MEETING_TOPIC,
    }

    for field, item_type in mapping.items():
        for entry in output.get(field, []):
            item = AnalysisItem.objects.create(
                analysis_run=analysis_run,
                item_type=item_type,
                title=entry["title"][:500],
                detail=entry.get("detail") or entry.get("reason") or "",
                project=(entry.get("project") or "")[:300],
                confidence=entry.get("confidence", 0.0),
                original_ai_output=entry,
            )

            # 保存来源
            for src in entry.get("sources", []):
                AnalysisItemSource.objects.create(
                    item=item,
                    source_type=src.get("source_type", "report_field"),
                    source_id=src.get("source_id", ""),
                    page=src.get("page", 1),
                    quote_hash=src.get("quote_hash", ""),
                )
