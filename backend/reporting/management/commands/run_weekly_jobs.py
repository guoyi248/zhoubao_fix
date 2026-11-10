import logging
import time
from concurrent.futures import ThreadPoolExecutor

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from analysis.tasks import dispatch_pending
from reporting.tasks import send_weekly_reminders

logger = logging.getLogger(__name__)


def run_analysis_batch():
    close_old_connections()
    try:
        dispatch_pending()
    finally:
        close_old_connections()


class Command(BaseCommand):
    help = "运行单机周报提醒和已提交周报的解析队列，--watch 持续运行"

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true")

    def handle(self, *args, **options):
        if not options["watch"]:
            sent = send_weekly_reminders()
            dispatch_pending()
            self.stdout.write(f"已发送 {sent} 封提醒，已检查进展总结队列。")
            return

        # 本地模型可能较慢，邮件检查独立运行。
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = None
            while True:
                close_old_connections()
                try:
                    if pending is None or pending.done():
                        if pending is not None:
                            pending.result()
                        pending = executor.submit(run_analysis_batch)
                except Exception:
                    logger.exception("Weekly analysis dispatcher interrupted")
                    pending = None
                try:
                    send_weekly_reminders()
                except Exception:
                    logger.exception("Weekly reminder check interrupted")
                time.sleep(30)
