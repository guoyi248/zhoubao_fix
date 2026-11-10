import json

import pytest
from django.core.management import call_command, CommandError

from .models import KnowledgeDocument, KnowledgeModule


pytestmark = pytest.mark.django_db


@pytest.fixture
def snapshot():
    return {
        "share_id": "7195675c-264a-49a7-819b-f5527f5a9443",
        "folders": [
            {"id": 12, "parent": 11, "name": "子目录", "order": 0},
            {"id": 11, "parent": None, "name": "文档", "order": 1},
        ],
        "documents": [{"id": 21, "parent": 12, "title": "计算", "markdown": "原文", "order": 0}],
    }


def load_snapshot(tmp_path, snapshot):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    call_command("import_apifox_knowledge", str(path))


def test_repeat_import_preserves_paths_ids_and_local_edits(tmp_path, snapshot):
    load_snapshot(tmp_path, snapshot)
    doc = KnowledgeDocument.objects.get(title="计算")
    assert doc.module.parent.name == "文档"
    assert doc.module.parent.parent.name == "Apifox 知识库"
    load_snapshot(tmp_path, snapshot)
    doc.refresh_from_db()
    assert doc.version == 1
    snapshot["documents"][0]["markdown"] = "来源更新"
    load_snapshot(tmp_path, snapshot)
    doc.refresh_from_db()
    assert doc.markdown == "来源更新" and doc.version == 2
    doc.markdown = "管理员修改"
    doc.save()
    snapshot["documents"][0]["markdown"] = "再次更新"
    load_snapshot(tmp_path, snapshot)
    doc.refresh_from_db()
    assert doc.markdown == "管理员修改"
    assert KnowledgeDocument.objects.filter(source_key__isnull=False).count() == 1


def test_broken_snapshot_rolls_back_and_existing_space_is_preserved(tmp_path, snapshot):
    snapshot["folders"][1]["parent"] = 12
    with pytest.raises(CommandError):
        load_snapshot(tmp_path, snapshot)
    assert not KnowledgeModule.objects.filter(source_key__isnull=False).exists()
    root = KnowledgeModule.objects.create(name="Apifox 知识库")
    snapshot["folders"][1]["parent"] = None
    with pytest.raises(CommandError):
        load_snapshot(tmp_path, snapshot)
    root.refresh_from_db()
    assert root.source_key is None


def test_local_and_remote_moves_cannot_form_a_cycle(tmp_path, snapshot):
    source_b, source_a = snapshot["folders"]
    source_b["parent"] = None
    load_snapshot(tmp_path, snapshot)
    a = KnowledgeModule.objects.get(name=source_a["name"])
    b = KnowledgeModule.objects.get(name=source_b["name"])
    root_id = a.parent_id
    original_hash = a.source_hash

    # A member of the admin team moved B below A using a local-only directory.
    local = KnowledgeModule.objects.create(name="本组补充", parent=a)
    b.parent = local
    b.save()
    source_a["parent"] = source_b["id"]
    snapshot["folders"].append({"id": 13, "parent": None, "name": "新增", "order": 2})
    with pytest.raises(CommandError, match="循环"):
        load_snapshot(tmp_path, snapshot)
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.parent_id == root_id and a.version == 1 and a.source_hash == original_hash
    assert b.parent_id == local.id
    assert not KnowledgeModule.objects.filter(name="新增").exists()

    local.parent_id = root_id
    local.save()
    load_snapshot(tmp_path, snapshot)
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.parent_id == b.id and a.version == 2
    assert b.parent_id == local.id
    assert KnowledgeModule.objects.filter(name="新增").count() == 1
