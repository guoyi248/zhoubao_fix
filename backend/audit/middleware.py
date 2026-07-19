"""审计日志中间件——为每个请求附加 request_id，供日志和审计使用。"""

import uuid


class AuditLogMiddleware:
    """为每个请求生成唯一 request_id。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = str(uuid.uuid4())
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        return response
