"""Effective integration configuration shared by HTTP and background workers."""
from urllib.parse import urlsplit

from django.conf import settings

from .credentials import CredentialUnavailable, unseal
from .models import SystemSetting

KEYS = {"model": "integrations.model", "mail": "integrations.mail"}
SECRET_FIELD = {"model": "api_key", "mail": "password"}
DESTINATION = {"model": ("provider", "base_url"), "mail": ("host", "port", "username", "use_ssl", "use_tls")}


def defaults(section):
    if section == "model":
        return {
            "enabled": settings.LLM_ENABLED, "provider": settings.LLM_PROVIDER.lower(),
            "base_url": settings.LLM_BASE_URL.rstrip("/"), "model": settings.LLM_MODEL,
            "api_key": settings.LLM_API_KEY_ENCRYPTED or settings.LLM_API_KEY,
        }
    return {
        "enabled": settings.WEEKLY_REMINDERS_ENABLED, "weekday": settings.REMINDER_WEEKDAY,
        "time": settings.REMINDER_TIME.strftime("%H:%M"), "site_url": settings.WEEKLY_SITE_URL,
        "host": settings.EMAIL_HOST, "port": settings.EMAIL_PORT, "username": settings.EMAIL_HOST_USER,
        "password": settings.EMAIL_HOST_PASSWORD, "from_email": settings.DEFAULT_FROM_EMAIL,
        "use_ssl": settings.EMAIL_USE_SSL, "use_tls": settings.EMAIL_USE_TLS,
    }


def destination(section, values):
    return [values[key] for key in DESTINATION[section]]


def effective_config(section, record, *, credentials=False):
    base = defaults(section)
    secret = SECRET_FIELD[section]
    overrides = record.get("values", {})
    values = {key: overrides.get(key, default) for key, default in base.items()}
    address = destination(section, values)
    saved = overrides.get(secret)
    if saved:
        values["has_secret"] = True
        if credentials:
            if not isinstance(saved, dict) or saved.get("destination") != address:
                raise CredentialUnavailable()
            values[secret] = unseal(saved.get("token"), section=section, destination=address)
    else:
        usable = secret not in overrides and address == destination(section, base)
        values[secret] = base[secret] if usable else ""
        values["has_secret"] = bool(values[secret])
        if credentials and usable and section == "model" and settings.LLM_API_KEY_ENCRYPTED:
            values[secret] = unseal(base[secret], section=section, destination=address)
    if not credentials:
        values.pop(secret)
    values["version"] = record.get("version", 0)
    values["source"] = "database" if overrides else "environment"
    return values


def get_config(section, *, credentials=False):
    record = SystemSetting.objects.filter(key=KEYS[section]).values_list("value", flat=True).first() or {}
    return effective_config(section, record, credentials=credentials)


def http_address(value):
    try:
        url = urlsplit(value)
        port = url.port
        return bool(url.scheme in {"http", "https"} and url.hostname and port != 0 and
                    url.username is None and url.password is None and not url.query and not url.fragment and
                    not any(c.isspace() or c == chr(92) for c in value))
    except (ValueError, TypeError):
        return False


def mail_issues(config):
    issues = []
    if not config["host"].strip():
        issues.append("EMAIL_HOST")
    if not config["from_email"].strip():
        issues.append("DEFAULT_FROM_EMAIL")
    if not http_address(config["site_url"]):
        issues.append("WEEKLY_SITE_URL")
    if not 1 <= config["port"] <= 65535:
        issues.append("EMAIL_PORT")
    if config["use_ssl"] and config["use_tls"]:
        issues.extend(["EMAIL_USE_TLS", "EMAIL_USE_SSL"])
    return issues


def model_issues(config):
    issues = []
    if config["provider"] not in {"ollama", "openai_compatible"}:
        issues.append("LLM_PROVIDER")
    if not http_address(config["base_url"]):
        issues.append("LLM_BASE_URL")
    if not config["model"].strip():
        issues.append("LLM_MODEL")
    return issues


def setup_info(issues):
    path = "deploy/config/app.env" if settings.SETTINGS_MODULE == "config.settings.production" else "backend/.env"
    return {"file": path, "issues": issues}
