from unittest.mock import patch

import pytest
from django.core import mail
from freezegun import freeze_time

from accounts.models import User
from analysis.models import AnalysisRun
from analysis.tasks import dispatch_pending
from audit.models import AuditEvent
from reporting.models import WeeklyReport
from reporting.periods import current_period
from reporting.tasks import send_weekly_reminders
from system_config.integrations import get_config
from system_config.models import SystemSetting

pytestmark = pytest.mark.django_db
URL = "/api/v1/admin/config/integrations"


def user(name, role="member"):
    return User.objects.create_user(name, role=role, account_status="active", display_name=name, email=name+"@example.test")


def patch_config(client, section, version, **values):
    return client.patch(URL, {"section": section, "version": version, "values": values}, content_type="application/json")


def test_only_admin_can_read_or_write_and_conflicts_are_atomic(client, settings):
    settings.LLM_API_KEY = "env-secret"
    assert client.get(URL).status_code in (401, 403)
    client.force_login(user("member"))
    assert client.get(URL).status_code == 403
    assert patch_config(client, "model", 0, base_url="https://other.test").status_code == 403
    client.force_login(user("admin", "admin"))
    assert b"env-secret" not in client.get(URL).content
    first = patch_config(client, "model", 0, model="first")
    assert first.status_code == 200 and first.json()["source"] == "database"
    assert patch_config(client, "model", 0, model="stale").status_code == 409
    assert patch_config(client, "model", 1, base_url="https://legit.test/path?key=secret").status_code == 400
    assert patch_config(client, "model", 1, made_up=True).status_code == 400
    assert get_config("model")["model"] == "first"
    assert AuditEvent.objects.filter(event_type="SYSTEM_SETTING_CHANGED").count() == 1
    assert client.patch(URL, {"section":"model", "version":1, "reset":True}, content_type="application/json").json()["source"] == "environment"


def test_worker_uses_selected_provider_and_never_forwards_previous_credential(client, settings):
    settings.SECRET_KEY = "independent-test-server-secret"
    settings.LLM_ENABLED = False
    settings.LLM_BASE_URL = "https://original.example.test/v1"
    settings.LLM_API_KEY = "original-secret"
    settings.LLM_PROVIDER = "openai_compatible"
    chair = user("chair", "admin")
    client.force_login(chair)
    result = patch_config(client, "model", 0, enabled=True, model="test-online", api_key="new-write-only")
    assert result.status_code == 200 and result.json()["has_secret"]
    assert b"new-write-only" not in result.content
    assert "new-write-only" not in str(SystemSetting.objects.get(key="integrations.model").value)
    assert b"integrations.model" not in client.get("/api/v1/admin/config/").content
    revision = WeeklyReport.objects.create(owner=chair, reporting_period=current_period(),
                                          draft_content_json={"completed":["定位问题"]}).submit(chair)
    assert AnalysisRun.objects.get(revision=revision).status == "queued"
    with patch("analysis.llm_client.requests.post") as post:
        post.return_value.json.return_value = {"choices":[{"message":{"content":'{"summary":"已修复"}'}}]}
        dispatch_pending()
        assert post.call_args.args == ("https://original.example.test/v1/chat/completions",)
        assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer new-write-only"
    switch = patch_config(client, "model", 1, provider="ollama", base_url="http://ollama:11434", model="test-local")
    assert switch.status_code == 200 and not switch.json()["has_secret"]
    analysis = f"/api/v1/reports/{revision.pk}/analysis"
    assert client.post(analysis+"/regenerate").status_code == 202
    with patch("analysis.llm_client.requests.post") as post:
        post.return_value.json.return_value = {"message":{"content":'{"summary":"本地模型的总结"}'}}
        dispatch_pending()
        assert post.call_args.args == ("http://ollama:11434/api/chat",)
        assert post.call_args.kwargs["headers"] == {}
    assert client.get(analysis).json()["summary"] == "本地模型的总结"
    assert get_config("model", credentials=True)["api_key"] == ""


@freeze_time("2026-11-06 10:00:00Z")
def test_mail_worker_reads_saved_schedule_and_delivery_credentials(client, settings):
    settings.SECRET_KEY = "independent-test-server-secret"
    settings.WEEKLY_REMINDERS_ENABLED = False
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    chair = user("chair", "admin")
    client.force_login(chair)
    saved = patch_config(client, "mail", 0, enabled=True, weekday=5, time="18:00", site_url="https://team.example.test",
                         host="smtp.example.test", port=587, use_tls=True, use_ssl=False, username="sender",
                         from_email="reports@example.test", password="private-smtp")
    assert saved.status_code == 200 and saved.json()["has_secret"] and b"private-smtp" not in saved.content
    assert "private-smtp" not in str(SystemSetting.objects.get(key="integrations.mail").value)
    assert send_weekly_reminders() == 1
    assert mail.outbox[0].from_email == "reports@example.test" and "https://team.example.test/" in mail.outbox[0].body
    assert send_weekly_reminders() == 0
    assert client.get("/api/v1/me/reports/reminders").json()["weekday"] == 5
    assert get_config("mail", credentials=True)["password"] == "private-smtp"
    assert patch_config(client, "mail", 1, host="other.test").status_code == 200
    assert not get_config("mail", credentials=True)["password"]
