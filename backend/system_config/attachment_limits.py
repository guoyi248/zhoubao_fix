from django.conf import settings

from .models import SystemSetting

KEY = "reports.attachment_limits"


def ceilings():
    return {"file_bytes": settings.MAX_UPLOAD_BYTES, "total_bytes": settings.MAX_REPORT_ATTACHMENT_BYTES,
            "count": settings.MAX_ATTACHMENTS_PER_REPORT}


def policy(record=None):
    if record is None:
        record = SystemSetting.objects.filter(key=KEY).values_list("value", flat=True).first() or {}
    hard = ceilings()
    stored = record.get("values", {})
    return {"limits": {field: min(value, stored.get(field, value)) for field, value in hard.items()},
            "ceilings": hard, "source": "database" if stored else "environment", "version": record.get("version", 0)}


def byte_label(size):
    for divisor, unit in [(1_048_576, "MiB"), (1024, "KiB")]:
        if size >= divisor and size % divisor == 0:
            return f"{size // divisor} {unit}"
    return f"{size:,} 字节"
