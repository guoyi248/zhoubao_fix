"""组会序列化器。"""

from rest_framework import serializers
from .models import (
    Meeting,
    MeetingReportSnapshot,
    MeetingReportState,
    ActionItem,
    MeetingStatus,
)


class ActionItemSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.display_name", read_only=True)
    created_by_name = serializers.CharField(source="created_by.display_name", read_only=True)

    class Meta:
        model = ActionItem
        fields = [
            "id",
            "title",
            "owner_id",
            "owner_name",
            "due_date",
            "status",
            "created_by_name",
            "resolved_at",
            "resolution_note",
            "created_at",
        ]
        read_only_fields = ["id", "created_by_name", "resolved_at", "created_at"]


class CreateActionItemSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=500)
    owner_id = serializers.UUIDField(required=False, allow_null=True)
    due_date = serializers.DateField(required=False, allow_null=True)
    source_report_id = serializers.UUIDField(required=False, allow_null=True)


class UpdateActionItemSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=500, required=False)
    owner_id = serializers.UUIDField(required=False, allow_null=True)
    due_date = serializers.DateField(required=False, allow_null=True)
    status = serializers.ChoiceField(
        choices=["open", "in_progress", "done", "cancelled"],
        required=False,
    )
    resolution_note = serializers.CharField(required=False, allow_blank=True)


class ReportSnapshotSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source="member.display_name")
    member_department = serializers.CharField(source="member.department.name", default="")

    class Meta:
        model = MeetingReportSnapshot
        fields = [
            "id",
            "member_id",
            "member_name",
            "member_department",
            "report_revision_id",
            "display_order",
        ]


class MeetingDetailSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.display_name", read_only=True)
    snapshots = serializers.SerializerMethodField()
    report_states = serializers.SerializerMethodField()
    action_items = ActionItemSerializer(many=True, read_only=True)

    class Meta:
        model = Meeting
        fields = [
            "id",
            "reporting_period_id",
            "status",
            "created_by_name",
            "member_order_json",
            "started_at",
            "ended_at",
            "notes",
            "snapshots",
            "report_states",
            "action_items",
            "created_at",
        ]

    def get_snapshots(self, obj):
        return ReportSnapshotSerializer(
            obj.report_snapshots.order_by("display_order").select_related(
                "member", "member__department", "report_revision"
            ),
            many=True,
        ).data

    def get_report_states(self, obj):
        states = MeetingReportState.objects.filter(meeting=obj).select_related("report")
        return {
            str(s.report_id): {
                "discussed": s.discussed,
                "discussed_at": s.discussed_at.isoformat() if s.discussed_at else None,
                "note": s.note,
            }
            for s in states
        }


class MeetingListSerializer(serializers.ModelSerializer):
    """组会列表（轻量）。"""

    created_by_name = serializers.CharField(source="created_by.display_name", read_only=True)
    snapshot_count = serializers.SerializerMethodField()

    class Meta:
        model = Meeting
        fields = [
            "id",
            "reporting_period_id",
            "status",
            "created_by_name",
            "started_at",
            "ended_at",
            "snapshot_count",
            "created_at",
        ]

    def get_snapshot_count(self, obj):
        return obj.report_snapshots.count()


class MarkDiscussedSerializer(serializers.Serializer):
    discussed = serializers.BooleanField(default=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class RefreshSnapshotSerializer(serializers.Serializer):
    """刷新为最新修订（需审计）。"""
    pass
