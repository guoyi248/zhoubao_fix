"""Encrypt write-only integration credentials separately from the database."""
import base64
import hmac
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _fernet(secret):
    derived = hmac.digest(secret.encode(), b"weekly-report:integration-credentials:v1", "sha256")
    return Fernet(base64.urlsafe_b64encode(derived))


def _local_cipher(create):
    # The single-machine SQLite setup can run without a deployment secret.
    folder = Path(settings.BASE_DIR) / "secrets"
    keyfile = folder / "integrations.key"
    if create and not keyfile.exists():
        folder.mkdir(mode=0o700, exist_ok=True)
        with NamedTemporaryFile(dir=folder, delete=False) as stream:
            temp = Path(stream.name)
            stream.write(Fernet.generate_key())
        try:
            # Publish only complete keys, even when two workers start together.
            os.link(temp, keyfile)
        except FileExistsError:
            pass
        finally:
            temp.unlink()
    return Fernet(keyfile.read_bytes())


class CredentialUnavailable(ImproperlyConfigured):
    def __init__(self):
        super().__init__("无法验证服务凭据。请管理员检查部署加密密钥和服务地址，或在系统配置中重新保存凭据。")


def _write_cipher():
    if settings.SECRET_KEY == "CHANGE-ME-IN-PRODUCTION":
        if settings.SETTINGS_MODULE != "config.settings.development" or settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3":
            raise ImproperlyConfigured("保存凭据前，请为部署设置独立的 DJANGO_SECRET_KEY。")
        return "local", _local_cipher(True)
    return "app", _fernet(settings.SECRET_KEY)


def _decrypt(value):
    scheme, data = value.split(":", 1)
    if scheme == "local":
        cipher = _local_cipher(False)
    elif scheme == "app":
        cipher = MultiFernet([_fernet(key) for key in [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]])
    else:
        raise ValueError("凭据格式无效")
    return cipher.decrypt(data.encode()).decode()


def seal(value, *, section, destination):
    envelope = json.dumps({"section": section, "destination": destination, "value": value},
                          ensure_ascii=False, separators=(",", ":"))
    try:
        scheme, cipher = _write_cipher()
        return f"v2:{scheme}:" + cipher.encrypt(envelope.encode()).decode()
    except (OSError, ValueError):
        raise CredentialUnavailable() from None


def unseal(token, *, section, destination):
    try:
        if not isinstance(token, str) or not token.startswith("v2:"):
            raise CredentialUnavailable()
        envelope = json.loads(_decrypt(token[3:]))
        if (not isinstance(envelope, dict) or envelope.get("section") != section or
                envelope.get("destination") != destination or not isinstance(envelope.get("value"), str)):
            raise CredentialUnavailable()
        return envelope["value"]
    except (InvalidToken, OSError, ValueError):
        raise CredentialUnavailable() from None


def decrypt_legacy_for_migration(token):
    """Only the one-time data migration may read old tokens without an authenticated destination."""
    try:
        if not isinstance(token, str):
            raise CredentialUnavailable()
        return _decrypt(token)
    except (InvalidToken, OSError, ValueError):
        raise CredentialUnavailable() from None
