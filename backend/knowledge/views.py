from collections import defaultdict
from sqlite3 import SQLITE_BUSY, SQLITE_LOCKED

from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Case, F, Prefetch, Q, Value, When
from django.db.models.deletion import ProtectedError
from django.db.models.functions import Greatest, Lower, StrIndex, Substr
from django.http import FileResponse, HttpResponseForbidden, HttpResponseNotFound, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_safe
from django.views.decorators.vary import vary_on_cookie
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.response import Response

from accounts.models import AccountStatus
from common.exceptions import ObjectNotFound
from common.storage import storage
from .models import KnowledgeDocument, KnowledgeModule


def can_read_knowledge(user):
    return user is not None and user.is_authenticated and user.is_active and user.account_status == AccountStatus.ACTIVE


class KnowledgeAccess(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return can_read_knowledge(user) and (request.method in SAFE_METHODS or user.is_admin)


class PositionedInput(serializers.Serializer):
    position = serializers.IntegerField(min_value=0, max_value=2_147_483_647, required=False)


class ModuleInput(PositionedInput):
    name = serializers.CharField(max_length=64)
    parent = serializers.PrimaryKeyRelatedField(queryset=KnowledgeModule.objects.all(), pk_field=serializers.UUIDField(),
                                                 allow_null=True, required=False)


class DocumentInput(PositionedInput):
    module = serializers.PrimaryKeyRelatedField(queryset=KnowledgeModule.objects.all(), pk_field=serializers.UUIDField())
    title = serializers.CharField(max_length=160)
    markdown = serializers.CharField(trim_whitespace=False, allow_blank=True, max_length=250_000)

    def validate_markdown(self, value):
        if value == "" and self.context.get("editing"):
            return value
        if not value.strip():
            raise serializers.ValidationError("请输入文档内容。")
        return value


class VersionInput(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)


class SearchInput(serializers.Serializer):
    q = serializers.CharField(max_length=160, required=False, allow_blank=True)
    scope = serializers.UUIDField(required=False)


def conflict(message):
    return Response({"code": "KNOWLEDGE_CONFLICT", "message": message}, status=409)


def module_info(module):
    return {"id": module.pk, "name": module.name, "version": module.version,
            "parent": module.parent_id, "position": module.position}


def document_info(doc):
    return {"id": doc.pk, "title": doc.title, "module": doc.module_id,
            "version": doc.version, "updated_at": doc.updated_at, "position": doc.position}


def can_move_directory(module_id, parent_id):
    # Serialize competing moves before following ancestors, including moves in other branches.
    parents = dict(KnowledgeModule.objects.select_for_update().order_by("pk").values_list("pk", "parent_id"))
    visited = {module_id}
    while parent_id is not None:
        if parent_id in visited or parent_id not in parents:
            return False
        visited.add(parent_id)
        parent_id = parents[parent_id]
    return True


def handle_write_contention(error):
    # SQLite can reject a read-to-write upgrade when parallel admins edit the tree.
    code = getattr(error.__cause__, "sqlite_errorcode", 0)
    if (code & 0xff) in (SQLITE_BUSY, SQLITE_LOCKED):
        return conflict("另一个操作正在更新知识库，请重试。")
    raise error


def save_content(request, model, form_class, identify, pk=None):
    form = form_class(data=request.data, context={"editing": pk is not None})
    form.is_valid(raise_exception=True)
    try:
        with transaction.atomic():
            if pk is None:
                obj = model.objects.create(**form.validated_data)
                return Response(identify(obj), status=201)
            revision = VersionInput(data=request.data)
            revision.is_valid(raise_exception=True)
            parent = form.validated_data.get("parent")
            if model is KnowledgeModule and parent and not can_move_directory(pk, parent.pk):
                return conflict("无法移动到自身、下级或已变更的目录。")
            current_revision = model.objects.filter(pk=pk, version=revision.validated_data["version"])
            keep_empty = form.validated_data.get("markdown") == ""
            # An imported title-only article may move, but an edit must never clear a filled article.
            target = current_revision.filter(markdown="") if keep_empty else current_revision
            count = target.update(
                **form.validated_data, version=F("version") + 1, updated_at=timezone.now())
            if not count:
                if keep_empty and current_revision.exists():
                    raise serializers.ValidationError({"markdown": ["不能清空已有正文。"]})
                return conflict("内容已变更或已删除。请保留草稿并重新载入。")
            return Response(identify(model.objects.get(pk=pk)))
    except IntegrityError:
        return conflict("同级名称重复或所属目录已变更，请刷新后再试。")
    except OperationalError as error:
        return handle_write_contention(error)


def remove_content(request, model, pk):
    revision = VersionInput(data=request.data)
    revision.is_valid(raise_exception=True)
    try:
        with transaction.atomic():
            obj = get_object_or_404(model.objects.select_for_update(), pk=pk)
            if obj.version != revision.validated_data["version"]:
                return conflict("内容已被更新，请重新载入后再删除。")
            obj.delete()
    except (ProtectedError, IntegrityError):
        return conflict("目录中还有子目录或文档，请先将它们移走或删除。")
    except OperationalError as error:
        return handle_write_contention(error)
    return Response(status=204)


@api_view(["GET", "POST"])
@permission_classes([KnowledgeAccess])
def library(request):
    if request.method == "POST":
        return save_content(request, KnowledgeModule, ModuleInput, module_info)
    modules = KnowledgeModule.objects.prefetch_related(Prefetch(
        "documents", queryset=KnowledgeDocument.objects.defer("markdown")))
    return Response([{
        **module_info(module), "documents": [document_info(doc) for doc in module.documents.all()],
    } for module in modules])


def directory_subtree(root_id):
    children = defaultdict(list)
    for directory_id, parent_id in KnowledgeModule.objects.values_list("id", "parent_id").order_by():
        children[parent_id].append(directory_id)
    descendants = set()
    remaining = [root_id]
    while remaining:
        directory_id = remaining.pop()
        if directory_id not in descendants:
            descendants.add(directory_id)
            remaining.extend(children[directory_id])
    return descendants


@api_view(["GET"])
@permission_classes([KnowledgeAccess])
def search_documents(request):
    form = SearchInput(data=request.query_params)
    form.is_valid(raise_exception=True)
    query = form.validated_data.get("q", "")
    if not query:
        return Response({"results": [], "has_more": False})
    docs = KnowledgeDocument.objects.filter(Q(title__icontains=query) | Q(markdown__icontains=query))
    scope = form.validated_data.get("scope")
    if scope is not None:
        get_object_or_404(KnowledgeModule, pk=scope)
        docs = docs.filter(module_id__in=directory_subtree(scope))
    match_offset = StrIndex(Lower("markdown"), Lower(Value(query)))
    results = list(docs.defer("markdown").annotate(
        excerpt=Substr("markdown", Greatest(Value(1), match_offset - 36), 180),
        rank=Case(When(title__iexact=query, then=0), When(title__icontains=query, then=1), default=2),
    ).order_by("rank", "position", "created_at", "id")[:51])
    return Response({
        "results": [{**document_info(doc), "excerpt": " ".join(doc.excerpt.split())} for doc in results[:50]],
        "has_more": len(results) > 50,
    })


@api_view(["PUT", "DELETE"])
@permission_classes([KnowledgeAccess])
def module_detail(request, pk):
    if request.method == "DELETE":
        return remove_content(request, KnowledgeModule, pk)
    return save_content(request, KnowledgeModule, ModuleInput, module_info, pk)


@api_view(["POST"])
@permission_classes([KnowledgeAccess])
def add_document(request):
    return save_content(request, KnowledgeDocument, DocumentInput, document_info)


@api_view(["GET", "PUT", "DELETE"])
@permission_classes([KnowledgeAccess])
def document_detail(request, pk):
    if request.method == "DELETE":
        return remove_content(request, KnowledgeDocument, pk)
    if request.method == "PUT":
        return save_content(request, KnowledgeDocument, DocumentInput, document_info, pk)
    doc = get_object_or_404(KnowledgeDocument, pk=pk)
    return Response({**document_info(doc), "markdown": doc.markdown})


@cache_control(private=True, no_store=True)
@vary_on_cookie
@require_safe
def knowledge_asset(request, digest, extension):
    if not can_read_knowledge(request.user):
        return HttpResponseForbidden()
    key = f"knowledge/assets/{digest}.{extension}"
    bucket = settings.S3_BUCKET_ORIGINALS
    media_type = "image/jpeg" if extension == "jpg" else f"image/{extension}"
    if request.method == "HEAD":
        if not storage.object_exists(bucket, key):
            return HttpResponseNotFound()
        # Leave the length unspecified when the storage adapter only checks existence.
        response = StreamingHttpResponse((), content_type=media_type)
    else:
        try:
            response = FileResponse(storage.generate_download_stream(bucket, key), content_type=media_type)
        except ObjectNotFound:
            return HttpResponseNotFound()
    response["X-Content-Type-Options"] = "nosniff"
    return response
