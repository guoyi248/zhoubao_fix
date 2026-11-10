from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from audit.events import record
from audit.models import AuditEvent
from common.exceptions import PermissionDeniedError
from . import attachment_limits
from .credentials import seal
from .integrations import (KEYS, SECRET_FIELD, defaults, destination, effective_config,
                           get_config, http_address, mail_issues, model_issues)
from .models import SystemSetting
from .serializers import ModelFields, MailFields


def _public(section, values):
    url_name = "base_url" if section == "model" else "site_url"
    if values[url_name] and not http_address(values[url_name]):
        # Existing .env URLs may contain embedded credentials.
        values[url_name] = ""
    return values


def _error(message, status=400):
    return Response({"code": "CONFIG_CONFLICT" if status == 409 else "INVALID_CONFIG", "message": message}, status=status)


def _persist(request, row, value, label, reset):
    with transaction.atomic():
        saved = SystemSetting.objects.filter(pk=row.pk, value__version=value["version"] - 1).update(
            value=value, updated_at=timezone.now()
        )
        if saved:
            summary = ("恢复环境配置 · " if reset else "更新配置 · ") + label
            record(request, AuditEvent.EventType.SYSTEM_SETTING_CHANGED, summary, target=row, risk="medium")
        return bool(saved)


@api_view(["GET", "PATCH"])
def attachment_policy(request):
    if not request.user.is_admin:
        raise PermissionDeniedError()
    if request.method == "GET":
        return Response(attachment_limits.policy())
    data = request.data
    if not isinstance(data, dict) or type(data.get("version")) is not int:
        return _error("版本号无效，请重新载入。")
    reset = data.get("reset") is True
    patch = data.get("values", {})
    hard = attachment_limits.ceilings()
    if not isinstance(patch, dict) or set(patch) - set(hard) or (reset and patch) or (not reset and not patch):
        return _error("请填写有效的附件限制。")
    labels = {"count": "附件数量", "file_bytes": "单文件大小", "total_bytes": "附件总大小"}
    for field, val in patch.items():
        if type(val) is not int or not 0 < val <= hard[field]:
            limit = str(hard[field]) + " 个" if field == "count" else attachment_limits.byte_label(hard[field])
            return _error(labels[field] + "必须大于零，且不能超过部署上限 " + limit)
    row, _ = SystemSetting.objects.get_or_create(key=attachment_limits.KEY, defaults={"value": {"version": 0, "values": {}}})
    value = {"version": data["version"] + 1, "values": {} if reset else {**row.value["values"], **patch}}
    if not _persist(request, row, value, "附件限制", reset):
        return _error("其他管理员已更新此配置，请重新载入后再保存。", 409)
    return Response(attachment_limits.policy(value))


@api_view(["GET"])
def list_config(request):
    if not request.user.is_admin:
        raise PermissionDeniedError()
    return Response(dict(SystemSetting.objects.exclude(key__in=KEYS.values()).values_list("key", "value")))


@api_view(["GET", "PATCH"])
def integrations(request):
    if not request.user.is_admin:
        raise PermissionDeniedError()
    if request.method == "GET":
        return Response({section: _public(section, get_config(section)) for section in KEYS})

    payload = request.data
    if not isinstance(payload, dict) or payload.get("section") not in ("model", "mail"):
        return _error("请选择模型解析或邮箱提醒。")
    section = payload["section"]
    version = payload.get("version")
    reset = payload.get("reset") is True
    patch = payload.get("values", {})
    if type(version) is not int or version < 0 or not isinstance(patch, dict) or (reset and patch):
        return _error("配置数据无效，请刷新页面。")
    form = (ModelFields if section == "model" else MailFields)(data=patch, partial=True)
    if set(patch) - set(form.fields):
        return _error("包含不支持的配置项。")
    if not form.is_valid():
        field, messages = next(iter(form.errors.items()))
        return _error(f"{field} · {messages[0]}")
    changes = dict(form.validated_data)
    if not changes and not reset:
        return _error("尚未修改配置。")
    if any(isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value) for value in changes.values()):
        return _error("配置不能包含换行或控制字符。")

    row, _ = SystemSetting.objects.get_or_create(key=KEYS[section], defaults={"value": {"version": 0, "values": {}}})
    old = row.value
    if old["version"] != version:
        return _error("其他管理员已更新此配置，请重新载入后再保存。", 409)
    secret_field = SECRET_FIELD[section]
    secret = changes.pop(secret_field, None)
    overrides = {} if reset else {**old["values"], **changes}
    current = effective_config(section, old)
    updated = {**defaults(section), **overrides}
    address = destination(section, updated)
    if secret:
        try:
            overrides[secret_field] = {"destination": address, "token": seal(secret, section=section, destination=address)}
        except ImproperlyConfigured as exc:
            return _error(str(exc))
    elif not reset and (secret == "" or destination(section, current) != address):
        # Never send an existing credential to a new host, account or protocol.
        overrides[secret_field] = ""

    value = {"version": version + 1, "values": overrides}
    effective = effective_config(section, value)
    issues = (model_issues if section == "model" else mail_issues)(effective)
    if not reset and effective["enabled"] and issues:
        return _error("启用前请补全或修正：" + "、".join(issues))
    if not reset and section == "mail" and effective["use_ssl"] and effective["use_tls"]:
        return _error("请选择一种 SMTP 加密方式。")

    label = "模型解析" if section == "model" else "邮箱提醒"
    if not _persist(request, row, value, label, reset):
        return _error("其他管理员已更新此配置，请重新载入后再保存。", 409)
    return Response(_public(section, effective))
