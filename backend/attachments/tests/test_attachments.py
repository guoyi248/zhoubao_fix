"""
附件管线集成测试。
测试：上传 → 状态查询 → MIME 检测 → 确认 → 下载权限。
"""

import io
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from accounts.models import User, UserRole, AccountStatus
from organizations.models import Department
from reporting.models import WeeklyReport, ReportingPeriod


pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("local_files")]

@pytest.fixture
def department():
    return Department.objects.create(name="技术部", code="tech")


@pytest.fixture
def member(department):
    return User.objects.create_user(
        username="zhangsan",
        password="Test1234!",
        display_name="张三",
        role=UserRole.MEMBER,
        account_status=AccountStatus.ACTIVE,
        department=department,
    )


@pytest.fixture
def api_client(member):
    client = Client()
    client.post(
        "/api/v1/auth/login",
        {"username": "zhangsan", "password": "Test1234!"},
        content_type="application/json",
    )
    return client


@pytest.fixture
def current_report(api_client, member):
    """获取当前周期周报。"""
    r = api_client.get("/api/v1/me/reports/current")
    period_data = r.json()
    report_id = period_data["id"]
    return WeeklyReport.objects.get(id=report_id)


class TestAttachmentUpload:
    """附件上传测试。"""

    def test_pdf_is_listed_after_reload_and_streamed_from_originals(self, api_client, current_report, local_files):
        pdf = io.BytesIO(b"%PDF-1.4\n% report\n%%EOF")
        pdf.name = "weekly.pdf"
        path = f"/api/v1/me/reports/{current_report.id}/attachments"
        upload = api_client.post(path, {"file": pdf})
        assert upload.status_code == 201
        attachment_id = upload.json()["id"]
        preview = api_client.get(f"/api/v1/attachments/{attachment_id}/preview-content")
        assert preview.status_code == 200
        assert preview["Content-Type"] == "application/pdf"
        assert b"".join(preview.streaming_content) == pdf.getvalue()
        preview.close()
        from django.conf import settings
        assert local_files.generate_download_stream.call_args.args[0] == settings.S3_BUCKET_ORIGINALS
        listed = api_client.get(path)
        assert listed.status_code == 200
        assert [a["id"] for a in listed.json()] == [attachment_id]
        assert listed.json()[0]["preview_status"]["available"]

    def test_correction_preserves_frozen_meeting_and_rejects_invalid_file(self, api_client, current_report, department):
        base = f"/api/v1/me/reports/{current_report.id}"
        pdf = io.BytesIO(b"%PDF-1.4\n% first\n%%EOF")
        pdf.name = "v1.pdf"
        original = api_client.post(base + "/attachments", {"file": pdf}).json()["id"]
        first = api_client.post(base + "/submit", {}, content_type="application/json")
        assert first.status_code == 201
        admin = User.objects.create_user(username="leader", display_name="组长", role=UserRole.ADMIN,
                                         account_status=AccountStatus.ACTIVE, department=department)
        chair = Client()
        chair.force_login(admin)
        first_row = chair.get("/api/v1/admin/reports/overview").json()["submitted"][0]
        assert first_row["published_filename"] == "v1.pdf"
        assert first_row["revision_no"] == 1 and first_row["submitted_at"]
        meeting = chair.post("/api/v1/admin/meetings/", {
            "reporting_period_id": str(current_report.reporting_period_id),
        }, content_type="application/json").json()
        invalid = io.BytesIO(b"invalid")
        invalid.name = "wrong.exe"
        assert api_client.post(base + "/correct", {"file": invalid}).status_code == 400
        pdf = io.BytesIO(b"%PDF-1.4\n% second\n%%EOF")
        pdf.name = "v2.pdf"
        corrected = api_client.post(base + "/correct", {"file": pdf})
        assert corrected.status_code == 201
        latest = corrected.json()["attachment_id"]
        row = api_client.get("/api/v1/me/reports/").json()[0]
        assert row["published_filename"] == "v2.pdf" and row["revision_no"] == 2
        revisions = api_client.get(base + "/revisions").json()
        assert [r["confirmed_pdf_attachment_id"] for r in revisions] == [latest, original]
        assert [a["id"] for a in api_client.get(base + "/attachments").json()] == [latest]
        snapshot = chair.get(f"/api/v1/admin/meetings/{meeting['id']}").json()["snapshots"][0]
        assert snapshot["confirmed_pdf_attachment_id"] == original
        legacy = current_report.attachments.get(pk=latest)
        legacy.uploaded_filename = ""
        legacy.save(update_fields=["uploaded_filename"])
        assert api_client.get("/api/v1/me/reports/").json()[0]["published_filename"] == legacy.original_filename
        preview = chair.get(f"/api/v1/attachments/{original}/preview-content")
        assert preview.status_code == 200
        preview.close()
        from audit.models import AuditEvent
        history = AuditEvent.objects.filter(target_id=str(current_report.pk), actor=current_report.owner)
        assert list(history.order_by("created_at").values_list("event_type", flat=True)) == [
            "ATTACHMENT_UPLOADED", "REPORT_SUBMITTED", "REPORT_RESUBMITTED",
        ]

    def test_projected_pages_keep_layout_and_check_access_before_cache(self, api_client, current_report):
        import fitz

        with fitz.open() as doc:
            doc.new_page(width=400, height=600).insert_text((30, 50), "First page")
            doc.new_page(width=600, height=400).insert_text((30, 50), "Landscape")
            file = SimpleUploadedFile("two-pages.pdf", doc.tobytes())
        root = f"/api/v1/me/reports/{current_report.pk}"
        attachment = api_client.post(root + "/attachments", {"file": file}).json()
        path = "/api/v1/attachments/" + attachment["id"] + "/presentation-pages/"
        first = api_client.get(path + "1")
        assert first.status_code == 200 and first.content.startswith(b"\x89PNG")
        assert first["X-Page-Count"] == "2"
        assert int(first["X-Page-Height"]) > int(first["X-Page-Width"])
        assert api_client.get(path + "1", HTTP_IF_NONE_MATCH=first["ETag"]).status_code == 304
        assert api_client.get(path + "3").status_code == 404
        chair = Client()
        chair.force_login(User.objects.create_user("chair", role="admin", account_status="active"))
        assert chair.get(path + "1", HTTP_IF_NONE_MATCH=first["ETag"]).status_code == 403
        assert api_client.post(root + "/submit", {}, content_type="application/json").status_code == 201
        second = chair.get(path + "2")
        assert int(second["X-Page-Width"]) > int(second["X-Page-Height"])
        stranger = Client()
        stranger.force_login(User.objects.create_user("reader", account_status="active"))
        assert stranger.get(path + "2", HTTP_IF_NONE_MATCH=second["ETag"]).status_code == 403

    def test_upload_txt_file(self, api_client, current_report):
        """上传 TXT 文件。"""
        content = b"Hello, this is a test report content."
        f = io.BytesIO(content)
        f.name = "test_report.txt"

        response = api_client.post(
            f"/api/v1/me/reports/{current_report.id}/attachments",
            {"file": f},
            format="multipart",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["original_filename"].startswith("hubu_")
        assert data["uploaded_filename"] == "test_report.txt"
        assert data["status"] == "preview_ready"
        assert len(data["source_sha256"]) == 64

    def test_repair_published_word_preview_preserves_versions_and_refreshes_pages(
        self, api_client, current_report, local_files, monkeypatch,
    ):
        from hashlib import sha256
        from unittest.mock import Mock

        import fitz
        from django.conf import settings
        from django.core.management import call_command, CommandError
        from attachments.models import Attachment, AttachmentExtractedText, AttachmentPreview, AttachmentStatus
        from attachments.tasks import read_attachment_text

        att = Attachment.objects.create(
            report=current_report, uploaded_by=current_report.owner, detected_mime="application/msword",
            original_filename="legacy.doc", safe_filename="legacy.doc", original_object_key="originals/legacy/source",
            source_sha256="a" * 64, status=AttachmentStatus.USER_CONFIRMED,
        )
        old_key = "previews/legacy/preview.pdf"
        with fitz.open() as doc:
            doc.new_page().insert_text((50, 50), "Old text only")
            old_pdf = doc.tobytes()
            doc.new_page(width=600, height=400).insert_text((50, 50), "Second page")
            new_pdf = doc.tobytes()
        local_files.put_object(Bucket=settings.S3_BUCKET_PREVIEWS, Key=old_key, Body=old_pdf)
        old = AttachmentPreview.objects.create(
            attachment=att, preview_object_key=old_key, source_sha256=att.source_sha256,
            converter_name="fpdf2", output_sha256=sha256(old_pdf).hexdigest(), page_count=1, status="ready",
        )
        AttachmentExtractedText.objects.create(attachment=att, content="Old text only", extractor_name="PyMuPDF")
        revision = current_report.submit(current_report.owner, confirmed_pdf_attachment=att)
        page_url = f"/api/v1/attachments/{att.pk}/presentation-pages/"
        old_etag = api_client.get(page_url + "1")["ETag"]
        engine = Mock(return_value=None)
        monkeypatch.setattr("attachments.management.commands.repair_word_previews.convert_and_store", engine)
        call_command("repair_word_previews", dry_run=True, stdout=io.StringIO())
        engine.assert_not_called()
        with pytest.raises(CommandError):
            call_command("repair_word_previews", stdout=io.StringIO(), stderr=io.StringIO())
        old.refresh_from_db()
        assert old.status == "ready" and att.previews.count() == 1
        assert api_client.get(page_url + "1", HTTP_IF_NONE_MATCH=old_etag).status_code == 304

        new_sha = sha256(new_pdf).hexdigest()
        new_key = f"previews/legacy/{new_sha}.pdf"
        local_files.put_object(Bucket=settings.S3_BUCKET_PREVIEWS, Key=new_key, Body=new_pdf)
        engine.return_value = {
            "object_key": new_key, "sha256": new_sha, "page_count": 2,
            "converter_name": "LibreOffice", "converter_version": "test",
        }
        call_command("repair_word_previews", stdout=io.StringIO())
        call_command("repair_word_previews", stdout=io.StringIO())
        assert engine.call_count == 2  # 首次失败和一次成功，同一修复可重复执行。
        old.refresh_from_db()
        att.refresh_from_db()
        revision.refresh_from_db()
        assert att.previews.count() == 2 and old.status == "superseded"
        assert att.status == AttachmentStatus.USER_CONFIRMED
        assert revision.confirmed_pdf_attachment_id == att.id and current_report.revisions.count() == 1
        assert local_files.download_to_bytes(settings.S3_BUCKET_PREVIEWS, old_key) == old_pdf
        fresh = api_client.get(page_url + "1", HTTP_IF_NONE_MATCH=old_etag)
        assert fresh.status_code == 200 and fresh["ETag"] != old_etag and fresh["X-Page-Count"] == "2"
        assert api_client.get(page_url + "2").status_code == 200
        assert "Second page" in read_attachment_text(Attachment.objects.get(pk=att.pk))

    def test_repair_only_old_office_math_previews(self, current_report, local_files, monkeypatch, settings):
        from hashlib import sha256
        from unittest.mock import Mock
        from zipfile import ZipFile

        from django.core.management import CommandError, call_command
        from attachments.models import Attachment, AttachmentPreview
        from attachments.word_preview_versions import EQUATION_VERSION

        def add_preview(name, renderer, version, has_equation):
            source = io.BytesIO()
            ns = "http://schemas.openxmlformats.org/officeDocument/2006/math"
            with ZipFile(source, "w") as package:
                package.writestr("word/document.xml", "<doc/>")
                package.writestr("word/header1.xml", f'<x xmlns="{ns}"><oMath/></x>' if has_equation else "<x/>")
                # Non-content metadata alone should never select an attachment.
                package.writestr("word/settings.xml", f'<x xmlns="{ns}"><oMath/></x>')
            digest = sha256(source.getvalue()).hexdigest()
            key = "originals/" + name + "/source"
            local_files.put_object(Bucket=settings.S3_BUCKET_ORIGINALS, Key=key, Body=source.getvalue())
            att = Attachment.objects.create(
                report=current_report, uploaded_by=current_report.owner, detected_mime="application/msword",
                original_filename=name + ".docx", safe_filename=name + ".docx", original_object_key=key,
                source_sha256=digest, status="user_confirmed",
            )
            return AttachmentPreview.objects.create(
                attachment=att, preview_object_key="previews/" + name + "/old.pdf", source_sha256=digest,
                converter_name=renderer, converter_version=version, output_sha256="a" * 64, page_count=1,
                status="ready",
            )

        old = add_preview("equation", "LibreOffice", "26", True)
        other = add_preview("plain", "LibreOffice", "26", False)
        new = add_preview("current", "Gotenberg", "8" + EQUATION_VERSION, True)
        engine = Mock(return_value={
            "object_key": "previews/upgraded.pdf", "sha256": "b" * 64, "page_count": 1,
            "converter_name": "Gotenberg", "converter_version": "8",
        })
        monkeypatch.setattr("attachments.management.commands.repair_word_previews.convert_and_store", engine)
        listing = io.StringIO()
        call_command("repair_word_previews", dry_run=True, stdout=listing)
        assert str(old.attachment_id) in listing.getvalue()
        assert str(other.attachment_id) not in listing.getvalue()
        assert str(new.attachment_id) not in listing.getvalue()
        engine.assert_not_called()
        with pytest.raises(CommandError):
            call_command("repair_word_previews", stdout=io.StringIO(), stderr=io.StringIO())
        old.refresh_from_db()
        assert old.status == "ready" and old.attachment.previews.count() == 1

        engine.return_value["converter_version"] += EQUATION_VERSION
        call_command("repair_word_previews", stdout=io.StringIO())
        call_command("repair_word_previews", stdout=io.StringIO())
        assert engine.call_count == 2  # failed attempt and successful retry
        old.refresh_from_db()
        assert old.status == "superseded"
        assert old.attachment.previews.get(status="ready").converter_version == "8" + EQUATION_VERSION

    def test_upload_pdf_file(self, api_client, current_report):
        """上传 PDF（最小有效 PDF）。"""
        # 最小有效 PDF
        pdf = (
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
            b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
            b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"
        )
        f = io.BytesIO(pdf)
        f.name = "test.pdf"

        response = api_client.post(
            f"/api/v1/me/reports/{current_report.id}/attachments",
            {"file": f},
            format="multipart",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["original_filename"].startswith("hubu_")

    def test_upload_disallowed_extension(self, api_client, current_report):
        """拒绝危险扩展名。"""
        f = io.BytesIO(b"malicious!")
        f.name = "evil.exe"

        response = api_client.post(
            f"/api/v1/me/reports/{current_report.id}/attachments",
            {"file": f},
            format="multipart",
        )
        assert response.status_code == 400
        assert response.json()["code"] == "FILE_TYPE_NOT_ALLOWED"

    def test_legacy_text_can_regenerate_preview_and_missing_original_is_reported(self, api_client, current_report, local_files):
        from django.conf import settings
        from attachments.models import AttachmentStatus

        path = f"/api/v1/me/reports/{current_report.pk}/attachments"
        row = api_client.post(path, {"file": SimpleUploadedFile("weekly.txt", b"first\nsecond")}).json()
        attachment = current_report.attachments.get(pk=row["id"])
        attachment.previews.all().delete()
        attachment.status = AttachmentStatus.STORED
        attachment.save()
        base = f"/api/v1/attachments/{attachment.pk}"
        assert api_client.post(base + "/retry", {}, content_type="application/json").status_code == 200
        assert api_client.get(path).json()[0]["preview_status"]["available"]
        local_files.delete_object(settings.S3_BUCKET_ORIGINALS, attachment.original_object_key)
        assert api_client.get(base + "/download").status_code == 404

    def test_text_preview_keeps_long_lines(self):
        from attachments.converter import convert_txt_to_pdf
        import fitz

        with fitz.open(stream=convert_txt_to_pdf("x" * 180 + "END\nsecond line"), filetype="pdf") as pdf:
            text = "".join(page.get_text() for page in pdf)
        assert "END" in text and "second line" in text

    def test_file_only_report_needs_a_displayable_attachment(self, api_client, current_report):
        path = f"/api/v1/me/reports/{current_report.pk}"
        upload = api_client.post(path + "/attachments", {"file": SimpleUploadedFile("docs.zip", b"archive")})
        assert upload.status_code == 201
        refused = api_client.post(path + "/submit", {}, content_type="application/json")
        assert refused.status_code == 409
        assert refused.json()["code"] == "NO_PREVIEW"
        assert not current_report.revisions.exists()

    def test_replace_at_limit_converts_word_and_preserves_old_on_failure(self, api_client, current_report, settings, monkeypatch):
        import fitz
        path = f"/api/v1/me/reports/{current_report.pk}/attachments"
        settings.MAX_ATTACHMENTS_PER_REPORT = 1
        pdf = SimpleUploadedFile("weekly.pdf", b"%PDF-1.4\nold\n%%EOF")
        original = api_client.post(path, {"file": pdf}).json()["id"]
        replace = f"/api/v1/attachments/{original}/replace"
        invalid = SimpleUploadedFile("broken.docx", b"not an office file")
        assert api_client.post(replace, {"file": invalid}).status_code == 422
        settings.MAX_REPORT_ATTACHMENT_BYTES = 10
        too_large = SimpleUploadedFile("too-large.txt", b"A" * 11)
        assert api_client.post(replace, {"file": too_large}).status_code == 400
        assert [a["id"] for a in api_client.get(path).json()] == [original]
        settings.MAX_REPORT_ATTACHMENT_BYTES = 1_000_000
        sample = Path(__file__).resolve().parents[3] / "tests/office-samples/sample_report.docx"
        with fitz.open() as document:
            document.new_page()
            office_output = document.tobytes()
        def office_service(data, filename):
            assert filename == "source.docx" and data == sample.read_bytes()
            return office_output
        monkeypatch.setattr("attachments.converter.convert_via_gotenberg", office_service)
        with sample.open("rb") as word:
            response = api_client.post(replace, {"file": word})
        assert response.status_code == 201
        updated = response.json()
        assert updated["status"] == "preview_ready"
        from audit.models import AuditEvent
        changes = AuditEvent.objects.filter(target_id=str(current_report.pk), event_type="ATTACHMENT_REPLACED")
        assert changes.count() == 1 and "sample_report.docx" in changes.get().summary
        assert [a["id"] for a in api_client.get(path).json()] == [updated["id"]]
        pdf = api_client.get(f"/api/v1/attachments/{updated['id']}/preview-content")
        assert b"".join(pdf.streaming_content).startswith(b"%PDF-")
        pdf.close()

    def test_cannot_upload_to_submitted_report(self, api_client, current_report):
        """已提交的周报不能上传新附件。"""
        api_client.post(
            f"/api/v1/me/reports/{current_report.id}/submit",
            {},
            content_type="application/json",
        )
        f = io.BytesIO(b"test")
        f.name = "test.txt"
        response = api_client.post(
            f"/api/v1/me/reports/{current_report.id}/attachments",
            {"file": f},
            format="multipart",
        )
        assert response.status_code == 409


class TestAttachmentStatus:
    """附件状态查询测试。"""

    def test_status_polling(self, api_client, current_report):
        """状态轮询。"""
        f = io.BytesIO(b"status test content")
        f.name = "status.txt"
        upload_resp = api_client.post(
            f"/api/v1/me/reports/{current_report.id}/attachments",
            {"file": f},
            format="multipart",
        )
        attachment_id = upload_resp.json()["id"]

        status_resp = api_client.get(f"/api/v1/attachments/{attachment_id}/status")
        assert status_resp.status_code == 200
        assert "status" in status_resp.json()

    def test_batch_status(self, api_client, current_report):
        """批量状态查询。"""
        ids = []
        for i in range(3):
            f = io.BytesIO(f"batch {i}".encode())
            f.name = f"batch_{i}.txt"
            resp = api_client.post(
                f"/api/v1/me/reports/{current_report.id}/attachments",
                {"file": f},
                format="multipart",
            )
            ids.append(resp.json()["id"])

        batch_resp = api_client.post(
            "/api/v1/attachments/batch-status",
            {"attachment_ids": ids},
            content_type="application/json",
        )
        assert batch_resp.status_code == 200
        assert len(batch_resp.json()["statuses"]) == 3


class TestAttachmentPermissions:
    """附件权限测试。"""

    def test_reopened_draft_is_private_until_resubmitted(self, api_client, current_report):
        admin = User.objects.create_user("leader", role=UserRole.ADMIN, account_status=AccountStatus.ACTIVE)
        chair = Client()
        chair.force_login(admin)
        path = f"/api/v1/me/reports/{current_report.pk}"
        def upload(name):
            return api_client.post(path + "/attachments", {
                "file": SimpleUploadedFile(name, b"%PDF-1.4\nreport\n%%EOF"),
            }).json()["id"]
        published, supplement = upload("main.pdf"), upload("appendix.pdf")
        current_report.save_draft({"completed": ["published"]}, 0)
        submit = api_client.post(path + "/submit", {"confirmed_pdf_attachment_id": published,
                                "reason": "first version"}, content_type="application/json")
        assert submit.status_code == 201
        assert api_client.post(path + "/resubmit", {}, content_type="application/json").status_code == 200
        current_report.refresh_from_db()
        current_report.save_draft({"completed": ["unfinished"]}, current_report.optimistic_version)
        staged = upload("unpublished.pdf")
        data = chair.get(f"/api/v1/admin/reports/{current_report.pk}").json()
        assert data["draft_content_json"] == {"completed": ["published"]}
        assert data["revisions"][0]["reason"] == "first version"
        assert chair.get(f"/api/v1/attachments/{staged}/preview-content").status_code == 403
        assert api_client.delete(f"/api/v1/attachments/{supplement}/delete").status_code == 204
        batch = {"attachment_ids": [published, supplement, staged]}
        statuses = chair.post("/api/v1/attachments/batch-status", batch, content_type="application/json")
        assert set(statuses.json()["statuses"]) == {published, supplement}
        reject = api_client.post(f"/api/v1/attachments/{published}/confirm", {"confirmed": False},
                                 content_type="application/json")
        assert reject.status_code == 409
        preview = chair.get(f"/api/v1/attachments/{published}/preview-content")
        assert preview.status_code == 200
        preview.close()
        stranger = User.objects.create_user("stranger", account_status=AccountStatus.ACTIVE)
        chair.force_login(stranger)
        statuses = chair.post("/api/v1/attachments/batch-status", batch, content_type="application/json")
        assert statuses.json()["statuses"] == {}

    @pytest.mark.parametrize(("verdict", "status"), [
        (b"stream: test-signature FOUND\n", 400),
        (b"stream: size limit exceeded. ERROR\n", 503),
        (b"stream: OK\n", 201),
    ])
    def test_scanner_must_return_clean_before_storage(self, api_client, current_report, settings, monkeypatch, verdict, status):
        from unittest.mock import MagicMock
        settings.CLAMAV_SCAN_UPLOADS = True
        sock = MagicMock()
        sock.__enter__.return_value.makefile.return_value.__enter__.return_value.readline.return_value = verdict
        monkeypatch.setattr("attachments.scanning.socket.create_connection", lambda *args, **kwargs: sock)
        response = api_client.post(f"/api/v1/me/reports/{current_report.pk}/attachments", {
            "file": SimpleUploadedFile("new.pdf", b"%PDF-1.4\nreport\n%%EOF"),
        })
        assert response.status_code == status
        assert current_report.attachments.count() == (1 if status == 201 else 0)

    def test_member_b_cannot_download_member_a_attachment(self, api_client, current_report, member, department):
        """成员不能下载他人的附件。"""
        # 上传附件
        f = io.BytesIO(b"secret content")
        f.name = "secret.txt"
        upload_resp = api_client.post(
            f"/api/v1/me/reports/{current_report.id}/attachments",
            {"file": f},
            format="multipart",
        )
        attachment_id = upload_resp.json()["id"]

        # 登出
        api_client.post("/api/v1/auth/logout")

        # 成员 B 登录
        member_b = User.objects.create_user(
            username="lisi",
            password="Test1234!",
            display_name="李四",
            role=UserRole.MEMBER,
            account_status=AccountStatus.ACTIVE,
            department=department,
        )
        client_b = Client()
        client_b.post(
            "/api/v1/auth/login",
            {"username": "lisi", "password": "Test1234!"},
            content_type="application/json",
        )

        # 尝试下载
        resp = client_b.get(f"/api/v1/attachments/{attachment_id}/download")
        assert resp.status_code == 403
