import hashlib
import json
import posixpath
import re
from io import BytesIO, StringIO
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlsplit
from uuid import uuid4
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from PIL import Image, UnidentifiedImageError
from django.conf import settings
from django.core.management import call_command, CommandError
from django.db import IntegrityError, transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from attachments.scanning import scan_stream
from common.storage import storage
from .history import require_admin
from .models import KnowledgeDocument, KnowledgeModule
from .views import KnowledgeAccess, directory_subtree


ASSET = re.compile(r"(?:https?://[^/\s)<>]+)?/api/v1/knowledge/assets/([a-f0-9]{64}\.(?:png|jpg|gif|webp))")
IMAGE = re.compile(r'(!\[[^\]\n]*\]\()(<[^>\n]+>|[^\s)]+)(\s+["\'][^\n]*?["\'])?\)')
FORMATS = {"PNG": ("png", "image/png"), "JPEG": ("jpg", "image/jpeg"), "GIF": ("gif", "image/gif"), "WEBP": ("webp", "image/webp")}


def picture(content):
    with Image.open(BytesIO(content)) as image:
        extension, mime = FORMATS[image.format]
        image.verify()
    digest = hashlib.sha256(content).hexdigest()
    return f"{digest}.{extension}", mime


@api_view(["POST"])
@parser_classes([MultiPartParser])
@permission_classes([KnowledgeAccess])
def upload_image(request):
    file = request.FILES.get("file")
    if not file or file.size > 10 * 1024 * 1024:
        return Response({"message": "请选择 10 MB 以内的 PNG、JPG、GIF 或 WebP 图片"}, status=400)
    content = file.read()
    try:
        filename, mime = picture(content)
    except (UnidentifiedImageError, OSError, KeyError, ValueError, SyntaxError, Image.DecompressionBombError):
        return Response({"message": "图片格式无效，请使用 PNG、JPG、GIF 或 WebP"}, status=400)
    if settings.CLAMAV_SCAN_UPLOADS:
        scan_stream(BytesIO(content))
    storage.client.put_object(Bucket=settings.S3_BUCKET_ORIGINALS, Key="knowledge/assets/" + filename, Body=content, ContentType=mime)
    return Response({"url": "/api/v1/knowledge/assets/" + filename}, status=201)


def safe_name(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:100] or "文档"


@api_view(["GET"])
@permission_classes([KnowledgeAccess])
def export_space(request, pk):
    root = get_object_or_404(KnowledgeModule, pk=pk)
    ids = directory_subtree(root.pk)
    modules = list(KnowledgeModule.objects.filter(pk__in=ids).order_by("position", "created_at"))
    by_id = {module.pk: module for module in modules}
    paths = {root.pk: safe_name(root.name)}

    def module_path(module):
        if module.pk not in paths:
            paths[module.pk] = module_path(by_id[module.parent_id]) + "/" + safe_name(module.name) + "-" + str(module.pk)[:8]
        return paths[module.pk]

    docs = list(KnowledgeDocument.objects.filter(module_id__in=ids, deleted_at__isnull=True).order_by("position", "created_at"))
    manifest = {"share_id": str(uuid4()), "space_name": root.name, "folders": [], "documents": [], "assets": []}
    for module in modules:
        if module.pk != root.pk:
            manifest["folders"].append({"id": str(module.pk), "parent": None if module.parent_id == root.pk else str(module.parent_id), "name": module.name, "order": module.position})
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        filenames = set()
        for doc in docs:
            path = module_path(by_id[doc.module_id]) + "/" + safe_name(doc.title) + "-" + str(doc.pk)[:8] + ".md"
            body = doc.markdown
            for match in ASSET.finditer(doc.markdown):
                filename = match[1]
                filenames.add(filename)
                body = body.replace(match[0], posixpath.relpath("assets/" + filename, posixpath.dirname(path)))
            archive.writestr(path, body)
            normalized_body = ASSET.sub(lambda match: "/api/v1/knowledge/assets/" + match[1], doc.markdown)
            manifest["documents"].append({"id": str(doc.pk), "parent": None if doc.module_id == root.pk else str(doc.module_id), "title": doc.title, "order": doc.position, "markdown": normalized_body})
        for filename in sorted(filenames):
            content = storage.download_to_bytes(settings.S3_BUCKET_ORIGINALS, "knowledge/assets/" + filename)
            archive.writestr("assets/" + filename, content)
            manifest["assets"].append({"path": "assets/" + filename, "source_url": "/api/v1/knowledge/assets/" + filename, "sha256": hashlib.sha256(content).hexdigest()})
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    output.seek(0)
    return FileResponse(output, as_attachment=True, filename=safe_name(root.name) + ".zip", content_type="application/zip")


def markdown_snapshot(files, name):
    manifest = {"space_name": name, "folders": [], "documents": [], "assets": []}
    directories = {"": None}
    images = {}

    def folder(path):
        if path not in directories:
            parent = folder(posixpath.dirname(path))
            directories[path] = str(uuid4())
            manifest["folders"].append({"id": directories[path], "parent": parent, "name": PurePosixPath(path).name[:64], "order": len(directories)})
        return directories[path]

    for path, content in files.items():
        if PurePosixPath(path).suffix.lower() not in {".md", ".markdown"}:
            continue
        body = content.decode("utf-8-sig")
        if not body.strip() or len(body) > 250_000 or "\0" in body:
            raise ValueError("Markdown 正文为空、包含无效字符或超过 25 万字符。")

        def local_image(match):
            url = match[2].strip("<>")
            if urlsplit(url).scheme or url.startswith(("//", "/api/v1/knowledge/assets/")):
                return match[0]
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), unquote(urlsplit(url).path)))
            if resolved.startswith(("../", "/")) or resolved not in files:
                raise ValueError("找不到 Markdown 引用的图片，请将图片一起放入 ZIP：" + url[:100])
            image = files[resolved]
            picture(image)
            if resolved not in images:
                source = "knowledge-import://" + str(uuid4())
                images[resolved] = source
                manifest["assets"].append({"path": resolved, "source_url": source, "sha256": hashlib.sha256(image).hexdigest()})
            return match[1] + images[resolved] + ")"

        body = IMAGE.sub(local_image, body)
        manifest["documents"].append({"id": str(uuid4()), "parent": folder(posixpath.dirname(path)), "title": PurePosixPath(path).stem[:160], "order": len(manifest["documents"]), "markdown": body})
    return manifest


@api_view(["POST"])
@parser_classes([MultiPartParser])
@permission_classes([KnowledgeAccess])
def import_archive(request):
    require_admin(request.user)
    file = request.FILES.get("file")
    if not file or file.size > 30 * 1024 * 1024:
        return Response({"message": "请选择 30 MB 以内的 Markdown 图片 ZIP 包"}, status=400)
    content = file.read()
    if settings.CLAMAV_SCAN_UPLOADS:
        scan_stream(BytesIO(content))
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 2000 or sum(item.file_size for item in entries) > 100 * 1024 * 1024:
                raise ValueError("解压内容超过 100 MB 或文件数量超过 2000，请分批导入。")
            files = {}
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in entry.filename or "\0" in entry.filename:
                    raise ValueError("压缩包包含不安全的文件路径。")
                if not entry.is_dir():
                    if path.as_posix() in files:
                        raise ValueError("压缩包存在重复的文件路径。")
                    files[path.as_posix()] = archive.read(entry)
        data = json.loads(files["manifest.json"].decode("utf-8-sig")) if "manifest.json" in files else markdown_snapshot(files, Path(file.name).stem)
        if not data.get("documents") or len(data["documents"]) > 1000:
            raise ValueError("未找到文档，或文档超过 1000 篇。")
        data["share_id"] = str(uuid4())
        name = str(data.get("space_name") or Path(file.name).stem).strip()[:64] or "导入知识库"
        parent_id = request.data.get("module") or None
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            for path, body in files.items():
                destination = directory / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(body)
            manifest_path = directory / "manifest.json"
            manifest_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with transaction.atomic():
                parent = get_object_or_404(KnowledgeModule.objects.select_for_update(), pk=parent_id) if parent_id else None
                final_name = name
                index = 2
                while KnowledgeModule.objects.filter(parent=parent, name=final_name).exists():
                    final_name = name[:52] + f"（导入 {index}）"
                    index += 1
                temporary_name = "导入-" + data["share_id"]
                call_command("import_apifox_knowledge", str(manifest_path), space=temporary_name, stdout=StringIO())
                root = KnowledgeModule.objects.get(source_key="apifox:" + data["share_id"] + ":root")
                root.parent, root.name = parent, final_name
                root.save(update_fields=["parent", "name", "updated_at"])
        return Response({"module": root.pk, "name": root.name, "documents": len(data["documents"]), "images": len(data.get("assets", []))}, status=201)
    except (BadZipFile, CommandError, ValueError, UnicodeError, KeyError, TypeError, OSError, SyntaxError, IntegrityError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        return Response({"message": "导入失败：" + str(exc)[:240]}, status=400)
