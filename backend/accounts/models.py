"""
账号模型：
- User：自定义用户，支持 member / admin / super_admin 角色
- RegistrationRequest：注册申请
- SessionRevocation：会话撤销记录
"""

import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from common.models import BaseModel


class UserRole(models.TextChoices):
    MEMBER = "member", "普通成员"
    ADMIN = "admin", "业务管理员"
    SUPER_ADMIN = "super_admin", "超级管理员"


class AccountStatus(models.TextChoices):
    INVITED = "invited", "已邀请"
    PENDING = "pending_approval", "待审批"
    ACTIVE = "active", "已激活"
    DISABLED = "disabled", "已禁用"


class UserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError("必须设置用户名")
        user = self.model(username=username, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("account_status", AccountStatus.ACTIVE)
        extra_fields.setdefault("role", UserRole.SUPER_ADMIN)
        return self.create_user(username, password, **extra_fields)

    def get_by_natural_key(self, username):
        return self.get(username=username)

    def active(self):
        return self.filter(is_active=True, account_status=AccountStatus.ACTIVE)

    def visible_to(self, viewer):
        """返回 viewer 可见的用户列表。"""
        if not viewer.is_authenticated or not viewer.is_active:
            return self.none()
        if viewer.role in {UserRole.ADMIN, UserRole.SUPER_ADMIN}:
            return self.all()
        return self.filter(id=viewer.id)


class User(AbstractBaseUser, PermissionsMixin):
    """自定义用户模型。"""

    # 账号标识
    username = models.CharField("账号", max_length=150, unique=True)
    email = models.EmailField("邮箱", blank=True, default="")

    # 组织信息
    display_name = models.CharField("姓名", max_length=150)
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
    )

    # 角色与状态
    role = models.CharField(
        "角色",
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.MEMBER,
    )
    account_status = models.CharField(
        "账号状态",
        max_length=20,
        choices=AccountStatus.choices,
        default=AccountStatus.INVITED,
    )

    # 安全
    totp_enabled = models.BooleanField("TOTP 已启用", default=False)
    totp_required = models.BooleanField("强制 TOTP", default=False)

    # 时间戳
    date_joined = models.DateTimeField("注册时间", auto_now_add=True)
    last_login_at = models.DateTimeField("上次登录", null=True, blank=True)
    password_changed_at = models.DateTimeField("密码修改时间", auto_now_add=True)

    # 激活令牌（一次性）
    activation_token = models.CharField(max_length=64, blank=True, default="")
    activation_token_expires_at = models.DateTimeField(null=True, blank=True)

    # 标记
    is_active = models.BooleanField("活跃", default=True)
    is_staff = models.BooleanField("Django Admin 访问", default=False)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["display_name"]

    class Meta:
        db_table = "users"
        verbose_name = "用户"
        verbose_name_plural = "用户"
        indexes = [
            models.Index(fields=["account_status", "role"]),
            models.Index(fields=["department", "account_status"]),
        ]

    def __str__(self):
        return f"{self.display_name} ({self.username})"

    @property
    def is_admin(self):
        return self.role in {UserRole.ADMIN, UserRole.SUPER_ADMIN}

    @property
    def is_super_admin(self):
        return self.role == UserRole.SUPER_ADMIN

    def activate(self):
        self.account_status = AccountStatus.ACTIVE
        self.activation_token = ""
        self.activation_token_expires_at = None
        self.save(update_fields=["account_status", "activation_token", "activation_token_expires_at"])

    def disable(self):
        self.account_status = AccountStatus.DISABLED
        self.is_active = False
        self.save(update_fields=["account_status", "is_active"])
        # 撤销所有现有会话
        SessionRevocation.objects.create(user=self, reason="账号被禁用")

    def enable(self):
        self.account_status = AccountStatus.ACTIVE
        self.is_active = True
        self.save(update_fields=["account_status", "is_active"])


class RegistrationRequest(BaseModel):
    """成员注册申请。"""

    display_name = models.CharField("姓名", max_length=150)
    username = models.CharField("申请账号", max_length=150)
    email = models.EmailField("邮箱", blank=True, default="")
    department_name = models.CharField("部门", max_length=200)
    reason = models.TextField("申请理由", blank=True, default="")
    status = models.CharField(
        "状态",
        max_length=20,
        choices=[("pending", "待审批"), ("approved", "已批准"), ("rejected", "已拒绝")],
        default="pending",
    )
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_requests",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField("审批备注", blank=True, default="")

    class Meta:
        db_table = "registration_requests"
        verbose_name = "注册申请"
        verbose_name_plural = "注册申请"


class SessionRevocation(models.Model):
    """记录需要强制撤销的会话。"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="session_revocations")
    revoked_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=255)
    invalidate_before = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "session_revocations"
        verbose_name = "会话撤销"
        verbose_name_plural = "会话撤销"
