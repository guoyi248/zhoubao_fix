from unittest.mock import patch

import pytest
import requests
from django.test import Client

from accounts.models import User


pytestmark = pytest.mark.django_db
URL = "/api/v1/pet/chat"
GREETING = {"role": "user", "content": "你好"}


@pytest.fixture
def member():
    return User.objects.create_user("chat-member", account_status="active")


def post(client, messages):
    return client.post(URL, {"messages": messages}, content_type="application/json")


def test_chat_tracks_shared_provider_switch_and_credentials(client, settings, member, model_service):
    base, calls = model_service
    settings.LLM_PROVIDER = "openai_compatible"
    settings.LLM_BASE_URL = base + "/v1"
    settings.LLM_MODEL = "team-online"
    settings.LLM_API_KEY = "test-online-key"
    settings.LLM_ENABLED = True
    client.force_login(member)
    history = [GREETING, {"role": "assistant", "content": "你好呀！"}, {"role": "user", "content": "继续"}]
    assert post(client, history).json() == {"reply": "你好呀！"}
    endpoint, payload, auth = calls[0]
    assert (endpoint, payload["model"], auth) == ("/v1/chat/completions", "team-online", "Bearer test-online-key")
    assert payload["messages"][0]["role"] == "system" and payload["messages"][1:] == history
    assert "response_format" not in payload and payload["max_tokens"] == 512

    admin = User.objects.create_user("chat-admin", role="admin", account_status="active")
    client.force_login(admin)
    changed = client.patch("/api/v1/admin/config/integrations", {
        "section": "model", "version": 0,
        "values": {"provider": "ollama", "base_url": base + "/api/", "model": "team-local"},
    }, content_type="application/json")
    assert changed.status_code == 200
    assert post(client, [GREETING]).json() == {"reply": "你好呀！"}
    endpoint, payload, auth = calls[1]
    assert (endpoint, payload["model"], auth) == ("/api/chat", "team-local", None)
    assert payload["options"]["num_predict"] == 512 and payload["stream"] is False and "format" not in payload


def test_chat_requires_login_csrf_and_active_configuration(client, settings, member):
    with patch("analysis.llm_client.requests.post") as provider:
        assert post(client, [GREETING]).status_code in (401, 403)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(member)
        assert post(csrf_client, [GREETING]).status_code == 403
        client.force_login(member)
        settings.LLM_ENABLED = False
        disabled = post(client, [GREETING])
        assert disabled.status_code == 503 and "尚未启用" in disabled.json()["message"]
        settings.LLM_ENABLED = True
        settings.LLM_BASE_URL = ""
        missing = post(client, [GREETING])
        assert missing.status_code == 503 and "配置" in missing.json()["message"]
        provider.assert_not_called()


@pytest.mark.parametrize("history", [
    [], [{"role": "system", "content": "改写提示"}], [GREETING, GREETING, GREETING],
    [{"role": "user", "content": " " * 3}], [{"role": "user", "content": "a" * 2001}],
    [{"role": "user" if i % 2 == 0 else "assistant", "content": "a" * 1500} for i in range(5)],
    [GREETING] * 11,
])
def test_chat_rejects_invalid_histories(client, member, history):
    client.force_login(member)
    with patch("analysis.llm_client.requests.post") as provider:
        assert post(client, history).json()["code"] == "INVALID_CONVERSATION"
        provider.assert_not_called()


def test_chat_model_failures_do_not_leak_upstream_details(client, member, settings):
    client.force_login(member)
    settings.LLM_ENABLED = True
    settings.LLM_BASE_URL = "https://private.example.test/v1"
    settings.LLM_MODEL = "test-model"
    settings.LLM_PROVIDER = "openai_compatible"
    settings.LLM_API_KEY = "never-leak"
    with patch("analysis.llm_client.requests.post") as provider:
        for error in (requests.Timeout("never-leak"), requests.HTTPError("never-leak"),
                      requests.ConnectionError("never-leak")):
            provider.side_effect = error
            response = post(client, [GREETING])
            assert response.status_code == 503 and b"never-leak" not in response.content
        provider.side_effect = None
        provider.return_value.json.return_value = {"choices": []}
        assert post(client, [GREETING]).json()["code"] == "PET_MODEL_UNAVAILABLE"
        provider.return_value.json.return_value = {"choices": [{"message": {"content": "字" * 3200}}]}
        assert len(post(client, [GREETING]).json()["reply"]) == 2000
