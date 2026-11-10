import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from accounts.models import User
from audit.models import AuditEvent

URL = "/api/v1/admin/config/attachment-limits"
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("local_files")]


def upload(size):
    return {"file": SimpleUploadedFile("report.pdf", b"%PDF-" + b"X" * (size - 5))}


def test_admin_limits_apply_to_upload_replace_and_correction_without_changing_history(client, settings):
    admin = Client()
    admin.force_login(User.objects.create_user("manager", role="admin", account_status="active"))
    client.force_login(User.objects.create_user("editor", account_status="active"))
    assert client.get(URL).status_code == 403
    settings.MAX_ATTACHMENTS_PER_REPORT = 10
    settings.MAX_UPLOAD_BYTES = 200
    settings.MAX_REPORT_ATTACHMENT_BYTES = 500

    def change(payload, caller=admin):
        return caller.patch(URL, payload, content_type="application/json")

    limits = {"file_bytes":40, "total_bytes":45, "count":2}
    patch = {"version":0, "values":limits}
    assert change(patch, client).status_code == 403
    assert change({"version":0, "values":{"file_bytes":201}}).status_code == 400
    assert change(patch).json()["limits"] == limits
    assert change(patch).status_code == 409
    report = client.get("/api/v1/me/reports/current").json()
    assert report["attachment_limits"] == limits
    root = "/api/v1/me/reports/" + report["id"]
    attachments = root + "/attachments"
    too_big = client.post(attachments, upload(41))
    assert too_big.status_code == 413 and "40 字节" in too_big.json()["message"]
    first = client.post(attachments, upload(30)).json()["id"]
    over_total = client.post(attachments, upload(16))
    assert over_total.status_code == 400 and "45 字节" in over_total.json()["message"]
    second = client.post(attachments, upload(15)).json()["id"]
    over_count = client.post(attachments, upload(6))
    assert over_count.status_code == 400 and "2 个" in over_count.json()["message"]
    replace = "/api/v1/attachments/" + first + "/replace"
    assert client.post(replace, upload(50)).status_code == 413
    assert {r["id"] for r in client.get(attachments).json()} == {first, second}
    replaced = client.post(replace, upload(29)).json()["id"]
    assert client.post(root+"/submit", {"confirmed_pdf_attachment_id":replaced}, content_type="application/json").status_code == 201
    assert change({"version":1, "values":{"file_bytes":10}}).status_code == 200
    assert client.post(root+"/correct", upload(11)).status_code == 413
    revisions = client.get(root+"/revisions").json()
    assert len(revisions) == 1 and revisions[0]["confirmed_pdf_attachment_id"] == replaced
    previous = client.get("/api/v1/attachments/"+replaced+"/preview-content")
    assert previous.status_code == 200 and len(b"".join(previous.streaming_content)) == 29
    previous.close()
    settings.MAX_REPORT_ATTACHMENT_BYTES = 42
    assert admin.get(URL).json()["limits"]["total_bytes"] == 42
    assert change({"version":2,"reset":True}).json()["limits"] == {"file_bytes":200,"count":10,"total_bytes":42}
    assert AuditEvent.objects.filter(event_type="SYSTEM_SETTING_CHANGED").count() == 3
