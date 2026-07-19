"""游标分页，避免大偏移量性能问题。"""

from rest_framework.pagination import CursorPagination as DRFCursorPagination
from rest_framework.response import Response


class CursorPagination(DRFCursorPagination):
    """基于游标的分页，按创建时间降序。"""

    page_size = 50
    max_page_size = 200
    ordering = "-created_at"
    cursor_query_param = "cursor"
    page_size_query_param = "page_size"

    def get_paginated_response(self, data):
        return Response(
            {
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "results": data,
            }
        )
