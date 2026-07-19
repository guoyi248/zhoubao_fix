"""
S3/MinIO 对象存储适配器。
所有文件操作通过此模块，不直接依赖具体 SDK。
"""

import io
import hashlib
import logging
from typing import BinaryIO

import boto3
from botocore.config import Config
from django.conf import settings

logger = logging.getLogger(__name__)


class ObjectStorage:
    """S3 兼容对象存储客户端。"""

    def __init__(self):
        self._client = None
        self._resource = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.S3_ENDPOINT,
                aws_access_key_id=settings.S3_ACCESS_KEY,
                aws_secret_access_key=settings.S3_SECRET_KEY,
                region_name=settings.S3_REGION,
                config=Config(
                    signature_version="s3v4",
                    connect_timeout=5,
                    read_timeout=30,
                    retries={"max_attempts": 2},
                ),
            )
        return self._client

    def ensure_bucket(self, bucket_name: str) -> None:
        """确保 Bucket 存在（幂等）。"""
        try:
            self.client.head_bucket(Bucket=bucket_name)
        except Exception:
            self.client.create_bucket(Bucket=bucket_name)

    def upload_stream(
        self,
        bucket: str,
        object_key: str,
        file_obj: BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> dict:
        """
        流式上传文件到对象存储，边读边计算 SHA-256。
        返回 {"sha256": ..., "size": ...}
        """
        sha = hashlib.sha256()
        size = 0

        # 先读取计算哈希
        chunks = []
        while True:
            chunk = file_obj.read(8 * 1024 * 1024)  # 8 MiB
            if not chunk:
                break
            sha.update(chunk)
            size += len(chunk)
            chunks.append(chunk)

        # 上传
        data = b"".join(chunks)
        self.client.put_object(
            Bucket=bucket,
            Key=object_key,
            Body=data,
            ContentType=content_type,
        )

        return {"sha256": sha.hexdigest(), "size": size}

    def download_to_bytes(self, bucket: str, object_key: str) -> bytes:
        """下载对象到内存（仅用于小文件/预览）。"""
        response = self.client.get_object(Bucket=bucket, Key=object_key)
        return response["Body"].read()

    def generate_download_stream(self, bucket: str, object_key: str):
        """生成下载流（返回 body iterator）。"""
        response = self.client.get_object(Bucket=bucket, Key=object_key)
        return response["Body"]

    def generate_presigned_url(self, bucket: str, object_key: str, ttl: int = None) -> str:
        """生成预签名下载 URL。"""
        if ttl is None:
            ttl = settings.SIGNED_URL_TTL_SECONDS
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": object_key},
            ExpiresIn=ttl,
        )

    def delete_object(self, bucket: str, object_key: str) -> None:
        """删除对象。"""
        self.client.delete_object(Bucket=bucket, Key=object_key)

    def object_exists(self, bucket: str, object_key: str) -> bool:
        """检查对象是否存在。"""
        try:
            self.client.head_object(Bucket=bucket, Key=object_key)
            return True
        except Exception:
            return False

    def copy_object(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> None:
        """复制对象。"""
        self.client.copy_object(
            Bucket=dst_bucket,
            Key=dst_key,
            CopySource={"Bucket": src_bucket, "Key": src_key},
        )


# 全局单例
storage = ObjectStorage()
