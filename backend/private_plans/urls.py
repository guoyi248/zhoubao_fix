"""个人计划 URL 路由。"""
from django.urls import path
from . import views

app_name = "private_plans"

urlpatterns = [
    path("", views.plan_list, name="list"),
    path("<uuid:plan_id>", views.plan_detail, name="detail"),
]
