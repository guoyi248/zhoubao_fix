import getpass
import sys
import warnings

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from system_config.credentials import seal
from system_config.integrations import defaults, destination, http_address


class Command(BaseCommand):
    help = "为部署环境生成 LLM_API_KEY_ENCRYPTED。默认在终端隐藏输入，也可用 --from-env 读取现有 LLM_API_KEY。"
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--from-env", action="store_true", help="加密当前部署配置中的 LLM_API_KEY")

    def create_parser(self, *args, **kwargs):
        parser = super().create_parser(*args, **kwargs)
        # argparse normally echoes unrecognized arguments, including accidentally pasted keys.
        report_error = parser.error
        parser.error = lambda _message: report_error("参数无效。请在终端提示中输入密钥，或使用 --from-env。")
        return parser

    def handle(self, *args, **options):
        model = defaults("model")
        if model["provider"] not in {"ollama", "openai_compatible"}:
            raise CommandError("请先将 LLM_PROVIDER 设为 openai_compatible 或 ollama。")
        if not http_address(model["base_url"]):
            raise CommandError("请先配置有效的 LLM_BASE_URL。")

        if options["from_env"]:
            value = settings.LLM_API_KEY
            if not value.strip():
                raise CommandError("当前部署尚未设置 LLM_API_KEY。请去掉 --from-env，在终端提示中输入密钥。")
        else:
            if not sys.stdin or not sys.stdin.isatty():
                raise CommandError("手动输入密钥需要交互终端。如已设置 LLM_API_KEY，可使用 --from-env。")
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", getpass.GetPassWarning)
                    value = getpass.getpass("模型 API 密钥（输入时隐藏）：")
            except (getpass.GetPassWarning, EOFError, OSError, KeyboardInterrupt):
                raise CommandError("未能安全读取密钥。请在交互终端重试，或使用 --from-env。") from None
            if not value.strip():
                raise CommandError("模型 API 密钥不能为空。")

        try:
            token = seal(value, section="model", destination=destination("model", model))
        except ImproperlyConfigured as error:
            raise CommandError(str(error)) from None
        self.stdout.write(f"LLM_API_KEY_ENCRYPTED={token}")
