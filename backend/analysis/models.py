"""
AI 分析模型：
- AnalysisRun：单次分析运行
- AnalysisItem：分析结果条目
- AnalysisItemSource：来源追溯
- AnalysisHumanRevision：人工修订记录
- TeamSummarySnapshot：团队总表快照
"""

from django.conf import settings
from django.db import models
from common.models import BaseModel


class AnalysisRun(BaseModel):
    """一次 AI 分析运行。"""

    revision = models.ForeignKey(
        "reporting.WeeklyReportRevision",
        on_delete=models.CASCADE,
        related_name="analysis_runs",
    )
    model_name = models.CharField("模型标识", max_length=200)
    prompt_version = models.CharField("Prompt 版本", max_length=50)
    input_text_hash = models.CharField("输入文本哈希", max_length=64)
    output_json = models.JSONField("原始 AI 输出")
    schema_version = models.CharField("Schema 版本", max_length=50)
    status = models.CharField("状态", max_length=30, default="completed")
    error_message = models.TextField("错误信息", blank=True, default="")
    tokens_used = models.IntegerField("Token 用量", default=0)
    generated_at = models.DateTimeField("生成时间", auto_now_add=True)

    class Meta:
        db_table = "analysis_runs"
        verbose_name = "分析运行"
        verbose_name_plural = "分析运行"


class AnalysisItem(BaseModel):
    """AI 分析的单条结果。"""

    class ItemType(models.TextChoices):
        ACHIEVEMENT = "achievement", "完成事项"
        RISK = "risk", "风险"
        BLOCKER = "blocker", "阻塞"
        COORDINATION = "coordination", "待协调"
        NEXT_PLAN = "next_plan", "下周计划"
        MEETING_TOPIC = "meeting_topic", "建议组会讨论"

    analysis_run = models.ForeignKey(
        AnalysisRun,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item_type = models.CharField("类型", max_length=20, choices=ItemType.choices)
    title = models.CharField("标题", max_length=500)
    detail = models.TextField("详情", blank=True, default="")
    project = models.CharField("项目", max_length=300, blank=True, default="")
    confidence = models.FloatField("置信度", default=0.0)
    human_status = models.CharField(
        "人工确认状态",
        max_length=20,
        default="pending",  # pending / confirmed / modified / rejected
    )
    human_revision_comment = models.TextField("人工修订说明", blank=True, default="")

    # AI 原始输出保留
    original_ai_output = models.JSONField("原始 AI 条目", default=dict)

    class Meta:
        db_table = "analysis_items"
        verbose_name = "分析条目"
        verbose_name_plural = "分析条目"
        indexes = [
            models.Index(fields=["analysis_run", "item_type"]),
        ]


class AnalysisItemSource(BaseModel):
    """分析条目与来源的关联（周报字段或附件页码）。"""

    class SourceType(models.TextChoices):
        REPORT_FIELD = "report_field", "周报字段"
        ATTACHMENT = "attachment", "附件"

    item = models.ForeignKey(
        AnalysisItem,
        on_delete=models.CASCADE,
        related_name="sources",
    )
    source_type = models.CharField("来源类型", max_length=20, choices=SourceType.choices)
    source_id = models.CharField("来源 ID", max_length=255)
    page = models.IntegerField("页码", default=1)
    quote_hash = models.CharField("引用哈希", max_length=64, blank=True, default="")

    class Meta:
        db_table = "analysis_item_sources"
        verbose_name = "来源追溯"
        verbose_name_plural = "来源追溯"


class AnalysisHumanRevision(BaseModel):
    """人工修订记录——保留原始 AI 输出和修改后版本。"""

    item = models.ForeignKey(
        AnalysisItem,
        on_delete=models.CASCADE,
        related_name="human_revisions",
    )
    revised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="analysis_revisions",
    )
    previous_data = models.JSONField("修订前数据")
    new_data = models.JSONField("修订后数据")

    class Meta:
        db_table = "analysis_human_revisions"
        verbose_name = "人工修订"
        verbose_name_plural = "人工修订"


class TeamSummarySnapshot(BaseModel):
    """团队总表快照。"""

    reporting_period = models.ForeignKey(
        "reporting.ReportingPeriod",
        on_delete=models.CASCADE,
        related_name="team_summaries",
    )
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="generated_summaries",
    )
    data_json = models.JSONField("总表数据")
    item_count = models.IntegerField("条目数", default=0)

    class Meta:
        db_table = "team_summary_snapshots"
        verbose_name = "团队总表"
        verbose_name_plural = "团队总表"
