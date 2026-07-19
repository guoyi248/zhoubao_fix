"""
账号序列化器。
"""

from rest_framework import serializers
from .models import User, UserRole, AccountStatus


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, style={"input_type": "password"})
    totp_code = serializers.CharField(max_length=6, required=False, allow_blank=True, default="")


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(max_length=128, style={"input_type": "password"})
    new_password = serializers.CharField(max_length=128, style={"input_type": "password"}, min_length=8)


class ActivateSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=64)
    password = serializers.CharField(max_length=128, style={"input_type": "password"}, min_length=8)


class UserProfileSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", default="")

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "display_name",
            "email",
            "role",
            "department_name",
            "account_status",
            "totp_enabled",
            "date_joined",
            "last_login_at",
        ]
        read_only_fields = fields


class CreateUserSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    display_name = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    department_id = serializers.UUIDField(required=False, allow_null=True)
    role = serializers.ChoiceField(
        choices=[("member", "普通成员"), ("admin", "业务管理员")],
        default="member",
    )


class UpdateUserSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=150, required=False)
    email = serializers.EmailField(required=False)
    department_id = serializers.UUIDField(required=False, allow_null=True)
    role = serializers.ChoiceField(
        choices=[("member", "普通成员"), ("admin", "业务管理员")],
        required=False,
    )


class ResetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(max_length=128, style={"input_type": "password"}, min_length=8)
