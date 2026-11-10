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
from django.db import IntegrityError, transaction
from django.db.models import OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django_otp import match_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from .models import User, UserRole, AccountStatus, RegistrationRequest, SessionRevocation
from .serializers import (
    LoginSerializer,
    AdminUserSerializer,
    ChangePasswordSerializer,
    ActivateSerializer,
    UserProfileSerializer,
    CreateUserSerializer,
    UpdateUserSerializer,
    ResetPasswordSerializer,
)
from audit.events import record
from audit.models import AuditEvent
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
@csrf_protect
def login_view(request):
    """POST /api/v1/auth/login"""
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    user = authenticate(request, username=data["username"], password=data["password"])
    if user is None:
        record(request, AuditEvent.EventType.LOGIN_FAILURE, f"登录失败 · {data['username']}", actor=None, result="failure")
        raise InvalidCredentialsError()

    if user.account_status != AccountStatus.ACTIVE:
        record(request, AuditEvent.EventType.LOGIN_FAILURE, "账号未激活或已停用", actor=user, result="denied")
        raise AccountDisabledError()

    if user.totp_enabled or user.totp_required:
        code = data["totp_code"]
        if not code:
            return Response({"code": "TOTP_REQUIRED", "message": "请提供 TOTP 验证码"}, status=401)
        device = match_token(user, code) if len(code) == 6 and code.isascii() and code.isdigit() else None
        if device is None:
            record(request, AuditEvent.EventType.LOGIN_FAILURE, "TOTP 验证失败", actor=user, result="failure")
            return Response({"code": "INVALID_TOTP", "message": "验证码无效或已使用"}, status=401)
        user.otp_device = device

    django_login(request, user)
    record(request, AuditEvent.EventType.LOGIN_SUCCESS, f"登录账号 {user.username}", actor=user)

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
@csrf_protect
@transaction.atomic
def activate_view(request):
    """POST /api/v1/auth/activate —— 使用一次性令牌激活账号并设置密码。"""
    serializer = ActivateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        user = User.objects.select_for_update().get(
            activation_token=data["token"], account_status=AccountStatus.INVITED, is_active=True,
        )
    except User.DoesNotExist:
        raise ObjectNotFound(detail="激活链接无效或已过期")

    if user.activation_token_expires_at and user.activation_token_expires_at < timezone.now():
        raise ObjectNotFound(detail="激活链接已过期，请联系管理员重新生成")

    try:
        validate_password(data["password"], user)
    except DjangoValidationError as e:
        return Response({"code": "WEAK_PASSWORD", "message": " ".join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)

    user.activate(data["password"])
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
    user.password_changed_at = timezone.now()
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


def _lock_accounts(request, user_id=None):
    # 在同一事务内重新核实操作者权限，以固定顺序锁定双方，避免并发互相降权。
    ids = [request.user.pk] if user_id is None else [request.user.pk, user_id]
    accounts = {user.pk: user for user in User.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    actor = accounts.get(request.user.pk)
    if not actor or actor.account_status != AccountStatus.ACTIVE:
        raise PermissionDeniedError()
    _require_admin(actor)
    if user_id is None:
        return actor
    target = accounts.get(user_id)
    if not target or target.account_status == AccountStatus.DELETED:
        raise ObjectNotFound()
    return target


def _username_taken():
    return Response({"code": "USERNAME_TAKEN", "message": "该账号名已被使用，请换一个账号名"}, status=409)


@api_view(["POST"])
@transaction.atomic
def admin_create_user(request):
    _lock_accounts(request)
    serializer = CreateUserSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    token = uuid.uuid4().hex
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                **data, account_status=AccountStatus.INVITED,
                activation_token=token, activation_token_expires_at=timezone.now() + timedelta(hours=24),
            )
    except IntegrityError:
        if User.objects.filter(username=data["username"]).exists():
            return _username_taken()
        raise
    record(request, AuditEvent.EventType.USER_CREATED, f"新增{user.get_role_display()} · {user}", target=user)
    return Response({"id": str(user.pk), "username": user.username, "activation_token": token,
                     "detail": "账号已创建，激活链接在 24 小时内有效"}, status=201)


@api_view(["GET"])
def admin_list_users(request):
    _require_admin(request.user)
    qs = User.objects.visible_to(request.user).select_related("department")
    for key, field in (("department", "department_id"), ("role", "role"), ("status", "account_status")):
        if value := request.GET.get(key):
            if key == "department":
                try:
                    value = uuid.UUID(value)
                except ValueError:
                    return Response({"message": "部门标识无效"}, status=400)
            qs = qs.filter(**{field: value})
    if query := request.GET.get("q", "").strip():
        qs = qs.filter(Q(username__icontains=query) | Q(display_name__icontains=query) | Q(email__icontains=query))
    latest_login = AuditEvent.objects.filter(actor_id=OuterRef("pk"), event_type=AuditEvent.EventType.LOGIN_SUCCESS).order_by("-created_at", "-event_id")
    qs = qs.annotate(
        latest_login_time=Coalesce("last_login_at", Subquery(latest_login.values("created_at")[:1]), "last_login"),
        last_login_ip=Subquery(latest_login.values("actor_ip")[:1]),
        last_login_location=Subquery(latest_login.values("actor_location")[:1]),
    ).order_by("username", "pk")
    if "page" not in request.GET:
        return Response(AdminUserSerializer(qs[:200], many=True).data)
    from django.core.paginator import Paginator
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return Response({"users": AdminUserSerializer(page.object_list, many=True).data, "total": page.paginator.count,
                     "page": page.number, "page_size": page.paginator.per_page})


@api_view(["PATCH"])
@transaction.atomic
def admin_update_user(request, user_id):
    target = _lock_accounts(request, user_id)
    serializer = UpdateUserSerializer(data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    changes = {key: value for key, value in serializer.validated_data.items() if getattr(target, key) != value}
    if not changes:
        return Response(UserProfileSerializer(target).data)
    if "role" in changes and request.user.pk == target.pk:
        raise PermissionDeniedError(detail="请由另一位管理员调整你的角色")
    old_name = str(target)
    for key, value in changes.items():
        setattr(target, key, value)
    fields = list(changes)
    if changes.get("role") == UserRole.MEMBER:
        target.is_staff = target.is_superuser = False
        fields.extend(["is_staff", "is_superuser"])
    try:
        with transaction.atomic():
            target.save(update_fields=fields)
    except IntegrityError:
        if "username" in changes and User.objects.exclude(pk=user_id).filter(username=changes["username"]).exists():
            return _username_taken()
        raise
    labels = {"username": "账号名", "display_name": "姓名", "email": "提醒邮箱", "department_id": "部门", "role": "角色"}
    summary = f"{old_name} · 修改{'、'.join(labels[field] for field in changes)}"
    if "role" in changes:
        summary += f"为{target.get_role_display()}"
    record(request, AuditEvent.EventType.ROLE_CHANGED if "role" in changes else AuditEvent.EventType.USER_UPDATED,
           summary, target=target)
    return Response(UserProfileSerializer(target).data)


@api_view(["POST"])
@transaction.atomic
def admin_disable_user(request, user_id):
    target = _lock_accounts(request, user_id)
    if target.pk == request.user.pk:
        raise PermissionDeniedError(detail="不能停用自己的账号")
    if target.account_status != AccountStatus.ACTIVE:
        return Response({"message": "只能停用已激活的账号"}, status=409)
    target.disable()
    record(request, AuditEvent.EventType.USER_DISABLED, f"停用账号 · {target}", target=target)
    return Response({"detail": "账号已停用"})


@api_view(["POST"])
@transaction.atomic
def admin_enable_user(request, user_id):
    target = _lock_accounts(request, user_id)
    if target.account_status != AccountStatus.DISABLED:
        return Response({"code": "NOT_DISABLED", "message": "只有已停用的账号可以恢复"}, status=409)
    target.enable()
    record(request, AuditEvent.EventType.USER_ENABLED, f"恢复账号 · {target}", target=target)
    return Response({"detail": "账号已恢复"})


@api_view(["POST"])
@transaction.atomic
def admin_reset_password(request, user_id):
    target = _lock_accounts(request, user_id)
    form = ResetPasswordSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    password = form.validated_data["new_password"]
    try:
        validate_password(password, target)
    except DjangoValidationError as exc:
        return Response({"code": "WEAK_PASSWORD", "message": " ".join(exc.messages)}, status=400)
    target.set_password(password)
    target.password_changed_at = timezone.now()
    if target.account_status == AccountStatus.INVITED:
        target.account_status = AccountStatus.ACTIVE
        target.activation_token = ""
        target.activation_token_expires_at = None
    target.save(update_fields=["password", "password_changed_at", "account_status", "activation_token", "activation_token_expires_at"])
    SessionRevocation.objects.create(user=target, reason=f"密码由 {request.user.username} 重置")
    record(request, AuditEvent.EventType.PASSWORD_RESET, f"重置密码 · {target}", target=target)
    if target.pk == request.user.pk:
        from django.contrib.auth import update_session_auth_hash
        update_session_auth_hash(request, target)
    return Response({"detail": "密码已重置"})


@api_view(["DELETE"])
@transaction.atomic
def admin_delete_user(request, user_id):
    target = _lock_accounts(request, user_id)
    if target.pk == request.user.pk:
        raise PermissionDeniedError(detail="不能删除自己的账号")
    # 保留原始外键以供历史周报、附件、组会和操作记录追溯。
    target.account_status = AccountStatus.DELETED
    target.is_active = False
    target.is_staff = target.is_superuser = False
    target.activation_token = ""
    target.activation_token_expires_at = None
    target.set_unusable_password()
    target.save(update_fields=["account_status", "is_active", "is_staff", "is_superuser", "activation_token",
                               "activation_token_expires_at", "password"])
    record(request, AuditEvent.EventType.USER_DELETED, f"删除账号 · {target}", target=target, risk="high")
    return Response({"detail": "账号已删除，历史周报与操作记录已保留"})
