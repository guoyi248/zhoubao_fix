"""
账号视图：
- auth: 登录、登出、激活、修改密码
- me: 当前用户信息
- admin: 用户管理（创建、审批、禁用、重置密码）
"""

import uuid
from datetime import timedelta

from django.contrib.auth import authenticate, login as django_login, logout as django_logout
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from .models import User, UserRole, AccountStatus, RegistrationRequest, SessionRevocation
from .serializers import (
    LoginSerializer,
    ChangePasswordSerializer,
    ActivateSerializer,
    UserProfileSerializer,
    CreateUserSerializer,
    UpdateUserSerializer,
    ResetPasswordSerializer,
)
from common.exceptions import (
    InvalidCredentialsError,
    AccountDisabledError,
    PermissionDeniedError,
    ObjectNotFound,
)


# ═══════════════════════════════════════════════════════════════
# Auth
# ═══════════════════════════════════════════════════════════════

@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    """POST /api/v1/auth/login"""
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    user = authenticate(request, username=data["username"], password=data["password"])
    if user is None:
        raise InvalidCredentialsError()

    if user.account_status != AccountStatus.ACTIVE:
        raise AccountDisabledError()

    # TOTP 校验（如已启用）
    if user.totp_enabled and not data.get("totp_code"):
        return Response(
            {"code": "TOTP_REQUIRED", "message": "请提供 TOTP 验证码"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    django_login(request, user)
    user.last_login_at = timezone.now()
    user.save(update_fields=["last_login_at"])

    return Response(UserProfileSerializer(user).data)


@api_view(["POST"])
def logout_view(request):
    """POST /api/v1/auth/logout"""
    django_logout(request)
    return Response({"detail": "已登出"})


@api_view(["POST"])
@permission_classes([AllowAny])
def activate_view(request):
    """POST /api/v1/auth/activate —— 使用一次性令牌激活账号并设置密码。"""
    serializer = ActivateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        user = User.objects.get(activation_token=data["token"])
    except User.DoesNotExist:
        raise ObjectNotFound(detail="激活链接无效或已过期")

    if user.activation_token_expires_at and user.activation_token_expires_at < timezone.now():
        raise ObjectNotFound(detail="激活链接已过期，请联系管理员重新生成")

    try:
        validate_password(data["password"], user)
    except DjangoValidationError as e:
        return Response({"code": "WEAK_PASSWORD", "message": " ".join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(data["password"])
    user.activate()
    return Response({"detail": "账号已激活，请登录"})


@api_view(["POST"])
def change_password_view(request):
    """POST /api/v1/auth/change-password"""
    serializer = ChangePasswordSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    user = request.user
    if not user.check_password(data["old_password"]):
        return Response({"code": "INVALID_PASSWORD", "message": "原密码错误"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        validate_password(data["new_password"], user)
    except DjangoValidationError as e:
        return Response({"code": "WEAK_PASSWORD", "message": " ".join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)

    user.set_password(data["new_password"])
    user.save(update_fields=["password", "password_changed_at"])
    # 修改密码后撤销所有其他会话
    SessionRevocation.objects.create(user=user, reason="密码已修改")
    django_login(request, user)  # 重新登录当前会话
    return Response({"detail": "密码已修改"})


# ═══════════════════════════════════════════════════════════════
# Me
# ═══════════════════════════════════════════════════════════════

@api_view(["GET"])
def me_view(request):
    """GET /api/v1/me"""
    return Response(UserProfileSerializer(request.user).data)


# ═══════════════════════════════════════════════════════════════
# Admin: 用户管理
# ═══════════════════════════════════════════════════════════════


def _require_admin(user):
    if not user.is_authenticated or not user.is_active or not user.is_admin:
        raise PermissionDeniedError()


@api_view(["POST"])
def admin_create_user(request):
    """POST /api/v1/admin/users —— 管理员创建账号。"""
    _require_admin(request.user)

    serializer = CreateUserSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    if User.objects.filter(username=data["username"]).exists():
        return Response(
            {"code": "USERNAME_TAKEN", "message": "账号已存在"},
            status=status.HTTP_409_CONFLICT,
        )

    token = uuid.uuid4().hex
    user = User.objects.create(
        username=data["username"],
        display_name=data["display_name"],
        email=data.get("email", ""),
        department_id=data.get("department_id"),
        role=data.get("role", UserRole.MEMBER),
        account_status=AccountStatus.INVITED,
        activation_token=token,
        activation_token_expires_at=timezone.now() + timedelta(hours=24),
    )
    user.set_unusable_password()

    return Response(
        {
            "id": str(user.id),
            "username": user.username,
            "activation_token": token,
            "detail": "账号已创建，请将激活链接发送给成员",
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
def admin_list_users(request):
    """GET /api/v1/admin/users —— 管理员查看用户列表。"""
    _require_admin(request.user)

    qs = User.objects.visible_to(request.user)
    department = request.GET.get("department")
    role = request.GET.get("role")
    account_status = request.GET.get("status")

    if department:
        qs = qs.filter(department_id=department)
    if role:
        qs = qs.filter(role=role)
    if account_status:
        qs = qs.filter(account_status=account_status)

    users = qs.select_related("department")[:200]
    return Response(UserProfileSerializer(users, many=True).data)


@api_view(["PATCH"])
def admin_update_user(request, user_id):
    """PATCH /api/v1/admin/users/{id}"""
    _require_admin(request.user)

    serializer = UpdateUserSerializer(data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        target = User.objects.get(id=user_id)
    except User.DoesNotExist:
        raise ObjectNotFound()

    # 非超级管理员不能修改管理员
    if target.is_admin and not request.user.is_super_admin:
        raise PermissionDeniedError(detail="只有超级管理员可以修改管理员账号")

    for field, value in data.items():
        if field == "department_id":
            target.department_id = value
        else:
            setattr(target, field, value)

    target.save(update_fields=list(data.keys()))
    return Response(UserProfileSerializer(target).data)


@api_view(["POST"])
def admin_disable_user(request, user_id):
    """POST /api/v1/admin/users/{id}/disable"""
    _require_admin(request.user)
    try:
        target = User.objects.get(id=user_id)
    except User.DoesNotExist:
        raise ObjectNotFound()

    if target.is_super_admin:
        raise PermissionDeniedError(detail="不能禁用超级管理员")

    target.disable()
    return Response({"detail": "账号已禁用"})


@api_view(["POST"])
def admin_enable_user(request, user_id):
    """POST /api/v1/admin/users/{id}/enable"""
    _require_admin(request.user)
    try:
        target = User.objects.get(id=user_id)
    except User.DoesNotExist:
        raise ObjectNotFound()
    target.enable()
    return Response({"detail": "账号已恢复"})


@api_view(["POST"])
def admin_reset_password(request, user_id):
    """POST /api/v1/admin/users/{id}/reset-password"""
    _require_admin(request.user)
    try:
        target = User.objects.get(id=user_id)
    except User.DoesNotExist:
        raise ObjectNotFound()

    if target.is_super_admin and not request.user.is_super_admin:
        raise PermissionDeniedError()

    serializer = ResetPasswordSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    target.set_password(serializer.validated_data["new_password"])
    target.save(update_fields=["password", "password_changed_at"])
    SessionRevocation.objects.create(user=target, reason=f"密码由 {request.user.username} 重置")

    return Response({"detail": "密码已重置"})
