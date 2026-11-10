"""附件序列化器。"""

from rest_framework import serializers
from .models import (
    Attachment,
    AttachmentCompatibilityReport,
    AttachmentExtractedText,
)


class AttachmentStatusSerializer(serializers.ModelSerializer):
    """草稿附件列表及预览状态。"""

    preview_status = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = [
            "id",
            "original_filename",
            "uploaded_filename",
            "status",
            "detected_mime",
            "file_size_bytes",
            "preview_status",
            "retry_count",
            "updated_at",
        ]

    def get_preview_status(self, obj):
        if not obj.pdf_source:
            return None
        preview = obj.ready_preview
        if not preview:
            return {"available": True, "page_count": None, "converter_name": "原始 PDF", "converter_version": ""}
        return {
            "available": True,
            "page_count": preview.page_count,
            "converter_name": preview.converter_name,
            "converter_version": preview.converter_version,
        }


class AttachmentDetailSerializer(AttachmentStatusSerializer):
    """附件详情（含兼容性报告和预览状态）。"""

    compatibility_report = serializers.SerializerMethodField()
    extracted_summary = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = [
            "id",
            "original_filename",
            "uploaded_filename",
            "safe_filename",
            "detected_mime",
            "file_size_bytes",
            "source_sha256",
            "status",
            "retry_count",
            "uploaded_by_id",
            "created_at",
            "updated_at",
            "compatibility_report",
            "preview_status",
            "extracted_summary",
        ]

    def get_compatibility_report(self, obj):
        report = AttachmentCompatibilityReport.objects.filter(attachment=obj).first()
        if not report:
            return None
        return {
            "declared_fonts": report.declared_fonts,
            "missing_fonts": report.missing_or_substituted_fonts,
            "font_matches": report.font_matches,
            "macro_enabled": report.macro_enabled,
            "encrypted": report.encrypted,
            "legacy_format": report.legacy_format,
            "preview_level": report.preview_level,
            "warnings": report.warnings,
        }

    def get_extracted_summary(self, obj):
        extracted = AttachmentExtractedText.objects.filter(attachment=obj).first()
        if not extracted:
            return None
        return {
            "completeness": extracted.completeness,
            "char_count": len(extracted.content),
            "warnings": extracted.warnings,
        }


class ConfirmPreviewSerializer(serializers.Serializer):
    """成员确认预览。"""
    confirmed = serializers.BooleanField()  # True = 确认/通过, False = 拒绝


class BatchStatusSerializer(serializers.Serializer):
    """批量查询附件状态。"""
    attachment_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=50
    )
