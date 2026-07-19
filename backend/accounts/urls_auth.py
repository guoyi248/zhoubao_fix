"""Auth URL 路由。"""

from django.urls import path
from . import views

app_name = "accounts_auth"

urlpatterns = [
    path("login", views.login_view, name="login"),
    path("logout", views.logout_view, name="logout"),
    path("activate", views.activate_view, name="activate"),
    path("change-password", views.change_password_view, name="change-password"),
]
