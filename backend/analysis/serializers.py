"""AI 分析序列化器。"""

from rest_framework import serializers
from .models import AnalysisRun, AnalysisItem, AnalysisItemSource, AnalysisHumanRevision


class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalysisItemSource
        fields = ["id", "source_type", "source_id", "page", "quote_hash"]


class AnalysisItemSerializer(serializers.ModelSerializer):
    sources = SourceSerializer(many=True, read_only=True)

    class Meta:
        model = AnalysisItem
        fields = [
            "id",
            "item_type",
            "title",
            "detail",
            "project",
            "confidence",
            "human_status",
            "human_revision_comment",
            "sources",
            "created_at",
        ]


class AnalysisRunSerializer(serializers.ModelSerializer):
    items = AnalysisItemSerializer(many=True, read_only=True)

    class Meta:
        model = AnalysisRun
        fields = [
            "id",
            "model_name",
            "prompt_version",
            "schema_version",
            "status",
            "tokens_used",
            "generated_at",
            "items",
        ]


class UpdateAnalysisItemSerializer(serializers.Serializer):
    """人工修订分析条目。"""

    title = serializers.CharField(max_length=500, required=False)
    detail = serializers.CharField(required=False, allow_blank=True)
    project = serializers.CharField(max_length=300, required=False, allow_blank=True, allow_null=True)
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class RegenerateAnalysisSerializer(serializers.Serializer):
    """重新生成分析。"""

    pass  # 无需参数，直接基于当前修订重跑
