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


class AdminUserSerializer(UserProfileSerializer):
    last_login_at = serializers.DateTimeField(source="latest_login_time", read_only=True, allow_null=True)
    last_login_ip = serializers.IPAddressField(read_only=True, allow_null=True)
    last_login_location = serializers.CharField(read_only=True, allow_null=True)

    class Meta(UserProfileSerializer.Meta):
        fields = [*UserProfileSerializer.Meta.fields, "last_login_ip", "last_login_location"]
        read_only_fields = fields


class UserFieldsSerializer(serializers.Serializer):
    department_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_department_id(self, value):
        from organizations.models import Department
        if value and not Department.objects.filter(pk=value).exists():
            raise serializers.ValidationError("部门不存在")
        return value


class CreateUserSerializer(UserFieldsSerializer):
    username = serializers.CharField(max_length=150)
    display_name = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(
        choices=UserRole.choices,
        default="member",
    )


class UpdateUserSerializer(UserFieldsSerializer):
    username = serializers.CharField(max_length=150, required=False)
    display_name = serializers.CharField(max_length=150, required=False)
    email = serializers.EmailField(required=False, allow_blank=True)
    role = serializers.ChoiceField(
        choices=UserRole.choices,
        required=False,
    )


class ResetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(max_length=128, style={"input_type": "password"}, min_length=8)
