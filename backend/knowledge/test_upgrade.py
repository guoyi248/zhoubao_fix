import hashlib
from io import BytesIO
from zipfile import ZipFile

import pytest
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from accounts.models import User
from common.storage import LocalStorage
from .models import KnowledgeDocument, KnowledgeModule, KnowledgeRevision


pytestmark = pytest.mark.django_db
BASE = "/api/v1/knowledge/"


@pytest.fixture
def files(tmp_path, monkeypatch):
    monkeypatch.setattr("common.storage.LOCAL_ROOT", tmp_path)
    local = LocalStorage()
    for module in ("knowledge.views", "knowledge.transfer", "knowledge.management.commands.import_apifox_knowledge"):
        monkeypatch.setattr(module + ".storage", local)
    return tmp_path


@pytest.fixture
def admin():
    client = Client()
    client.force_login(User.objects.create_user("upgrade-admin", display_name="知识管理员", role="admin", account_status="active"))
    return client


def json_call(client, method, path, data):
    return getattr(client, method)(BASE + path, data, content_type="application/json")


def archive(files):
    content = BytesIO()
    with ZipFile(content, "w") as bundle:
        for name, body in files.items():
            bundle.writestr(name, body)
    return SimpleUploadedFile("实验笔记.zip", content.getvalue(), content_type="application/zip")


def png():
    content = BytesIO()
    Image.new("RGB", (20, 20), "green").save(content, "PNG")
    return content.getvalue()


def test_history_restore_keeps_newer_versions_and_checks_conflicts(admin):
    folder = KnowledgeModule.objects.create(name="版本测试")
    payload = {"module": str(folder.pk), "title": "实验步骤", "markdown": "第一版"}
    created = json_call(admin, "post", "documents", payload).json()
    path = "documents/" + created["id"]
    assert json_call(admin, "put", path, {**payload, "markdown": "第二版", "version": 1}).status_code == 200
    history = admin.get(BASE + path + "/history").json()
    assert [row["version"] for row in history] == [2, 1]
    restore = path + "/history/" + history[1]["id"]
    assert json_call(admin, "post", restore, {"version": 1}).status_code == 409
    assert json_call(admin, "post", restore, {"version": 2}).json()["version"] == 3
    assert admin.get(BASE + path).json()["markdown"] == "第一版"
    assert list(KnowledgeRevision.objects.filter(document_id=created["id"]).values_list("version", flat=True)) == [3, 2, 1]


def test_trash_hides_document_and_restores_after_original_folder_removed(admin):
    folder = KnowledgeModule.objects.create(name="即将删除的目录")
    target = KnowledgeModule.objects.create(name="恢复目录")
    doc = KnowledgeDocument.objects.create(module=folder, title="回收站专用词", markdown="原始内容")
    path = "documents/" + str(doc.pk)
    assert json_call(admin, "delete", path, {"version": 1}).status_code == 204
    assert admin.get(BASE + path).status_code == 404
    assert admin.get(BASE + "search", {"q": doc.title}).json()["results"] == []
    assert not any(entry["id"] == str(doc.pk) for module in admin.get(BASE).json() for entry in module["documents"])
    assert json_call(admin, "delete", "modules/" + str(folder.pk), {"version": 1}).status_code == 204
    trashed = next(row for row in admin.get(BASE + "trash").json() if row["id"] == str(doc.pk))
    assert trashed["module"] is None
    assert json_call(admin, "post", "trash/" + str(doc.pk) + "/restore", {"version": trashed["version"], "module": str(target.pk)}).status_code == 200
    doc.refresh_from_db()
    assert doc.deleted_at is None and doc.markdown == "原始内容" and doc.module == target


def test_image_upload_zip_export_and_import_preserve_images(admin, files):
    image = png()
    upload = admin.post(BASE + "assets", {"file": SimpleUploadedFile("结果.png", image, content_type="image/png")})
    assert upload.status_code == 201
    url = upload.json()["url"]
    folder = KnowledgeModule.objects.create(name="可迁移知识库")
    child = KnowledgeModule.objects.create(name="实验记录", parent=folder)
    KnowledgeDocument.objects.create(module=child, title="原始图表", markdown="## 图表\n\n![实验结果](" + url + ")")
    response = admin.get(BASE + "modules/" + str(folder.pk) + "/export")
    assert response.status_code == 200
    exported = b"".join(response.streaming_content)
    with ZipFile(BytesIO(exported)) as bundle:
        md = next(name for name in bundle.namelist() if name.endswith(".md"))
        assert "../" in bundle.read(md).decode()
        assert bundle.read("assets/" + url.rsplit("/", 1)[1]) == image
    result = admin.post(BASE + "import", {"file": SimpleUploadedFile("export.zip", exported)} )
    assert result.status_code == 201, result.content
    assert result.json()["documents"] == 1 and result.json()["images"] == 1
    imported = KnowledgeModule.objects.get(pk=result.json()["module"])
    assert imported.name == "可迁移知识库（导入 2）"
    doc = KnowledgeDocument.objects.get(module__parent=imported)
    assert doc.title == "原始图表" and url in doc.markdown


def test_generic_markdown_zip_handles_nested_images_and_unicode(admin, files):
    image = png()
    result = admin.post(BASE + "import", {"file": archive({"基础/入门.md": "## 入门\n\n![图](../图片/结果.png)", "图片/结果.png": image})})
    assert result.status_code == 201, result.content
    root = KnowledgeModule.objects.get(pk=result.json()["module"])
    doc = KnowledgeDocument.objects.get(module__parent=root)
    assert doc.module.name == "基础" and doc.title == "入门"
    digest = hashlib.sha256(image).hexdigest()
    assert f"/api/v1/knowledge/assets/{digest}.png" in doc.markdown


@pytest.mark.parametrize("content", [
    {"../escape.md": "不能越界"},
    {"文档.md": "![缺图](missing.png)"},
    {"文档.md": "![伪造](fake.png)", "fake.png": b"not an image"},
    {"文档.md": b"\xff\xff"},
])
def test_invalid_archive_has_no_partial_database_changes(admin, files, content):
    before = KnowledgeModule.objects.count(), KnowledgeDocument.objects.count()
    assert admin.post(BASE + "import", {"file": archive(content)}).status_code == 400
    assert before == (KnowledgeModule.objects.count(), KnowledgeDocument.objects.count())


def test_member_cannot_upload_import_read_trash_or_history(admin, files):
    folder = KnowledgeModule.objects.create(name="权限测试")
    doc = KnowledgeDocument.objects.create(module=folder, title="权限文档", markdown="内容")
    member = Client()
    member.force_login(User.objects.create_user("upgrade-reader", account_status="active"))
    assert member.get(BASE + "trash").status_code == 403
    assert member.get(BASE + f"documents/{doc.pk}/history").status_code == 403
    assert member.post(BASE + "assets", {"file": SimpleUploadedFile("图.png", png())}).status_code == 403
    assert member.post(BASE + "import", {"file": archive({"a.md": "内容"})}).status_code == 403
    response = Client().get(BASE + f"modules/{folder.pk}/export")
    assert response.status_code in (401, 403)


def test_search_explicit_pagination_and_scope(admin):
    folder = KnowledgeModule.objects.create(name="分页空间")
    other = KnowledgeModule.objects.create(name="另一个空间")
    KnowledgeDocument.objects.bulk_create([KnowledgeDocument(module=folder, title=f"分页词 {i}", markdown="内容") for i in range(27)])
    KnowledgeDocument.objects.create(module=other, title="分页词 外部", markdown="内容")
    first = admin.get(BASE + "search", {"q": "分页词", "scope": folder.pk, "page": 1}).json()
    second = admin.get(BASE + "search", {"q": "分页词", "scope": folder.pk, "page": 2}).json()
    assert first["total"] == 27 and len(first["results"]) == 25 and len(second["results"]) == 2
    assert {row["id"] for row in first["results"]}.isdisjoint(row["id"] for row in second["results"])


def test_corrupt_png_is_rejected_as_a_validation_error(admin, files):
    image = bytearray(png())
    image[29] ^= 1
    response = admin.post(BASE + "assets", {"file": SimpleUploadedFile("损坏.png", bytes(image), content_type="image/png")})
    assert response.status_code == 400
