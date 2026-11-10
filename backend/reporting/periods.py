from datetime import datetime, time, timedelta

from django.utils import timezone

from accounts.models import User
from .models import ReportingPeriod, WeeklyReport


def current_period(today=None):
    today = today or timezone.localdate()
    year, week, weekday = today.isocalendar()
    start = today - timedelta(days=weekday - 1)
    end = start + timedelta(days=6)
    period, _ = ReportingPeriod.objects.get_or_create(
        iso_year=year, iso_week=week,
        defaults={"start_date": start, "end_date": end,
                  "deadline": timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min))},
    )
    return period


def missing_members(period):
    submitted = WeeklyReport.objects.filter(reporting_period=period, current_revision__isnull=False)
    return User.objects.active().exclude(pk__in=submitted.values("owner_id")).order_by("display_name", "pk")
