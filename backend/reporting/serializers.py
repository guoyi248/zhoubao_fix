"""
周报序列化器。
"""

from rest_framework import serializers
from .models import (
    ReportingPeriod,
    WeeklyReport,
    WeeklyReportRevision,
    AdminReportNote,
    ReportStatus,
)


class ReportingPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportingPeriod
        fields = [
            "id",
            "iso_year",
            "iso_week",
            "start_date",
            "end_date",
            "deadline",
            "status",
        ]


class SaveDraftSerializer(serializers.Serializer):
    """保存草稿。"""

    content = serializers.JSONField()
    version = serializers.IntegerField()  # optimistic_version


class SubmitReportSerializer(serializers.Serializer):
    """提交周报。"""

    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    confirmed_pdf_attachment_id = serializers.UUIDField(required=False, allow_null=True)


class WeeklyReportListSerializer(serializers.ModelSerializer):
    """周报列表（低信息量）。"""

    owner_name = serializers.CharField(source="owner.display_name")
    period_label = serializers.SerializerMethodField()

    class Meta:
        model = WeeklyReport
        fields = [
            "id",
            "owner_name",
            "period_label",
            "status",
            "owner_id",
            "reporting_period_id",
            "updated_at",
            "current_revision_id",
        ]

    def get_period_label(self, obj):
        return f"{obj.reporting_period.iso_year}-W{obj.reporting_period.iso_week:02d}"


class WeeklyReportDetailSerializer(serializers.ModelSerializer):
    """周报详情（含草稿内容和管理员可见字段）。"""

    owner_name = serializers.CharField(source="owner.display_name")
    owner_department = serializers.CharField(source="owner.department.name", default="")
    period = ReportingPeriodSerializer(source="reporting_period", read_only=True)
    revisions = serializers.SerializerMethodField()

    class Meta:
        model = WeeklyReport
        fields = [
            "id",
            "owner_id",
            "owner_name",
            "owner_department",
            "reporting_period_id",
            "period",
            "status",
            "draft_content_json",
            "current_revision_id",
            "optimistic_version",
            "created_at",
            "updated_at",
            "revisions",
        ]

    def get_revisions(self, obj):
        if obj.current_revision:
            return RevisionSerializer(
                obj.revisions.select_related("submitted_by").all(),
                many=True,
            ).data
        return []


class RevisionSerializer(serializers.ModelSerializer):
    submitted_by_name = serializers.CharField(source="submitted_by.display_name")

    class Meta:
        model = WeeklyReportRevision
        fields = [
            "id",
            "revision_no",
            "submitted_by_name",
            "submitted_at",
            "content_sha256",
            "reason",
            "confirmed_pdf_attachment_id",
        ]


class RevisionDetailSerializer(serializers.ModelSerializer):
    """修订版详情（含完整内容）。"""

    submitted_by_name = serializers.CharField(source="submitted_by.display_name")

    class Meta:
        model = WeeklyReportRevision
        fields = [
            "id",
            "revision_no",
            "structured_content_json",
            "submitted_by_name",
            "submitted_at",
            "content_sha256",
            "reason",
            "confirmed_pdf_attachment_id",
        ]


class AdminNoteSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.display_name", read_only=True)

    class Meta:
        model = AdminReportNote
        fields = ["id", "content", "author_name", "created_at"]
        read_only_fields = ["id", "author_name", "created_at"]


class CreateAdminNoteSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=5000)
