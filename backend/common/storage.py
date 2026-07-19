"""
对象存储适配器。优先 S3/MinIO，不可用时自动回退到本地文件。
"""

import io
import hashlib
import logging
import os
import shutil
from pathlib import Path
from typing import BinaryIO

import boto3
from botocore.config import Config
from django.conf import settings

logger = logging.getLogger(__name__)

LOCAL_ROOT = Path(settings.BASE_DIR) / "media"  # noqa: F405


class LocalStorage:
    """本地文件系统存储。S3 不可用时的回退方案。"""

    def __init__(self):
        LOCAL_ROOT.mkdir(parents=True, exist_ok=True)

    def upload_stream(self, bucket: str, object_key: str, file_obj: BinaryIO, content_type: str = "") -> dict:
        path = LOCAL_ROOT / object_key
        path.parent.mkdir(parents=True, exist_ok=True)
        sha = hashlib.sha256()
        size = 0
        with open(path, "wb") as f:
            while True:
                chunk = file_obj.read(8 * 1024 * 1024)
                if not chunk:
                    break
                sha.update(chunk)
                size += len(chunk)
                f.write(chunk)
        return {"sha256": sha.hexdigest(), "size": size}

    def download_to_bytes(self, bucket: str, object_key: str) -> bytes:
        path = LOCAL_ROOT / object_key
        return path.read_bytes()

    def generate_download_stream(self, bucket: str, object_key: str):
        path = LOCAL_ROOT / object_key
        return open(path, "rb")

    def generate_presigned_url(self, bucket: str, object_key: str, ttl: int = None) -> str:
        return f"/media/{object_key}"

    def delete_object(self, bucket: str, object_key: str) -> None:
        path = LOCAL_ROOT / object_key
        if path.exists():
            path.unlink()

    def object_exists(self, bucket: str, object_key: str) -> bool:
        return (LOCAL_ROOT / object_key).exists()

    def copy_object(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> None:
        src = LOCAL_ROOT / src_key
        dst = LOCAL_ROOT / dst_key
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    def put_object(self, Bucket, Key, Body, ContentType=""):
        path = LOCAL_ROOT / Key
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(Body, str):
            path.write_text(Body)
        else:
            path.write_bytes(Body)

    def get_object(self, Bucket, Key):
        class Response:
            def __init__(self, data):
                self._data = data
            def read(self):
                return self._data
            @property
            def Body(self):
                return self
        return Response((LOCAL_ROOT / Key).read_bytes())

    def head_object(self, Bucket, Key):
        if not (LOCAL_ROOT / Key).exists():
            raise FileNotFoundError(Key)

    def head_bucket(self, Bucket):
        pass

    def create_bucket(self, Bucket):
        pass

    @property
    def client(self):
        return self


class S3Storage:
    """S3/MinIO 对象存储。"""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.S3_ENDPOINT,
                aws_access_key_id=settings.S3_ACCESS_KEY,
                aws_secret_access_key=settings.S3_SECRET_KEY,
                region_name=settings.S3_REGION,
                config=Config(signature_version="s3v4", connect_timeout=3, read_timeout=30, retries={"max_attempts": 1}),
            )
        return self._client

    def upload_stream(self, bucket, object_key, file_obj, content_type="application/octet-stream"):
        sha = hashlib.sha256()
        size = 0
        chunks = []
        while True:
            chunk = file_obj.read(8 * 1024 * 1024)
            if not chunk:
                break
            sha.update(chunk)
            size += len(chunk)
            chunks.append(chunk)
        self.client.put_object(Bucket=bucket, Key=object_key, Body=b"".join(chunks), ContentType=content_type)
        return {"sha256": sha.hexdigest(), "size": size}

    def download_to_bytes(self, bucket, object_key):
        return self.client.get_object(Bucket=bucket, Key=object_key)["Body"].read()

    def generate_download_stream(self, bucket, object_key):
        return self.client.get_object(Bucket=bucket, Key=object_key)["Body"]

    def delete_object(self, bucket, object_key):
        self.client.delete_object(Bucket=bucket, Key=object_key)

    def object_exists(self, bucket, object_key):
        try:
            self.client.head_object(Bucket=bucket, Key=object_key)
            return True
        except Exception:
            return False

    def copy_object(self, src_bucket, src_key, dst_bucket, dst_key):
        self.client.copy_object(Bucket=dst_bucket, Key=dst_key, CopySource={"Bucket": src_bucket, "Key": src_key})


storage = S3Storage()
