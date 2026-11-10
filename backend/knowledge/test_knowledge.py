from uuid import uuid4

import pytest
from django.test import Client

from accounts.models import AccountStatus, User, UserRole
from .models import KnowledgeDocument, KnowledgeModule

pytestmark = pytest.mark.django_db
base = "/api/v1/knowledge/"


def login(role):
    client = Client()
    user = User.objects.create_user(username=role, display_name="组内成员", role=role,
                                    account_status=AccountStatus.ACTIVE)
    client.force_login(user)
    return client


def test_private_library_and_read_only_member():
    member = login(UserRole.MEMBER)
    topics = member.get(base).json()
    assert len(topics) >= 3
    topic = next(group for group in topics if any(doc["title"] == "从上传到提交" for doc in group["documents"]))
    entry = next(doc for doc in topic["documents"] if doc["title"] == "从上传到提交")
    assert "markdown" not in entry
    module = base + "modules/" + topic["id"]
    doc = base + "documents/" + entry["id"]
    assert "##" in member.get(doc).json()["markdown"]
    assert Client().get(base).status_code in (401, 403)
    assert Client().get(doc).status_code in (401, 403)
    for method, path in [("post", base), ("put", module), ("delete", module), ("post", base+"documents"),
                         ("put", doc), ("delete", doc)]:
        assert getattr(member, method)(path, {}, content_type="application/json").status_code == 403


def test_admin_edits_versions_and_safe_module_deletion():
    admin = login(UserRole.ADMIN)
    def call(method, path, payload):
        return getattr(admin, method)(base + path, payload, content_type="application/json")
    first = call("post", "", {"name": "技术笔记"}).json()
    second = call("post", "", {"name": "待归档"}).json()
    assert call("post", "", {"name": "技术笔记"}).status_code == 409
    module_path = "modules/" + second["id"]
    assert call("put", module_path, {"name": "归档资料", "version":1}).json()["version"] == 2
    assert call("delete", module_path, {"version":1}).status_code == 409

    payload = {"module":first["id"], "title":"性能记录", "markdown":"## 样本\n\n- 第一批"}
    doc = call("post", "documents", payload)
    assert doc.status_code == 201
    ident = doc.json()["id"]
    path = "documents/" + ident
    assert call("post", "documents", {**payload, "markdown":"  "}).status_code == 400
    assert call("delete", "modules/" + first["id"], {"version":1}).status_code == 409
    edit = call("put", path, {**payload, "module":second["id"], "markdown":"新内容", "version":1})
    assert edit.status_code == 200 and edit.json()["version"] == 2
    assert call("put", path, {**payload, "version":1}).status_code == 409
    assert call("delete", path, {"version":1}).status_code == 409
    assert KnowledgeDocument.objects.get(pk=ident).markdown == "新内容"
    assert call("delete", path, {"version":2}).status_code == 204
    assert call("delete", module_path, {"version":2}).status_code == 204
    assert not KnowledgeModule.objects.filter(pk=second["id"]).exists()


def test_bootstrap_does_not_overwrite_existing_document():
    from importlib import import_module
    from django.apps import apps
    from django.db import connection
    from types import SimpleNamespace
    seed = import_module("knowledge.migrations.0002_starter_documents").seed_documents
    doc = KnowledgeDocument.objects.get(title="从上传到提交")
    doc.markdown = "管理员维护的内容"
    doc.save()
    count = KnowledgeDocument.objects.count()
    seed(apps, SimpleNamespace(connection=connection))
    doc.refresh_from_db()
    assert doc.markdown == "管理员维护的内容" and KnowledgeDocument.objects.count() == count


def test_existing_empty_article_can_move_and_receive_content():
    admin = login(UserRole.ADMIN)
    folder = KnowledgeModule.objects.create(name="空文档来源")
    other = KnowledgeModule.objects.create(name="待整理")
    doc = KnowledgeDocument.objects.create(module=folder, title="只有标题", markdown="")
    path = base + "documents/" + str(doc.pk)
    payload = {"module": str(other.pk), "title": "新标题", "markdown": "", "version": 1}
    for blank in ["", "  "]:
        assert admin.post(base + "documents", {**payload, "markdown": blank},
                          content_type="application/json").status_code == 400
    assert admin.put(path, {**payload, "markdown": "\n"}, content_type="application/json").status_code == 400
    assert admin.put(path, payload, content_type="application/json").status_code == 200
    assert admin.put(path, payload, content_type="application/json").status_code == 409
    doc.refresh_from_db()
    assert (doc.module_id, doc.title, doc.markdown, doc.version) == (other.pk, "新标题", "", 2)
    assert admin.put(path, {**payload, "markdown": "补上正文", "version": 2},
                     content_type="application/json").status_code == 200
    assert admin.put(path, {**payload, "version": 3}, content_type="application/json").status_code == 400
    assert admin.put(path, payload, content_type="application/json").status_code == 409
    doc.refresh_from_db()
    assert doc.markdown == "补上正文" and doc.version == 3


@pytest.mark.parametrize("status", [AccountStatus.INVITED, AccountStatus.PENDING, AccountStatus.DISABLED,
                                     AccountStatus.DELETED])
def test_inactive_account_cannot_read_library(status):
    user = User.objects.create_user(username="visitor", role=UserRole.ADMIN, account_status=status)
    client = Client()
    client.force_login(user)
    doc_id = KnowledgeDocument.objects.first().id
    for path in ["", "search?q=周报", f"documents/{doc_id}"]:
        assert client.get(base + path).status_code == 403
        assert Client().get(base + path).status_code in (401, 403)


def test_tree_moves_names_and_legacy_links():
    admin = login(UserRole.ADMIN)
    def create(name, parent=None, position=0):
        return admin.post(base, {"name": name, "parent": parent, "position": position}, content_type="application/json")
    root = create("研发空间").json()
    experiments = create("记录", root["id"], 20).json()
    other = create("观测", root["id"], 10).json()
    deep = create("第一期", experiments["id"]).json()
    assert create("记录", root["id"]).status_code == 409
    assert create("记录", other["id"]).status_code == 201
    assert create("空间外目录", "bad-id").status_code == 400
    assert create("空间外目录", str(uuid4())).status_code == 400

    root_path = base + "modules/" + root["id"]
    assert admin.delete(root_path, {"version": 1}, content_type="application/json").status_code == 409
    for invalid in [root, deep]:
        result = admin.put(root_path, {"name": root["name"], "parent": invalid["id"], "version": 1},
                           content_type="application/json")
        assert result.status_code == 409
    assert KnowledgeModule.objects.get(pk=root["id"]).version == 1

    deep_path = base + "modules/" + deep["id"]
    edit = admin.put(deep_path, {"name": "试验", "version": 1}, content_type="application/json")
    assert edit.json()["parent"] == experiments["id"]
    body = "# 实验记录\n\n| 项 | 值 |\n| --- | --- |\n| 样本 | 1 |\n"
    for title, position in [("追加内容", 9), ("记录原文", 1)]:
        result = admin.post(base + "documents", {"module": deep["id"], "title": title, "position": position,
                            "markdown": body}, content_type="application/json")
        assert result.status_code == 201
    document_path = base + "documents/" + result.json()["id"]
    edit = admin.put(deep_path, {"name": "试验", "parent": other["id"], "version": 2}, content_type="application/json")
    assert edit.json()["parent"] == other["id"]
    member = login(UserRole.MEMBER)
    tree = member.get(base).json()
    assert [m["id"] for m in tree if m["parent"] == root["id"]] == [other["id"], experiments["id"]]
    docs = next(m for m in tree if m["id"] == deep["id"])["documents"]
    assert [doc["title"] for doc in docs] == ["记录原文", "追加内容"]
    assert member.get(document_path).json()["markdown"] == body
    edit = admin.put(deep_path, {"name": "试验", "parent": None, "version": 3}, content_type="application/json")
    assert edit.status_code == 200 and edit.json()["parent"] is None


def test_search_title_body_and_directory_scope():
    member = login(UserRole.MEMBER)
    root = KnowledgeModule.objects.create(name="遥感空间")
    mid = KnowledgeModule.objects.create(name="算法", parent=root)
    leaf = KnowledgeModule.objects.create(name="样本", parent=mid)
    other = KnowledgeModule.objects.create(name="空间外")
    KnowledgeDocument.objects.create(module=other, title="GEESearch", markdown="只在别的空间")
    body_doc = KnowledgeDocument.objects.create(module=leaf, title="公式", markdown="前言 " * 200 + "geesearch 命中")
    title_doc = KnowledgeDocument.objects.create(module=root, title="关于 geesearch", markdown="说明\n\n两段")
    path = base + "search"
    result = member.get(path, {"q": " GEEsearch ", "scope": str(root.pk)}).json()
    assert not result["has_more"]
    assert [hit["id"] for hit in result["results"]] == [str(title_doc.pk), str(body_doc.pk)]
    assert "geesearch 命中" in result["results"][1]["excerpt"]
    assert all("markdown" not in hit for hit in result["results"])
    assert member.get(path, {"q": "geesearch"}).json()["results"][0]["title"] == "GEESearch"
    assert member.get(path, {"q": "  "}).json() == {"results": [], "has_more": False}
    assert member.get(path, {"q": "xx", "scope": str(uuid4())}).status_code == 404
    assert member.get(path, {"q": "xx", "scope": "invalid"}).status_code == 400
    KnowledgeDocument.objects.bulk_create([KnowledgeDocument(module=mid, title=f"检索{i}", markdown="中文关键词")
                                           for i in range(51)])
    truncated = member.get(path, {"q": "中文关键词", "scope": str(mid.pk)}).json()
    assert len(truncated["results"]) == 50 and truncated["has_more"]
