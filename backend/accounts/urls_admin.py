"""Admin user management URL 路由。"""

from django.urls import path
from . import views

app_name = "accounts_admin"

urlpatterns = [
    path("users", views.admin_list_users, name="list-users"),
    path("users/create", views.admin_create_user, name="create-user"),
    path("users/<uuid:user_id>", views.admin_update_user, name="update-user"),
    path("users/<uuid:user_id>/disable", views.admin_disable_user, name="disable-user"),
    path("users/<uuid:user_id>/enable", views.admin_enable_user, name="enable-user"),
    path("users/<uuid:user_id>/reset-password", views.admin_reset_password, name="reset-password"),
]
