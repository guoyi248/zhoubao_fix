import re
from rest_framework import serializers

from .integrations import http_address


class ServiceAddress(serializers.CharField):
    def to_internal_value(self, data):
        value = super().to_internal_value(data).rstrip("/")
        if value and not http_address(value):
            raise serializers.ValidationError("请输入 HTTP(S) 网址，地址中不能包含凭据、查询参数或片段。")
        return value


class ModelFields(serializers.Serializer):
    enabled = serializers.BooleanField()
    provider = serializers.ChoiceField(choices=("openai_compatible", "ollama"))
    base_url = ServiceAddress(max_length=600, allow_blank=True)
    model = serializers.CharField(max_length=180, allow_blank=True)
    api_key = serializers.CharField(max_length=4096, allow_blank=True, trim_whitespace=False, write_only=True)


class MailFields(serializers.Serializer):
    enabled = serializers.BooleanField()
    weekday = serializers.IntegerField(min_value=1, max_value=7)
    time = serializers.RegexField(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    site_url = ServiceAddress(max_length=600, allow_blank=True)
    host = serializers.CharField(max_length=253, allow_blank=True)
    port = serializers.IntegerField(min_value=1, max_value=65535)
    username = serializers.CharField(max_length=320, allow_blank=True)
    password = serializers.CharField(max_length=4096, allow_blank=True, trim_whitespace=False, write_only=True)
    from_email = serializers.EmailField(allow_blank=True, max_length=320)
    use_tls = serializers.BooleanField()
    use_ssl = serializers.BooleanField()

    def validate_host(self, host):
        if host and not re.fullmatch(r"[a-zA-Z0-9:.\-]+", host):
            raise serializers.ValidationError("请输入 SMTP 主机名或 IP 地址。")
        return host
