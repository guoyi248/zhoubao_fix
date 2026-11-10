"""
账号认证与权限集成测试。
"""

import pytest
from django.test import Client
from accounts.models import User, UserRole, AccountStatus
from organizations.models import Department


pytestmark = pytest.mark.django_db


@pytest.fixture
def department():
    return Department.objects.create(name="技术部", code="tech")


@pytest.fixture
def admin_user(department):
    user = User.objects.create_user(
        username="admin",
        password="Admin123!",
        display_name="管理员",
        role=UserRole.ADMIN,
        account_status=AccountStatus.ACTIVE,
        department=department,
    )
    return user


@pytest.fixture
def member_user(department):
    return User.objects.create_user(
        username="zhangsan",
        password="Test1234!",
        display_name="张三",
        role=UserRole.MEMBER,
        account_status=AccountStatus.ACTIVE,
        department=department,
    )


@pytest.fixture
def member_b(department):
    return User.objects.create_user(
        username="lisi",
        password="Test1234!",
        display_name="李四",
        role=UserRole.MEMBER,
        account_status=AccountStatus.ACTIVE,
        department=department,
    )


@pytest.fixture
def api_client():
    return Client()


class TestAuthentication:
    """登录认证测试。"""

    def test_login_requires_csrf_from_browser(self, member_user):
        browser = Client(enforce_csrf_checks=True)
        credentials = {"username": member_user.username, "password": "Test1234!"}
        url = "/api/v1/auth/login"
        assert browser.post(url, credentials, content_type="application/json").status_code == 403
        browser.get("/api/v1/auth/csrf")
        response = browser.post(url, credentials, content_type="application/json",
                                HTTP_X_CSRFTOKEN=browser.cookies["csrftoken"].value)
        assert response.status_code == 200

    def test_invitation_activates_with_chosen_password(self, api_client, admin_user):
        api_client.force_login(admin_user)
        invite = api_client.post("/api/v1/admin/users/create", {
            "username": "invited", "display_name": "新成员",
        }, content_type="application/json")
        assert invite.status_code == 201
        api_client.logout()
        activation = {"token": invite.json()["activation_token"], "password": "Chosen123!"}
        assert api_client.post("/api/v1/auth/activate", activation, content_type="application/json").status_code == 200
        assert api_client.post("/api/v1/auth/activate", activation, content_type="application/json").status_code == 404
        response = api_client.post("/api/v1/auth/login", {
            "username": "invited", "password": activation["password"],
        }, content_type="application/json")
        assert response.status_code == 200

    def test_totp_requires_a_valid_unused_code(self, api_client, member_user):
        from django_otp.oath import totp
        from django_otp.plugins.otp_totp.models import TOTPDevice
        from audit.models import AuditEvent

        device = TOTPDevice.objects.create(user=member_user, name="手机")
        member_user.totp_enabled = True
        member_user.save()
        credentials = {"username": member_user.username, "password": "Test1234!"}
        login_url = "/api/v1/auth/login"
        for code in ["", "abcdef"]:
            response = api_client.post(login_url, {**credentials, "totp_code": code}, content_type="application/json")
            assert response.status_code == 401
            assert api_client.get("/api/v1/me/").status_code == 403
        assert not AuditEvent.objects.filter(event_type="LOGIN_SUCCESS").exists()
        credentials["totp_code"] = f"{totp(device.bin_key):06d}"
        assert api_client.post(login_url, credentials, content_type="application/json").status_code == 200
        api_client.logout()
        assert api_client.post(login_url, credentials, content_type="application/json").status_code == 401

    def test_login_success(self, api_client, member_user):
        response = api_client.post(
            "/api/v1/auth/login",
            {"username": "zhangsan", "password": "Test1234!"},
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["username"] == "zhangsan"
        assert response.json()["role"] == "member"

    def test_login_wrong_password(self, api_client, member_user):
        response = api_client.post(
            "/api/v1/auth/login",
            {"username": "zhangsan", "password": "wrong"},
            content_type="application/json",
        )
        assert response.status_code == 401
        assert response.json()["code"] == "INVALID_CREDENTIALS"

    def test_login_disabled_account(self, api_client, member_user, department):
        disabled = User.objects.create_user(
            username="disabled_user",
            password="Test1234!",
            display_name="禁用用户",
            account_status=AccountStatus.DISABLED,
            department=department,
        )
        response = api_client.post(
            "/api/v1/auth/login",
            {"username": "disabled_user", "password": "Test1234!"},
            content_type="application/json",
        )
        assert response.status_code == 403
        assert response.json()["code"] == "ACCOUNT_DISABLED"

    def test_login_then_get_me(self, api_client, member_user):
        api_client.post(
            "/api/v1/auth/login",
            {"username": "zhangsan", "password": "Test1234!"},
            content_type="application/json",
        )
        response = api_client.get("/api/v1/me/")
        assert response.status_code == 200
        assert response.json()["username"] == "zhangsan"

    def test_unauthenticated_access(self, api_client):
        response = api_client.get("/api/v1/me/")
        assert response.status_code == 403


class TestPermissionIsolation:
    """权限隔离测试。"""

    def test_two_roles_manage_accounts_and_preserve_deleted_history(self, api_client, admin_user, member_user):
        from audit.models import AuditEvent
        from reporting.models import WeeklyReportRevision

        api_client.force_login(member_user)
        users = "/api/v1/admin/users"
        target = f"{users}/{member_user.pk}"
        own = f"{users}/{admin_user.pk}"
        json_type = {"content_type": "application/json"}
        assert api_client.get(users).status_code == 403
        assert api_client.get("/api/v1/admin/audit/").status_code == 403
        assert api_client.post(users + "/create", {"username": "peer", "display_name": "管理员", "role": "admin"}, **json_type).status_code == 403
        assert api_client.patch(target, {"role": "admin"}, **json_type).status_code == 403
        assert api_client.delete(own + "/delete").status_code == 403
        report_id = api_client.get("/api/v1/me/reports/current").json()["id"]
        assert api_client.post(f"/api/v1/me/reports/{report_id}/submit", {}, **json_type).status_code == 201

        api_client.force_login(admin_user)
        invite = api_client.post(users + "/create", {"username": "peer", "display_name": "管理员", "role": "admin"}, **json_type)
        assert invite.status_code == 201
        assert api_client.patch(target, {"role": "admin", "display_name": "张工", "email": "member@example.test"}, **json_type).status_code == 200
        assert api_client.patch(own, {"role": "member"}, **json_type).status_code == 403
        assert api_client.post(own + "/disable").status_code == 403
        assert api_client.delete(own + "/delete").status_code == 403
        assert api_client.delete(target + "/delete").status_code == 200
        assert not any(row["id"] == member_user.pk for row in api_client.get(users).json())
        assert api_client.post(target + "/enable").status_code == 404
        assert api_client.post(target + "/reset-password", {"new_password": "Another234!"}, **json_type).status_code == 404
        assert WeeklyReportRevision.objects.filter(report_id=report_id, submitted_by=member_user).exists()
        assert AuditEvent.objects.filter(event_type="USER_DELETED", target_id=str(member_user.pk)).exists()
        rows = api_client.get("/api/v1/admin/audit/", {"group":"report", "actor_id": member_user.pk}).json()
        assert rows["count"] == 1 and rows["events"][0]["actor_name"] == "张工"

    def test_login_location_and_admin_visibility(self, api_client, admin_user, member_user, settings):
        from audit.models import AuditEvent

        settings.AUDIT_TRUSTED_PROXIES = "10.0.0.1/32"
        settings.AUDIT_LOCATION_NETWORKS = "10.3.0.0/16=园区,10.3.2.0/24=南京实验室"
        login_url = "/api/v1/auth/login"
        payload = {"username": member_user.username, "password": "Test1234!"}
        attempts = [
            ("127.0.0.1", "10.3.2.9", "127.0.0.1", "本机回环"),
            ("10.0.0.1", "10.3.2.9", "10.3.2.9", "南京实验室"),
            ("10.0.0.1", "bad-header", None, "来源未知"),
        ]
        for peer, header, expected_ip, expected_location in attempts:
            response = api_client.post(login_url, payload, content_type="application/json",
                                       REMOTE_ADDR=peer, HTTP_X_REAL_IP=header)
            assert response.status_code == 200
            event = AuditEvent.objects.filter(event_type="LOGIN_SUCCESS").first()
            assert (event.actor_ip, event.actor_location) == (expected_ip, expected_location)
            assert "last_login_ip" not in response.json()
        api_client.force_login(admin_user)
        users = api_client.get("/api/v1/admin/users", {"q": member_user.username, "page": 1}).json()
        assert users["total"] == 1 and users["users"][0]["last_login_at"]
        assert users["users"][0]["last_login_location"] == "来源未知"
        assert api_client.get("/api/v1/admin/audit/", {"days": "nan"}).status_code == 400

    def test_disabled_sessions_stay_revoked_on_reactivation(self, api_client, admin_user, member_user):
        browser = Client()
        browser.force_login(member_user)
        api_client.force_login(admin_user)
        url = f"/api/v1/admin/users/{member_user.pk}"
        assert api_client.post(url + "/disable").status_code == 200
        assert api_client.post(url + "/enable").status_code == 200
        assert browser.get("/api/v1/me/").status_code == 403

    def test_role_change_applies_to_an_open_session(self, api_client, admin_user, member_user):
        browser = Client()
        browser.force_login(member_user)
        api_client.force_login(admin_user)
        url = f"/api/v1/admin/users/{member_user.pk}"
        protected = ["/api/v1/admin/meetings/list", "/api/v1/admin/users", "/api/v1/admin/audit/"]
        for role, status_code in [("admin", 200), ("member", 403)]:
            assert api_client.patch(url, {"role": role}, content_type="application/json").status_code == 200
            for path in protected:
                assert browser.get(path).status_code == status_code
        assert api_client.patch(url, {"role": "super_admin"}, content_type="application/json").status_code == 400

    def test_legacy_log_keeps_its_ip_and_time_without_guessing_location(self, api_client, admin_user, member_user):
        from audit.models import AuditEvent

        event = AuditEvent.objects.create(actor=member_user, actor_ip="192.168.1.9", event_type="LOGIN_SUCCESS")
        api_client.force_login(admin_user)
        entry = api_client.get("/api/v1/admin/audit/", {"actor_id": member_user.pk}).json()["events"][0]
        assert entry["actor_ip"] == "192.168.1.9" and entry["actor_location"] == "未记录地点"
        row = api_client.get("/api/v1/admin/users", {"q": member_user.username, "page":1}).json()["users"][0]
        from datetime import datetime
        assert datetime.fromisoformat(row["last_login_at"]) == event.created_at
        assert row["last_login_ip"] == entry["actor_ip"]

    def test_member_a_cannot_access_member_b_report(self, api_client, member_user, member_b):
        # 成员 B 登录，创建并提交周报
        api_client.post(
            "/api/v1/auth/login",
            {"username": "lisi", "password": "Test1234!"},
            content_type="application/json",
        )
        current = api_client.get("/api/v1/me/reports/current")
        report = current.json()
        report_id = report["id"]

        api_client.post(
            f"/api/v1/me/reports/{report_id}/submit",
            {},
            content_type="application/json",
        )

        # 登出
        api_client.post("/api/v1/auth/logout")

        # 成员 A 登录，尝试访问成员 B 的周报
        api_client.post(
            "/api/v1/auth/login",
            {"username": "zhangsan", "password": "Test1234!"},
            content_type="application/json",
        )

        response = api_client.get(f"/api/v1/me/reports/{report_id}")
        assert response.status_code == 404  # 404 而非 403，不暴露资源存在

    def test_member_cannot_access_admin_endpoint(self, api_client, member_user):
        api_client.post(
            "/api/v1/auth/login",
            {"username": "zhangsan", "password": "Test1234!"},
            content_type="application/json",
        )
        response = api_client.get("/api/v1/admin/reports/")
        assert response.status_code == 403

    def test_admin_cannot_access_draft(self, api_client, member_user, admin_user):
        # 成员创建草稿
        api_client.post(
            "/api/v1/auth/login",
            {"username": "zhangsan", "password": "Test1234!"},
            content_type="application/json",
        )
        current = api_client.get("/api/v1/me/reports/current")
        report_id = current.json()["id"]
        api_client.post("/api/v1/auth/logout")

        # 管理员尝试访问草稿
        api_client.post(
            "/api/v1/auth/login",
            {"username": "admin", "password": "Admin123!"},
            content_type="application/json",
        )
        response = api_client.get(f"/api/v1/admin/reports/{report_id}")
        assert response.status_code == 403


class TestReportLifecycle:
    """周报生命周期测试。"""

    def test_current_week_uses_local_monday(self, api_client, member_user):
        from datetime import datetime, timezone
        from unittest.mock import patch

        api_client.force_login(member_user)
        with patch("django.utils.timezone.now", return_value=datetime(2025, 12, 28, 16, 5, tzinfo=timezone.utc)):
            period = api_client.get("/api/v1/me/reports/current").json()["period"]
        assert (period["iso_year"], period["iso_week"]) == (2026, 1)
        assert datetime.fromisoformat(period["deadline"]) == datetime(2026, 1, 4, 16, tzinfo=timezone.utc)

    def test_stale_report_instance_cannot_override_concurrent_save(self, api_client, member_user):
        from common.exceptions import VersionConflictError
        from reporting.models import WeeklyReport

        api_client.force_login(member_user)
        pk = api_client.get("/api/v1/me/reports/current").json()["id"]
        first, stale = WeeklyReport.objects.get(pk=pk), WeeklyReport.objects.get(pk=pk)
        first.save_draft({"text": "first"}, 0)
        with pytest.raises(VersionConflictError):
            stale.save_draft({"text": "overwritten"}, 0)
        assert WeeklyReport.objects.get(pk=pk).draft_content_json == {"text": "first"}

    def test_create_draft_and_submit(self, api_client, member_user):
        api_client.post(
            "/api/v1/auth/login",
            {"username": "zhangsan", "password": "Test1234!"},
            content_type="application/json",
        )

        # 获取当前周报（自动创建草稿）
        current = api_client.get("/api/v1/me/reports/current")
        assert current.status_code == 200
        report = current.json()
        assert report["status"] == "draft"

        # 提交
        submit = api_client.post(
            f"/api/v1/me/reports/{report['id']}/submit",
            {},
            content_type="application/json",
        )
        assert submit.status_code == 201
        assert submit.json()["revision_no"] == 1

        # 再次获取——status 应为 submitted
        current2 = api_client.get("/api/v1/me/reports/current")
        assert current2.json()["status"] == "submitted"

    def test_optimistic_lock_conflict(self, api_client, member_user):
        api_client.post(
            "/api/v1/auth/login",
            {"username": "zhangsan", "password": "Test1234!"},
            content_type="application/json",
        )
        current = api_client.get("/api/v1/me/reports/current")
        report = current.json()

        # 第一次保存成功
        r1 = api_client.patch(
            f"/api/v1/me/reports/{report['id']}/save",
            {"content": {"a": 1}, "version": 0},
            content_type="application/json",
        )
        assert r1.status_code == 200

        # 第二次用过期 version 保存——冲突
        r2 = api_client.patch(
            f"/api/v1/me/reports/{report['id']}/save",
            {"content": {"b": 2}, "version": 0},  # 版本应该为 1
            content_type="application/json",
        )
        assert r2.status_code == 409
        assert r2.json()["code"] == "REPORT_VERSION_CONFLICT"
