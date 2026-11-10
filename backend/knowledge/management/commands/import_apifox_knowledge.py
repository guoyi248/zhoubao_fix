"""Load an offline snapshot of an Apifox shared knowledge base."""

import hashlib
import json
from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from PIL import Image

from common.storage import storage
from knowledge.models import KnowledgeDocument, KnowledgeModule


def fingerprint(fields):
    data = json.dumps(fields, ensure_ascii=False, default=str, sort_keys=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def save_node(model, key, fields, counts):
    incoming = fingerprint(fields)
    obj = model.objects.select_for_update(no_key=True).filter(source_key=key).first()
    if obj is None:
        obj = model.objects.create(pk=uuid5(NAMESPACE_URL, key), source_key=key,
                                   source_hash=incoming, **fields)
        counts["新增"] += 1
    else:
        current = fingerprint({field: getattr(obj, field) for field in fields})
        if current != obj.source_hash and current != incoming:
            counts["保留本地编辑"] += 1
        elif current != incoming or obj.source_hash != incoming:
            for field, value in fields.items():
                setattr(obj, field, value)
            obj.source_hash = incoming
            obj.version += 1
            obj.save()
            counts["更新"] += 1
        else:
            counts["相同"] += 1
    return obj


def get_name(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise CommandError(f"文档或目录名称为空或超过 {limit} 字。")
    return value


def source_index(items):
    result = {}
    for item in items:
        key = str(item["id"]).strip() if item["id"] is not None else ""
        if not key or key in result:
            raise CommandError(f"快照中的条目标识为空或重复：{key}")
        result[key] = item
    return result


def validate_merged_tree(imported_ids):
    # A preserved local move can point through directories outside the snapshot.
    parents = dict(KnowledgeModule.objects.order_by().values_list("pk", "parent_id"))
    checked = {None}
    for directory_id in imported_ids:
        path = set()
        while directory_id not in checked:
            if directory_id in path:
                name = KnowledgeModule.objects.values_list("name", flat=True).get(pk=directory_id)
                raise CommandError(f"本地与来源的目录移动形成循环，涉及“{name}”。请调整目录后重新导入。")
            path.add(directory_id)
            directory_id = parents[directory_id]
        checked.update(path)


def import_images(manifest, assets):
    directory = manifest.resolve().parent
    replacements = {}
    formats = {"PNG": ("png", "image/png"), "JPEG": ("jpg", "image/jpeg"),
               "WEBP": ("webp", "image/webp"), "GIF": ("gif", "image/gif")}
    for item in assets:
        path = (directory / item["path"]).resolve()
        if not path.is_relative_to(directory):
            raise CommandError("图片文件必须位于快照目录中。")
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != item["sha256"]:
            raise CommandError(f"图片校验失败：{path.name}")
        with Image.open(BytesIO(content)) as image:
            suffix, mime = formats[image.format]
            image.verify()
        filename = f"{digest}.{suffix}"
        bucket, key = settings.S3_BUCKET_ORIGINALS, f"knowledge/assets/{filename}"
        if not storage.object_exists(bucket, key):
            storage.client.put_object(Bucket=bucket, Key=key, Body=content, ContentType=mime)
        replacements[item["source_url"]] = f"/api/v1/knowledge/assets/{filename}"
    return replacements


class Command(BaseCommand):
    help = "从离线 JSON 快照导入 Apifox 分享的目录与 Markdown。再次执行会保留本地编辑。"

    def add_arguments(self, parser):
        parser.add_argument("manifest", type=Path)
        parser.add_argument("--space", default="Apifox 知识库")

    def handle(self, manifest, space, **options):
        try:
            manifest = Path(manifest)
            data = json.loads(manifest.read_text(encoding="utf-8-sig"))
            if data.get("unavailable_assets"):
                raise CommandError("快照中有未下载的图片，请补齐图片后重新导入。")
            share = str(UUID(data["share_id"]))
            prefix = f"apifox:{share}:"
            folders = source_index(data["folders"])
            documents = source_index(data["documents"])
            children = defaultdict(list)
            for identifier, folder in folders.items():
                parent = folder["parent"]
                children[str(parent) if parent is not None else None].append(identifier)
            counts = Counter()
            with transaction.atomic():
                # Match the lock order used by interactive moves before changing any parents.
                list(KnowledgeModule.objects.select_for_update(no_key=True).order_by("pk").values_list("pk", flat=True))
                root = save_node(KnowledgeModule, prefix + "root", {
                    "name": get_name(space, 64), "parent_id": None, "position": 0,
                }, counts)
                parents = {None: root.pk}
                pending = [None]
                while pending:
                    parent = pending.pop()
                    for ident in children[parent]:
                        item = folders[ident]
                        module = save_node(KnowledgeModule, prefix + "folder:" + ident, {
                            "name": get_name(item["name"], 64), "parent_id": parents[parent],
                            "position": int(item["order"]),
                        }, counts)
                        parents[ident] = module.pk
                        pending.append(ident)
                if len(parents) != len(folders) + 1:
                    raise CommandError("快照中存在循环目录或缺少上级目录。")
                validate_merged_tree(parents.values())
                images = import_images(manifest, data.get("assets", []))
                for ident, item in documents.items():
                    parent = item["parent"]
                    body = item["markdown"]
                    if not isinstance(body, str) or len(body) > 250_000:
                        raise CommandError(f"文档 {ident} 的正文不是字符串或超过编辑器长度限制。")
                    for source_url, local_url in images.items():
                        body = body.replace(f"]({source_url})", f"]({local_url})")
                    save_node(KnowledgeDocument, prefix + "doc:" + ident, {
                        "module_id": parents[str(parent) if parent is not None else None],
                        "title": get_name(item["title"], 160), "markdown": body,
                        "position": int(item["order"]),
                    }, counts)
        except (OSError, ValueError, TypeError, KeyError, IntegrityError) as exc:
            raise CommandError(f"导入失败，请检查源文件和同名条目。{exc}") from exc
        self.stdout.write(f"{root.name}  {len(folders)} 个目录，{len(documents)} 篇文档，{len(images)} 幅图片。"
                          + "，".join(f"{k} {v}" for k, v in counts.items()))
