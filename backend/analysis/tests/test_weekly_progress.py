from unittest.mock import patch

import fitz
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import User
from analysis.models import AnalysisRun
from analysis.tasks import analyze_report, dispatch_pending, queue_revision
from reporting.models import WeeklyReport
from reporting.periods import current_period

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("local_files")]


def pdf(text=""):
    with fitz.open() as doc:
        page = doc.new_page()
        if text:
            page.insert_text((25, 40), text)
        return doc.tobytes()


@pytest.mark.parametrize("provider", ["openai_compatible", "ollama"])
def test_submission_uses_all_frozen_files_and_corrected_version(client, settings, model_service, provider):
    base, calls = model_service
    settings.LLM_ENABLED = True
    settings.LLM_PROVIDER = provider
    settings.LLM_MODEL = "local-test"
    settings.LLM_API_KEY = "" if provider == "ollama" else "synthetic-test-key"
    settings.LLM_BASE_URL = base if provider == "ollama" else base + "/v1"
    settings.LLM_MAX_RETRIES = 0
    member = User.objects.create_user("sample", display_name="测试", account_status="active")
    client.force_login(member)
    current = client.get("/api/v1/me/reports/current").json()
    root = "/api/v1/me/reports/" + current["id"]
    for name, content in [("acceptance.pdf", pdf("accepted M17")), ("results.txt", "第二阶段交付".encode())]:
        assert client.post(root + "/attachments", {"file": SimpleUploadedFile(name, content)}).status_code == 201
    assert not AnalysisRun.objects.exists() and not calls
    first = client.post(root + "/submit", {}, content_type="application/json")
    assert first.status_code == 201
    revision_id = first.json()["revision_id"]
    path = "/api/v1/reports/" + revision_id + "/analysis"
    assert client.get(path).json()["status"] == "queued"
    dispatch_pending()
    result = client.get(path).json()
    assert result["summary"] == "已完成验收。" and result["items"][0]["title"] == "完成验收"
    assert result["tokens_used"] == (5 if provider == "ollama" else 8)
    endpoint, payload, auth = calls[0]
    assert endpoint == ("/api/chat" if provider == "ollama" else "/v1/chat/completions")
    assert auth == (None if provider == "ollama" else "Bearer synthetic-test-key")
    prompt = payload["messages"][1]["content"]
    assert "accepted M17" in prompt and "第二阶段交付" in prompt
    if provider == "ollama":
        assert payload["stream"] is False and payload["format"]["type"] == "object"
    analyze_report(revision_id)
    assert len(calls) == 1
    second = client.post(root + "/correct", {"file": SimpleUploadedFile("fixed.pdf", pdf("revised N42"))})
    assert second.status_code == 201
    dispatch_pending()
    next_prompt = calls[-1][1]["messages"][1]["content"]
    assert "revised N42" in next_prompt and "accepted M17" not in next_prompt and "第二阶段交付" not in next_prompt
    assert AnalysisRun.objects.filter(status="completed").count() == 2
    assert client.get(path).json()["id"] == result["id"]

    assert client.get("/api/v1/admin/reports/overview").status_code == 403
    admin = User.objects.create_user("facilitator", role="admin", display_name="主持", account_status="active")
    client.force_login(admin)
    overview = client.get("/api/v1/admin/reports/overview").json()
    assert [(r["owner_name"], r["progress_summary"]) for r in overview["submitted"]] == [("测试", "已完成验收。")]
    assert overview["submitted"][0]["current_revision_id"] == second.json()["revision_id"]


def test_model_configuration_is_visible_without_exposing_credentials(client, settings):
    settings.LLM_ENABLED = True
    settings.LLM_PROVIDER = "ollama"
    settings.LLM_BASE_URL = ""
    settings.LLM_MODEL = ""
    settings.LLM_API_KEY = "never-return-model-key"
    chair = User.objects.create_user("chair", role="admin", account_status="active")
    report = WeeklyReport.objects.create(owner=chair, reporting_period=current_period(), draft_content_json={"completed":["ok"]})
    revision = report.submit(chair)
    endpoint = "/api/v1/reports/analysis-service"
    client.force_login(chair)
    response = client.get(endpoint)
    assert b"never-return-model-key" not in response.content
    assert not response.json()["configured"]
    assert response.json()["setup"]["issues"] == ["LLM_BASE_URL", "LLM_MODEL"]
    analysis = f"/api/v1/reports/{revision.pk}/analysis"
    assert client.get(analysis).json()["status"] == "unconfigured"
    assert client.post(analysis + "/regenerate").status_code == 409
    settings.LLM_BASE_URL = "http://127.0.0.1:11434"
    settings.LLM_MODEL = "local-example"
    assert client.get(endpoint).json()["configured"]
    client.force_login(User.objects.create_user("participant", account_status="active"))
    assert client.get(endpoint).json() == {"enabled": True, "configured": True}


def test_scan_without_text_fails_without_calling_model(client, settings):
    settings.LLM_ENABLED = True
    member = User.objects.create_user("scan", display_name="扫码", account_status="active")
    client.force_login(member)
    root = "/api/v1/me/reports/" + client.get("/api/v1/me/reports/current").json()["id"]
    client.post(root + "/attachments", {"file": SimpleUploadedFile("scan.pdf", pdf())})
    response = client.post(root + "/submit", {}, content_type="application/json")
    revision_id = response.json()["revision_id"]
    with patch("analysis.tasks.llm_client.analyze_report") as model:
        dispatch_pending()
        model.assert_not_called()
    result = client.get(f"/api/v1/reports/{revision_id}/analysis").json()
    assert result["status"] == "failed" and "文字" in result["error_message"]


def test_older_submissions_can_be_queued_once_after_enabling(settings):
    user = User.objects.create_user("legacy")
    report = WeeklyReport.objects.create(owner=user, reporting_period=current_period())
    revision = report.submit(user)
    assert not AnalysisRun.objects.exists()
    settings.LLM_ENABLED = True
    assert queue_revision(revision, force=True).pk == queue_revision(revision, force=True).pk
