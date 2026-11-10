from datetime import time
from email import policy
from email.parser import BytesParser
from socketserver import StreamRequestHandler, TCPServer
from threading import Thread
from smtplib import SMTPException
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.mail import EmailMessage
from freezegun import freeze_time

from accounts.models import User
from reporting.models import WeeklyReminder, WeeklyReport
from reporting.periods import current_period
from reporting.tasks import send_weekly_reminders

pytestmark = pytest.mark.django_db


def account(name, **overrides):
    fields = dict(display_name=name, email=f"{name}@example.test", account_status="active")
    return User.objects.create_user(username=name, **{**fields, **overrides})


@pytest.fixture(autouse=True)
def reminder_settings(settings):
    settings.WEEKLY_REMINDERS_ENABLED = True
    settings.WEEKLY_SITE_URL = "https://weekly.example.test"
    settings.EMAIL_HOST = "smtp.example.test"
    settings.DEFAULT_FROM_EMAIL = "reports@example.test"
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.REMINDER_WEEKDAY = 7
    settings.REMINDER_TIME = time(18)


def test_weekend_roster_deduplicates_and_skips_published_versions(client):
    with freeze_time("2026-11-08 09:59:00Z"):
        period = current_period()
        missing = account("missing")
        draft = account("draft")
        WeeklyReport.objects.create(owner=draft, reporting_period=period)
        account("invited", account_status="invited")
        account("disabled", is_active=False)
        account("no-email", email="")
        admin = account("host", role="admin")
        submitted = WeeklyReport.objects.create(owner=admin, reporting_period=period)
        submitted.submit(admin)
        submitted.status = "resubmitted"
        submitted.save(update_fields=["status"])
        assert send_weekly_reminders() == 0
    with freeze_time("2026-11-08 10:00:00Z"):
        assert send_weekly_reminders() == 2
        assert send_weekly_reminders() == 0
        assert WeeklyReminder.objects.filter(sent_at__isnull=False).count() == 2
        assert {message.to[0] for message in mail.outbox} == {missing.email, draft.email}
        assert all(len(message.to) == 1 and "https://weekly.example.test/reports/current" in message.body for message in mail.outbox)
        client.force_login(admin)
        data = client.get("/api/v1/admin/reports/overview").json()
        assert {m["name"] for m in data["missing"]} == {"missing", "draft", "no-email"}
        assert [r["owner_name"] for r in data["submitted"]] == ["host"]
    with freeze_time("2026-11-08 16:00:00Z"):
        assert send_weekly_reminders() == 0


@freeze_time("2026-11-08 10:01:00Z")
def test_reminder_center_separates_personal_email_from_team_receipts(client, settings):
    settings.EMAIL_HOST_PASSWORD = "never-return-smtp-password"
    member = account("recipient", email="")
    chair = account("chair", role="admin")
    WeeklyReport.objects.create(owner=chair, reporting_period=current_period()).submit(chair)
    endpoint = "/api/v1/me/reports/reminders"
    client.force_login(member)
    assert client.patch(endpoint, {"email": "bad"}, content_type="application/json").status_code == 400
    data = client.patch(endpoint, {"email": "new@example.test"}, content_type="application/json").json()
    assert data["email"] == "new@example.test" and data["submitted"] is False
    assert "team" not in data and "setup" not in data
    assert send_weekly_reminders() == 1
    assert mail.outbox[0].to == ["new@example.test"]
    assert client.get(endpoint).json()["sent_at"]
    client.force_login(chair)
    response = client.get(endpoint)
    assert b"never-return-smtp-password" not in response.content
    data = response.json()
    assert data["configured"] and data["weekday"] == 7 and data["time"] == "18:00"
    assert data["submitted"] and [r["name"] for r in data["team"]["sent"]] == ["recipient"]
    assert data["team"]["missing"][0]["sent_at"] == data["team"]["sent"][0]["sent_at"]
    settings.EMAIL_USE_SSL = True
    assert not client.get(endpoint).json()["configured"]


@freeze_time("2026-11-08 12:00Z")
def test_delivery_retry_rechecks_submission(settings):
    submitted_after_error = account("late")
    pending = account("pending")
    with patch.object(EmailMessage, "send", side_effect=SMTPException("busy")):
        assert send_weekly_reminders() == 0
    WeeklyReport.objects.create(owner=submitted_after_error, reporting_period=current_period()).submit(submitted_after_error)
    settings.WEEKLY_REMINDERS_ENABLED = False
    assert send_weekly_reminders() == 0
    settings.WEEKLY_REMINDERS_ENABLED = True
    assert send_weekly_reminders() == 1
    assert mail.outbox[0].to == [pending.email]
    assert send_weekly_reminders() == 0



@freeze_time("2026-11-08 10:03:00Z")
def test_smtp_transport_delivers_a_private_link(settings):
    messages = []

    class Receiver(StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 local test SMTP\r\n")
            while line := self.rfile.readline():
                command = line.split()[0].upper()
                if command == b"DATA":
                    self.wfile.write(b"354 send message\r\n")
                    body = []
                    for part in self.rfile:
                        if part == b".\r\n":
                            break
                        body.append(part)
                    messages.append(BytesParser(policy=policy.default).parsebytes(b"".join(body)))
                elif command == b"QUIT":
                    self.wfile.write(b"221 goodbye\r\n")
                    return
                self.wfile.write(b"250 OK\r\n")

    account("local")
    with TCPServer(("127.0.0.1", 0), Receiver) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
            settings.EMAIL_HOST, settings.EMAIL_PORT = server.server_address
            settings.EMAIL_USE_TLS = False
            settings.EMAIL_USE_SSL = False
            settings.EMAIL_HOST_USER = ""
            assert send_weekly_reminders() == 1
            assert send_weekly_reminders() == 0
        finally:
            server.shutdown()
            worker.join()
    assert len(messages) == 1
    assert messages[0]["To"] == "local@example.test"
    assert "https://weekly.example.test/reports/current" in messages[0].get_content()
