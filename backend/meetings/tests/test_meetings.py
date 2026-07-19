"""
组会模式集成测试。
测试：创建组会、锁定快照、标记已讨论、行动项 CRUD。
"""

import pytest
from datetime import date, timedelta
from django.test import Client

from accounts.models import User, UserRole, AccountStatus
from organizations.models import Department
from reporting.models import (
    ReportingPeriod, WeeklyReport, WeeklyReportRevision,
    ReportStatus,
)
from meetings.models import Meeting, MeetingReportSnapshot, ActionItem


pytestmark = pytest.mark.django_db


@pytest.fixture
def department():
    return Department.objects.create(name="技术部", code="tech")


@pytest.fixture
def admin(department):
    return User.objects.create_user(
        username="admin",
        password="Admin123!",
        display_name="管理员",
        role=UserRole.SUPER_ADMIN,
        account_status=AccountStatus.ACTIVE,
        department=department,
    )


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
def admin_client(admin):
    client = Client()
    client.post(
        "/api/v1/auth/login",
        {"username": "admin", "password": "Admin123!"},
        content_type="application/json",
    )
    return client


@pytest.fixture
def period_with_reports(admin, member, department):
    """创建含已提交周报的周期。"""
    member2 = User.objects.create_user(
        username="lisi",
        password="Test1234!",
        display_name="李四",
        role=UserRole.MEMBER,
        account_status=AccountStatus.ACTIVE,
        department=department,
    )

    period = ReportingPeriod.objects.create(
        iso_year=2026,
        iso_week=30,
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 26),
        deadline="2026-07-27T00:00:00Z",
    )

    for m in [member, member2]:
        report = WeeklyReport.objects.create(
            owner=m,
            reporting_period=period,
            status=ReportStatus.SUBMITTED,
            draft_content_json={"completed": [f"{m.display_name}的工作"]},
        )
        revision = WeeklyReportRevision.objects.create(
            report=report,
            revision_no=1,
            structured_content_json=report.draft_content_json,
            submitted_by=m,
            content_sha256=f"sha_{m.username}",
        )
        report.current_revision = revision
        report.save(update_fields=["current_revision"])

    return period


class TestMeetingLifecycle:
    """组会全生命周期测试。"""

    def test_create_meeting_freezes_snapshots(self, admin_client, period_with_reports):
        """创建组会应锁定所有已提交周报的 Revision 快照。"""
        resp = admin_client.post(
            "/api/v1/admin/meetings/",
            {"reporting_period_id": str(period_with_reports.id)},
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["snapshots"]) == 2
        assert data["status"] == "planned"

    def test_member_cannot_create_meeting(self, period_with_reports, member):
        """成员不能创建组会。"""
        client = Client()
        client.post(
            "/api/v1/auth/login",
            {"username": "zhangsan", "password": "Test1234!"},
            content_type="application/json",
        )
        resp = client.post(
            "/api/v1/admin/meetings/",
            {"reporting_period_id": str(period_with_reports.id)},
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_start_and_finish_meeting(self, admin_client, period_with_reports):
        """开始和结束组会。"""
        # 创建
        create_resp = admin_client.post(
            "/api/v1/admin/meetings/",
            {"reporting_period_id": str(period_with_reports.id)},
            content_type="application/json",
        )
        meeting_id = create_resp.json()["id"]

        # 开始
        start_resp = admin_client.post(f"/api/v1/admin/meetings/{meeting_id}/start")
        assert start_resp.status_code == 200
        assert start_resp.json()["status"] == "in_progress"

        # 结束
        finish_resp = admin_client.post(
            f"/api/v1/admin/meetings/{meeting_id}/finish",
            {"notes": "本次组会顺利"},
            content_type="application/json",
        )
        assert finish_resp.status_code == 200
        assert finish_resp.json()["status"] == "finished"

    def test_mark_discussed(self, admin_client, period_with_reports):
        """标记成员已讨论。"""
        create_resp = admin_client.post(
            "/api/v1/admin/meetings/",
            {"reporting_period_id": str(period_with_reports.id)},
            content_type="application/json",
        )
        meeting_id = create_resp.json()["id"]
        snapshot_id = create_resp.json()["snapshots"][0]["id"]

        resp = admin_client.patch(
            f"/api/v1/admin/meetings/{meeting_id}/reports/{snapshot_id}",
            {"discussed": True, "note": "进展正常"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["discussed"] is True

    def test_action_item_crud(self, admin_client, period_with_reports):
        """行动项创建和更新。"""
        create_resp = admin_client.post(
            "/api/v1/admin/meetings/",
            {"reporting_period_id": str(period_with_reports.id)},
            content_type="application/json",
        )
        meeting_id = create_resp.json()["id"]

        # 创建行动项
        item_resp = admin_client.post(
            f"/api/v1/admin/meetings/{meeting_id}/action-items",
            {"title": "张三需要在周五前完成性能测试"},
            content_type="application/json",
        )
        assert item_resp.status_code == 201
        item_id = item_resp.json()["id"]
        assert item_resp.json()["status"] == "open"

        # 更新行动项
        update_resp = admin_client.patch(
            f"/api/v1/admin/action-items/{item_id}",
            {"status": "done", "resolution_note": "已完成"},
            content_type="application/json",
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["status"] == "done"
