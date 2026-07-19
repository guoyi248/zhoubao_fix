"""Me URL 路由。"""

from django.urls import path
from . import views

app_name = "accounts_me"

urlpatterns = [
    path("", views.me_view, name="me"),
]
