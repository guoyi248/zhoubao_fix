"""
AI 分析 Celery 任务：
- analyze_report: 对单份周报修订执行 LLM 分析
- rebuild_team_summary: 重建团队总表（Phase 4）
"""

import json
import logging
import hashlib

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from reporting.models import WeeklyReportRevision
from attachments.models import AttachmentExtractedText

from .models import AnalysisRun, AnalysisItem, AnalysisItemSource
from .llm_client import llm_client

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, retry_backoff=True)
def analyze_report(self, revision_id: str):
    """
    对一份周报修订执行 LLM 分析。
    输入：修订版的结构化正文 + 已确认附件的抽取文本
    输出：AnalysisRun + AnalysisItems（含来源追溯）
    """
    if not settings.LLM_ENABLED:
        return

    try:
        revision = WeeklyReportRevision.objects.select_related("report__owner").get(id=revision_id)
    except WeeklyReportRevision.DoesNotExist:
        logger.error("Revision %s not found", revision_id)
        return

    # 收集输入文本
    report_text = json.dumps(revision.structured_content_json, ensure_ascii=False)
    input_text_hash = hashlib.sha256(report_text.encode()).hexdigest()

    # 收集附件文本
    attachment_texts = []
    if revision.confirmed_pdf_attachment:
        extracted = AttachmentExtractedText.objects.filter(
            attachment=revision.confirmed_pdf_attachment
        ).first()
        if extracted and extracted.completeness != "empty":
            attachment_texts.append(extracted.content)

    try:
        result = llm_client.analyze_report(report_text, attachment_texts)

        # 保存分析运行
        analysis_run = AnalysisRun.objects.create(
            revision=revision,
            model_name=result["model"],
            prompt_version="v1.0",
            input_text_hash=input_text_hash,
            output_json=result["output"],
            schema_version="v1.0",
            tokens_used=result.get("tokens_used", 0),
        )

        # 保存各条目
        _save_items(analysis_run, result["output"])

        logger.info(
            "Analysis complete for revision %s: %d items",
            revision_id,
            AnalysisItem.objects.filter(analysis_run=analysis_run).count(),
        )

    except Exception as exc:
        logger.exception("LLM analysis failed for revision %s", revision_id)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

        # 最终失败也记录
        AnalysisRun.objects.create(
            revision=revision,
            model_name=settings.LLM_MODEL,
            prompt_version="v1.0",
            input_text_hash=input_text_hash,
            output_json={"error": str(exc)},
            schema_version="v1.0",
            status="failed",
            error_message=str(exc),
        )


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
                title=entry.get("title", ""),
                detail=entry.get("detail", ""),
                project=entry.get("project") or "",
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
