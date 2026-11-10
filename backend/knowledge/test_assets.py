import hashlib
from io import BytesIO
from unittest.mock import Mock

import pytest
from django.test import Client
from PIL import Image

from accounts.models import AccountStatus, User, UserRole
from common import storage as storage_module
from . import views

pytestmark = pytest.mark.django_db
base = "/api/v1/knowledge/assets/"


def signed_in(role=UserRole.MEMBER, status=AccountStatus.ACTIVE):
    user = User.objects.create_user(username=f"{role}-{status}", role=role, account_status=status)
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.parametrize(("extension", "format_name", "mime"),
                         [("png", "PNG", "image/png"), ("jpg", "JPEG", "image/jpeg"),
                          ("gif", "GIF", "image/gif"), ("webp", "WEBP", "image/webp")])
def test_members_read_images_from_local_storage(tmp_path, monkeypatch, settings, extension, format_name, mime):
    monkeypatch.setattr(storage_module, "LOCAL_ROOT", tmp_path)
    local = storage_module.LocalStorage()
    monkeypatch.setattr(views, "storage", local)
    image = BytesIO()
    Image.new("RGB", (1, 1)).save(image, format=format_name)
    body = image.getvalue()
    filename = f"{hashlib.sha256(body).hexdigest()}.{extension}"
    key = "knowledge/assets/" + filename
    url = base + filename
    member = signed_in()
    assert member.get(url).status_code == 404
    assert member.head(url).status_code == 404
    local.put_object(Bucket=settings.S3_BUCKET_ORIGINALS, Key=key, Body=body, ContentType=mime)
    for method in ["get", "head"]:
        response = getattr(member, method)(url, HTTP_ACCEPT=mime)
        assert response.status_code == 200
        assert response["Content-Type"] == mime
        assert response["X-Content-Type-Options"] == "nosniff"
        assert {"private", "no-store"} <= set(response["Cache-Control"].split(", "))
        assert "Cookie" in response["Vary"]
        assert b"".join(response.streaming_content) == (body if method == "get" else b"")
        response.close()


def test_s3_images_require_login_before_storage_lookup(monkeypatch, settings):
    s3 = storage_module.S3Storage()
    s3._client = Mock()
    s3.client.get_object.return_value = {"Body": BytesIO(b"object-bytes")}
    monkeypatch.setattr(views, "storage", s3)
    filename = "e" * 64 + ".jpg"
    url = base + filename
    for blocked in [Client(), signed_in(status=AccountStatus.PENDING), signed_in(status=AccountStatus.DISABLED)]:
        for method in ["get", "head"]:
            response = getattr(blocked, method)(url)
            assert response.status_code == 403 and "private" in response["Cache-Control"]
    assert s3.client.mock_calls == []

    admin = signed_in(UserRole.ADMIN)
    assert admin.head(url).status_code == 200
    s3.client.get_object.assert_not_called()
    expected = {"Bucket": settings.S3_BUCKET_ORIGINALS, "Key": "knowledge/assets/" + filename}
    s3.client.head_object.assert_called_once_with(**expected)
    response = admin.get(url)
    assert b"".join(response.streaming_content) == b"object-bytes"
    response.close()
    s3.client.get_object.assert_called_once_with(**expected)
    assert admin.post(url, {}).status_code == 405
    for invalid in ["f" * 63 + ".png", "f" * 64 + ".svg", "g" * 64 + ".png", filename + "/../secrets"]:
        assert admin.get(base + invalid).status_code == 404
    assert s3.client.get_object.call_count == 1
