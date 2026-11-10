from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.apps import apps
from django.db import connection

from accounts.models import User
from audit.models import AuditEvent
from system_config.credentials import CredentialUnavailable, _fernet, seal, unseal
from system_config.integrations import effective_config, get_config
from system_config.models import SystemSetting

pytestmark = pytest.mark.django_db
SITE = ["openai_compatible", "https://models.example.test/v1"]


def test_tampered_database_cannot_retarget_a_key_or_leak_it(client, settings):
    settings.SECRET_KEY = "server-key"
    admin = User.objects.create_user("settings-owner", role="admin", account_status="active")
    client.force_login(admin)
    url = "/api/v1/admin/config/integrations"
    response = client.patch(url, {"section": "model", "version": 0, "values": {
        "enabled": True, "provider": SITE[0], "base_url": SITE[1], "model": "test",
        "api_key": "private-model-key",
    }}, content_type="application/json")
    assert response.status_code == 200 and response.json()["has_secret"]
    row = SystemSetting.objects.get(key="integrations.model")
    stored = row.value["values"]["api_key"]
    assert stored["token"].startswith("v2:") and "private-model-key" not in str(row.value)
    assert "private-model-key" not in str(list(AuditEvent.objects.values()))
    assert b"private-model-key" not in client.get(url).content and stored["token"].encode() not in client.get(url).content
    assert get_config("model", credentials=True)["api_key"] == "private-model-key"
    with pytest.raises(CredentialUnavailable):
        unseal(stored["token"], section="mail", destination=SITE)
    row.value["values"]["base_url"] = "https://attacker.example.test/v1"
    stored["destination"][1] = row.value["values"]["base_url"]
    row.save(update_fields=["value"])
    with patch("analysis.llm_client.requests.post") as network:
        failed = client.post("/api/v1/pet/chat", {"messages": [{"role": "user", "content": "test"}]},
                             content_type="application/json")
        assert failed.status_code == 503 and "重新保存凭据" in failed.json()["message"]
        assert b"private-model-key" not in failed.content and stored["token"].encode() not in failed.content
        network.assert_not_called()
    cleared = client.patch(url, {"section": "model", "version": 1, "values": {"api_key": ""}},
                           content_type="application/json")
    assert cleared.status_code == 200 and not get_config("model", credentials=True)["api_key"]


def test_env_ciphertext_precedence_and_recovery(settings):
    settings.SECRET_KEY = "server-key"
    settings.LLM_PROVIDER, settings.LLM_BASE_URL = SITE
    settings.LLM_API_KEY = "old-plain-env-key"
    settings.LLM_API_KEY_ENCRYPTED = seal("env-secret", section="model", destination=SITE)
    assert effective_config("model", {}, credentials=True)["api_key"] == "env-secret"
    settings.SECRET_KEY = "rotated-server-key"
    with pytest.raises(CredentialUnavailable):
        effective_config("model", {}, credentials=True)
    assert "api_key" not in effective_config("model", {})
    assert effective_config("model", {"values": {"api_key": ""}}, credentials=True)["api_key"] == ""
    assert effective_config("model", {"values": {"base_url": "http://other.test"}}, credentials=True)["api_key"] == ""
    override = seal("db-secret", section="model", destination=SITE)
    record = {"values": {"api_key": {"token": override, "destination": SITE}}}
    assert effective_config("model", record, credentials=True)["api_key"] == "db-secret"
    settings.SECRET_KEY_FALLBACKS = ["server-key"]
    assert effective_config("model", {}, credentials=True)["api_key"] == "env-secret"


def test_local_wrapping_key_loss_does_not_generate_a_replacement():
    with TemporaryDirectory() as folder:
        development = SimpleNamespace(SECRET_KEY="CHANGE-ME-IN-PRODUCTION", BASE_DIR=Path(folder),
                                      SETTINGS_MODULE="config.settings.development",
                                      DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3"}})
        with patch("system_config.credentials.settings", development):
            token = seal("local-secret", section="model", destination=SITE)
            assert token.startswith("v2:local:") and unseal(token, section="model", destination=SITE) == "local-secret"
            key_file = development.BASE_DIR / "secrets" / "integrations.key"
            key_file.unlink()
            with pytest.raises(CredentialUnavailable) as error:
                unseal(token, section="model", destination=SITE)
            assert not key_file.exists() and "local-secret" not in str(error.value) and token not in str(error.value)


def test_migration_upgrades_legacy_tokens_and_cleartext_idempotently(settings):
    settings.SECRET_KEY = "server-key"
    address = ["smtp.test", 465, "sender", True, False]
    old = "app:" + _fernet(settings.SECRET_KEY).encrypt(b"mail-secret").decode()
    SystemSetting.objects.create(key="integrations.mail", value={"version": 1, "values": {
        "host": address[0], "port": address[1], "username": address[2], "use_ssl": True, "use_tls": False,
        "password": {"token": old, "destination": address},
    }})
    SystemSetting.objects.create(key="integrations.model", value={"version": 1, "values": {
        "provider": SITE[0], "base_url": SITE[1], "api_key": "old-model-secret",
    }})
    with pytest.raises(CredentialUnavailable):
        get_config("mail", credentials=True)
    with pytest.raises(CredentialUnavailable):
        get_config("model", credentials=True)
    run = import_module("system_config.migrations.0002_bind_integration_credentials").bind_credentials
    run(apps, SimpleNamespace(connection=connection))
    snapshots = list(SystemSetting.objects.order_by("pk").values_list("value", flat=True))
    assert old not in str(snapshots) and "old-model-secret" not in str(snapshots)
    assert get_config("model", credentials=True)["api_key"] == "old-model-secret"
    assert get_config("mail", credentials=True)["password"] == "mail-secret"
    run(apps, SimpleNamespace(connection=connection))
    assert snapshots == list(SystemSetting.objects.order_by("pk").values_list("value", flat=True))
