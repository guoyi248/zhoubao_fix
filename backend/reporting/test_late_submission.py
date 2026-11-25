from datetime import timedelta

import pytest
import fitz
from django.core.files.uploadedfile import SimpleUploadedFile
from freezegun import freeze_time

from accounts.models import User
from reporting.models import WeeklyReport
from reporting.periods import current_period


pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("local_files")]


@pytest.mark.parametrize("today", ["2026-11-16 02:00:00Z", "2027-01-04 02:00:00Z"])
def test_previous_week_without_existing_draft_can_be_submitted(client, today):
    with freeze_time(today):
        user = User.objects.create_user("late", display_name="补交成员", account_status="active")
        client.force_login(user)
        current = current_period()
        previous = current_period(current.start_date - timedelta(days=7))
        previous.status = "closed"
        previous.save()
        response = client.get("/api/v1/me/reports/current?week=previous")
        assert response.status_code == 200
        report = response.json()
        assert report["reporting_period_id"] == str(previous.pk)
        path = "/api/v1/me/reports/" + report["id"]
        with fitz.open() as pdf:
            pdf.new_page().insert_text((30, 50), "Last week's results")
            uploaded = client.post(path + "/attachments", {"file": SimpleUploadedFile("late.pdf", pdf.tobytes(), content_type="application/pdf")})
        assert uploaded.status_code == 201
        saved = client.patch(path + "/save", {"content": {"progress": "上周完成实验"}, "version": 0}, content_type="application/json")
        assert saved.status_code == 200
        assert client.post(path + "/submit", {}, content_type="application/json").status_code == 201
        row = WeeklyReport.objects.get(pk=report["id"])
        assert row.reporting_period_id == previous.pk and row.current_revision_id
        assert row.current_revision.submitted_at > previous.deadline
        assert row.current_revision.confirmed_pdf_attachment_id
        assert not WeeklyReport.objects.filter(owner=user, reporting_period=current).exists()
        assert client.post(path + "/submit", {}, content_type="application/json").status_code == 409
