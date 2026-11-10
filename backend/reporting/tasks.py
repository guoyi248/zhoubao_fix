import logging
from datetime import timedelta
from smtplib import SMTPException

from celery import shared_task
from django.core.mail import EmailMessage, get_connection
from django.db import transaction
from django.utils import timezone

from .models import PeriodStatus, WeeklyReminder
from system_config.credentials import CredentialUnavailable
from system_config.integrations import get_config, mail_issues
from .periods import current_period, missing_members
from .reminders import scheduled_time, reminder_message

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def send_weekly_reminders():
    try:
        config = get_config("mail", credentials=True)
    except CredentialUnavailable as exc:
        logger.warning("%s", exc)
        return 0
    if not config["enabled"]:
        return 0
    issues = mail_issues(config)
    if issues:
        logger.warning("Weekly reminder settings need attention: %s", ", ".join(issues))
        return 0
    now = timezone.localtime()
    start = now.date() - timedelta(days=now.weekday())
    if now < scheduled_time(start, config):
        return 0
    period = current_period(now.date())
    if now >= period.deadline or period.status != PeriodStatus.OPEN:
        return 0
    eligible = missing_members(period).exclude(email="")
    recipients = eligible.exclude(pk__in=WeeklyReminder.objects.filter(
        period=period, sent_at__isnull=False
    ).values("user_id")).values_list("pk", flat=True)
    connection = get_connection(host=config["host"], port=config["port"], username=config["username"],
                                password=config["password"], use_tls=config["use_tls"], use_ssl=config["use_ssl"])
    sent = 0
    for user_id in list(recipients):
        try:
            with transaction.atomic():
                receipt, _ = WeeklyReminder.objects.select_for_update().get_or_create(period=period, user_id=user_id)
                member = eligible.filter(pk=user_id).first()
                if receipt.sent_at or not member or timezone.now() >= period.deadline:
                    continue
                subject, body = reminder_message(period, member.display_name, config["site_url"])
                message = EmailMessage(
                    subject, body, config["from_email"], [member.email], connection=connection,
                    headers={"Message-ID": f"<weekly-{period.pk}-{user_id}@weekly-report.local>"},
                )
                if message.send(fail_silently=False) != 1:
                    raise SMTPException("SMTP did not accept the message")
                receipt.sent_at = timezone.now()
                receipt.save(update_fields=["sent_at"])
                sent += 1
        except (SMTPException, OSError, ValueError):
            logger.warning("Weekly reminder delivery failed for user %s in period %s", user_id, period.pk)
    return sent
