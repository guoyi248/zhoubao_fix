"""
附件管线集成测试。
测试：上传 → 状态查询 → MIME 检测 → 确认 → 下载权限。
"""

import io
import hashlib
from unittest.mock import patch, MagicMock

import pytest
from django.test import Client

from accounts.models import User, UserRole, AccountStatus
from organizations.models import Department
from reporting.models import WeeklyReport, ReportingPeriod


pytestmark = pytest.mark.django_db

# ── Mock Storage ──────────────────────────────────────


def _mock_upload_stream(bucket, object_key, file_obj, content_type=None):
    """模拟流式上传，返回 SHA-256。"""
    sha = hashlib.sha256()
    size = 0
    while True:
        chunk = file_obj.read(8192)
        if not chunk:
            break
        sha.update(chunk)
        size += len(chunk)
    return {"sha256": sha.hexdigest(), "size": size}


@pytest.fixture(autouse=True)
def mock_storage_and_celery():
    """自动 mock 对象存储和 Celery 任务，避免依赖 MinIO/Redis。"""
    with patch("attachments.views.storage") as mock_store, \
         patch("attachments.tasks.storage") as mock_task_store, \
         patch("attachments.views.scan_file") as mock_scan, \
         patch("attachments.tasks.convert_to_pdf") as mock_convert:
        mock_store.upload_stream.side_effect = _mock_upload_stream
        mock_store.download_to_bytes.return_value = b"mock file content"
        mock_store.generate_download_stream.return_value = io.BytesIO(b"mock content")
        mock_store.client = MagicMock()
        mock_store.delete_object = MagicMock()
        mock_store.copy_object = MagicMock()
        mock_store.object_exists.return_value = True

        mock_task_store.download_to_bytes.return_value = b"mock file content"
        mock_task_store.client = MagicMock()

        # Celery tasks become no-ops
        mock_scan.delay = MagicMock()
        mock_convert.delay = MagicMock()

        yield mock_store


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
        assert data["original_filename"] == "test_report.txt"
        assert data["status"] in {"quarantined", "ready"}
        assert len(data["source_sha256"]) == 64

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
        assert data["original_filename"] == "test.pdf"

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
