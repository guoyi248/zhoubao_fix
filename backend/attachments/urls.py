"""附件 URL 路由。"""

from django.urls import path
from . import views

app_name = "attachments"

urlpatterns = [
    # 状态查询 + 批量轮询
    path("<uuid:attachment_id>/status", views.get_attachment_status, name="attachment-status"),
    path("batch-status", views.batch_status, name="batch-status"),

    # 详情 + 预览 + 下载
    path("<uuid:attachment_id>", views.get_attachment_detail, name="attachment-detail"),
    path("<uuid:attachment_id>/preview-content", views.get_preview_content, name="preview-content"),
    path("<uuid:attachment_id>/download", views.download_original, name="download-original"),
    path("<uuid:attachment_id>/compatibility", views.get_compatibility, name="compatibility"),

    # 预览确认
    path("<uuid:attachment_id>/confirm", views.confirm_preview, name="confirm-preview"),
    path("<uuid:attachment_id>/link-author-pdf", views.link_author_pdf, name="link-author-pdf"),

    # 重试 + 删除 + 替换
    path("<uuid:attachment_id>/retry", views.retry_processing, name="retry"),
    path("<uuid:attachment_id>/delete", views.delete_attachment, name="delete"),
    path("<uuid:attachment_id>/replace", views.replace_attachment, name="replace"),
]
