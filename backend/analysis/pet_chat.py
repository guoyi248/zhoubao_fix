"""Stateless conversations using the same model service as weekly reports."""
import requests
from rest_framework.decorators import api_view
from rest_framework.response import Response

from common.exceptions import WeeklyReportError
from system_config.credentials import CredentialUnavailable
from system_config.integrations import get_config, model_issues
from .llm_client import request_completion


PET_PROMPT = (
    "你叫大肥鱼，是周报空间里的桌宠。用用户使用的语言亲切、简洁地交流，默认用中文。"
    "你只能看到本次对话。涉及周报或知识库时，请用户提供需要讨论的内容。"
)
MAX_MESSAGE_CHARS = 2000


class InvalidConversation(WeeklyReportError):
    default_code = "INVALID_CONVERSATION"
    default_detail = "请发送有效的对话内容。"


class ModelUnavailable(WeeklyReportError):
    status_code = 503
    default_code = "PET_MODEL_UNAVAILABLE"
    default_detail = "暂时无法连接 AI 服务，请稍后重试。"


def conversation(data):
    entries = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not 1 <= len(entries) <= 9 or len(entries) % 2 == 0:
        raise InvalidConversation("每次最多发送 5 轮对话，并以你的新消息结尾。")
    total = 0
    messages = []
    for index, entry in enumerate(entries):
        role = "assistant" if index % 2 else "user"
        if not isinstance(entry, dict) or entry.get("role") != role:
            raise InvalidConversation()
        content = entry.get("content")
        if not isinstance(content, str) or not content.strip() or len(content) > MAX_MESSAGE_CHARS:
            raise InvalidConversation("每条消息须为 1 至 2000 字的文字。")
        content = content.strip()
        total += len(content)
        messages.append({"role": role, "content": content})
    if total > 6000:
        raise InvalidConversation("这段对话超过 6000 字，请缩短后重试。")
    return messages


@api_view(["POST"])
def pet_chat(request):
    history = conversation(request.data)
    try:
        config = get_config("model", credentials=True)
    except CredentialUnavailable as exc:
        raise ModelUnavailable(str(exc)) from None
    if not config["enabled"]:
        raise ModelUnavailable("AI 服务尚未启用，请管理员在「系统配置 → AI 模型」中启用。")
    if model_issues(config):
        raise ModelUnavailable("AI 服务配置不完整，请管理员检查服务地址和模型名称。")
    messages = [{"role": "system", "content": PET_PROMPT}, *history]
    try:
        text, _ = request_completion(config, messages)
    except requests.Timeout:
        raise ModelUnavailable("AI 服务回复超时，请稍后再试。") from None
    except (ValueError, TypeError, IndexError, KeyError, AttributeError):
        raise ModelUnavailable("AI 服务返回的内容格式异常，请管理员检查模型配置。") from None
    except requests.HTTPError:
        raise ModelUnavailable("AI 服务暂时无法生成回复，请管理员检查模型配置。") from None
    except requests.RequestException:
        raise ModelUnavailable() from None
    if not isinstance(text, str) or not text.strip():
        raise ModelUnavailable("AI 服务没有返回文字，请重试或联系管理员。")
    return Response({"reply": text.strip()[:MAX_MESSAGE_CHARS]})
