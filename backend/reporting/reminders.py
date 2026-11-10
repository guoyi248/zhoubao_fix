from datetime import datetime, time, timedelta

from django.utils import timezone


def scheduled_time(week_start, config):
    day = week_start + timedelta(days=config["weekday"] - 1)
    return timezone.make_aware(datetime.combine(day, time.fromisoformat(config["time"])))


def reminder_message(period, name, site_url):
    deadline = timezone.localtime(period.deadline).strftime("%m 月 %d 日 %H:%M")
    link = site_url.rstrip("/") + "/reports/current"
    return (
        f"周报提醒 · {period.iso_year} 年第 {period.iso_week} 周",
        f"{name}，你好！\n\n你本周的周报仍待提交，请在 {deadline} 前完成。\n提交周报：{link}\n",
    )
