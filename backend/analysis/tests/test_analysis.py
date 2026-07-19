"""
AI 分析模块测试。
测试：LLM Schema 校验、分析结果存储、人工修订、权限隔离。
"""

import pytest
from unittest.mock import patch, MagicMock
from django.test import Client

from accounts.models import User, UserRole, AccountStatus
from organizations.models import Department
from reporting.models import (
    ReportingPeriod, WeeklyReport, WeeklyReportRevision,
    ReportStatus,
)
from analysis.models import AnalysisRun, AnalysisItem
from analysis.llm_client import llm_client, LLMClient


pytestmark = pytest.mark.django_db


# ── 模拟 LLM 输出 ────────────────────────────────────────

MOCK_LLM_RESPONSE = {
    "output": {
        "summary": "本周完成了接口改造和线上问题修复，整体进度正常。",
        "achievements": [
            {
                "title": "完成接口改造",
                "detail": "完成用户模块接口重构，已通过测试",
                "project": "用户系统",
                "confidence": 0.95,
                "sources": [
                    {"source_type": "report_field", "source_id": "completed", "page": 1, "quote_hash": "abc"}
                ],
            }
        ],
        "risks": [
            {
                "title": "第三方接口不稳定",
                "detail": "依赖的支付接口最近有超时现象",
                "severity": "high",
                "confidence": 0.85,
                "sources": [],
            }
        ],
        "blockers": [],
        "coordination_requests": [],
        "next_week_plans": [
            {
                "title": "性能优化",
                "detail": "数据库查询优化和缓存引入",
                "project": "用户系统",
                "priority": "high",
                "confidence": 0.9,
                "sources": [],
            }
        ],
        "meeting_topics": [],
    },
    "model": "test-model",
    "tokens_used": 500,
}


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
def submitted_revision(member):
    """创建一份已提交的周报修订版。"""
    from datetime import date, timedelta

    period = ReportingPeriod.objects.create(
        iso_year=2026,
        iso_week=30,
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 26),
        deadline="2026-07-27T00:00:00Z",
    )
    report = WeeklyReport.objects.create(
        owner=member,
        reporting_period=period,
        status=ReportStatus.SUBMITTED,
        draft_content_json={
            "completed": ["完成接口改造", "修复线上问题"],
            "risks": ["第三方接口不稳定"],
            "next_week": ["性能优化"],
        },
    )
    revision = WeeklyReportRevision.objects.create(
        report=report,
        revision_no=1,
        structured_content_json=report.draft_content_json,
        submitted_by=member,
        content_sha256="test_sha256",
    )
    report.current_revision = revision
    report.save(update_fields=["current_revision"])
    return revision


class TestLLMClient:
    """LLM Client 单元测试。"""

    def test_schema_validation_fills_missing_fields(self):
        """缺失字段自动填充。"""
        client = LLMClient()
        data = {"summary": "test"}
        client._validate(data)
        assert "achievements" in data
        assert "risks" in data
        assert data["achievements"] == []

    def test_mock_llm_response(self):
        """模拟 LLM 返回正确结构。"""
        result = llm_client._validate(MOCK_LLM_RESPONSE["output"])
        # 不应抛出异常
        assert MOCK_LLM_RESPONSE["output"]["summary"]


class TestAnalysisAPI:
    """分析 API 测试。"""

    def test_view_analysis(self, submitted_revision, member, settings):
        """成员查看自己周报的分析。"""
        from analysis.tasks import analyze_report
        settings.LLM_ENABLED = True
        with patch.object(llm_client, "analyze_report", return_value=MOCK_LLM_RESPONSE):
            analyze_report(str(submitted_revision.id))

        client = Client()
        client.post(
            "/api/v1/auth/login",
            {"username": "zhangsan", "password": "Test1234!"},
            content_type="application/json",
        )

        resp = client.get(f"/api/v1/reports/{submitted_revision.id}/analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data or "detail" in data

    def test_cannot_view_others_analysis(self, submitted_revision, member, department):
        """成员不能查看他人分析。"""
        other = User.objects.create_user(
            username="lisi",
            password="Test1234!",
            display_name="李四",
            role=UserRole.MEMBER,
            account_status=AccountStatus.ACTIVE,
            department=department,
        )
        client = Client()
        client.post(
            "/api/v1/auth/login",
            {"username": "lisi", "password": "Test1234!"},
            content_type="application/json",
        )

        resp = client.get(f"/api/v1/reports/{submitted_revision.id}/analysis")
        assert resp.status_code == 403

    def test_confirm_analysis_item(self, submitted_revision, member, settings):
        """成员确认 AI 分析条目。"""
        from analysis.tasks import analyze_report
        settings.LLM_ENABLED = True
        with patch.object(llm_client, "analyze_report", return_value=MOCK_LLM_RESPONSE):
            analyze_report(str(submitted_revision.id))

        item = AnalysisItem.objects.first()

        client = Client()
        client.post(
            "/api/v1/auth/login",
            {"username": "zhangsan", "password": "Test1234!"},
            content_type="application/json",
        )

        resp = client.post(f"/api/v1/analysis/items/{item.id}/confirm")
        assert resp.status_code == 200
        item.refresh_from_db()
        assert item.human_status == "confirmed"

    def test_reject_analysis_item(self, submitted_revision, member, settings):
        """成员拒绝 AI 分析条目。"""
        from analysis.tasks import analyze_report
        settings.LLM_ENABLED = True
        with patch.object(llm_client, "analyze_report", return_value=MOCK_LLM_RESPONSE):
            analyze_report(str(submitted_revision.id))

        item = AnalysisItem.objects.first()

        client = Client()
        client.post(
            "/api/v1/auth/login",
            {"username": "zhangsan", "password": "Test1234!"},
            content_type="application/json",
        )

        resp = client.post(f"/api/v1/analysis/items/{item.id}/reject")
        assert resp.status_code == 200
        item.refresh_from_db()
        assert item.human_status == "rejected"
