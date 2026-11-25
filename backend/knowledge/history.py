from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from common.exceptions import PermissionDeniedError
from .models import KnowledgeDocument, KnowledgeModule, KnowledgeRevision, remember_document
from .views import KnowledgeAccess, VersionInput, conflict, document_info


def require_admin(user):
    if not user.is_admin:
        raise PermissionDeniedError()


@api_view(["GET"])
@permission_classes([KnowledgeAccess])
def document_history(request, pk):
    require_admin(request.user)
    doc = get_object_or_404(KnowledgeDocument, pk=pk, deleted_at__isnull=True)
    return Response([{"id": r.pk, "version": r.version, "title": r.title, "created_at": r.created_at,
                      "editor": r.editor.display_name if r.editor else "已有文档"}
                     for r in doc.history.select_related("editor")])


@api_view(["GET", "POST"])
@permission_classes([KnowledgeAccess])
def history_revision(request, pk, revision_id):
    require_admin(request.user)
    revision = get_object_or_404(KnowledgeRevision, pk=revision_id, document_id=pk, document__deleted_at__isnull=True)
    if request.method == "GET":
        return Response({"title": revision.title, "markdown": revision.markdown, "version": revision.version})
    form = VersionInput(data=request.data)
    form.is_valid(raise_exception=True)
    try:
        with transaction.atomic():
            doc = get_object_or_404(KnowledgeDocument.objects.select_for_update(), pk=pk, deleted_at__isnull=True)
            if doc.version != form.validated_data["version"]:
                return conflict("文档已被更新，请重新打开历史版本。")
            remember_document(doc)
            doc.title, doc.markdown = revision.title, revision.markdown
            doc.version += 1
            doc.save(update_fields=["title", "markdown", "version", "updated_at"])
            remember_document(doc, request.user)
    except IntegrityError:
        return conflict("同目录已有同名文档，请先调整名称。")
    return Response(document_info(doc))


@api_view(["GET"])
@permission_classes([KnowledgeAccess])
def trash(request):
    require_admin(request.user)
    return Response([{**document_info(doc), "deleted_at": doc.deleted_at, "deleted_from": doc.deleted_from}
                     for doc in KnowledgeDocument.objects.filter(deleted_at__isnull=False).defer("markdown").order_by("-deleted_at")])


class RestoreInput(VersionInput):
    module = serializers.PrimaryKeyRelatedField(queryset=KnowledgeModule.objects.all(), pk_field=serializers.UUIDField())


@api_view(["POST"])
@permission_classes([KnowledgeAccess])
def restore_document(request, pk):
    require_admin(request.user)
    form = RestoreInput(data=request.data)
    form.is_valid(raise_exception=True)
    try:
        with transaction.atomic():
            doc = get_object_or_404(KnowledgeDocument.objects.select_for_update(), pk=pk, deleted_at__isnull=False)
            if doc.version != form.validated_data["version"]:
                return conflict("文档已被恢复或变更，请刷新回收站。")
            doc.module = form.validated_data["module"]
            doc.deleted_at = None
            doc.version += 1
            doc.save(update_fields=["module", "deleted_at", "version", "updated_at"])
            remember_document(doc, request.user)
    except IntegrityError:
        return conflict("目标目录已有同名文档，请选择其他目录。")
    return Response(document_info(doc))
