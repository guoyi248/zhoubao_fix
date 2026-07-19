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
        role=UserRole.SUPER_ADMIN,
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
