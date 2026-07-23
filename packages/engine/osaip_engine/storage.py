"""THE S3 storage interface (spec §3.1: all storage access goes through here).

Synchronous boto3 core — callers in async apps must go through
`osaip_engine.aio.run_engine` (thread offload + semaphore). Dev endpoint is
SeaweedFS (path-style, no SSL); production is any S3-compatible endpoint.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import IO, Any

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError, EndpointConnectionError

from osaip_engine.errors import AuthFailed, HostUnreachable, ObjectNotFound, StorageError


@dataclass(frozen=True)
class StorageConfig:
    endpoint: str  # host:port, scheme-less (ADR-0006 §2)
    bucket: str
    access_key: str
    secret_key: str
    region: str = "us-east-1"
    use_ssl: bool = False

    @property
    def endpoint_url(self) -> str:
        scheme = "https" if self.use_ssl else "http"
        return f"{scheme}://{self.endpoint}"


class Storage:
    def __init__(self, config: StorageConfig) -> None:
        self.config = config
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
            region_name=config.region,
            config=BotoConfig(
                s3={"addressing_style": "path"},
                connect_timeout=5,
                read_timeout=60,
                retries={"max_attempts": 2},
            ),
        )

    def ensure_bucket(self) -> None:
        """Idempotent, memoized per process: SeaweedFS does not auto-create buckets."""
        if getattr(self, "_ensured", False):
            return
        try:
            self._client.head_bucket(Bucket=self.config.bucket)
        except EndpointConnectionError as exc:
            raise HostUnreachable() from exc
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchBucket"}:
                try:
                    self._client.create_bucket(Bucket=self.config.bucket)
                except ClientError as create_exc:
                    raise StorageError() from create_exc
            elif code in {"403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
                raise AuthFailed() from exc
            else:
                raise StorageError() from exc
        self._ensured = True

    def check_access(self) -> None:
        """Auth probe for test-connection: list one key."""
        try:
            self._client.list_objects_v2(Bucket=self.config.bucket, MaxKeys=1)
        except EndpointConnectionError as exc:
            raise HostUnreachable() from exc
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
                raise AuthFailed() from exc
            if code in {"404", "NoSuchBucket"}:
                raise ObjectNotFound("The bucket does not exist on that endpoint.") from exc
            raise StorageError() from exc

    def put_fileobj(self, fileobj: IO[bytes], key: str) -> None:
        try:
            self._client.upload_fileobj(fileobj, self.config.bucket, key)
        except (ClientError, EndpointConnectionError) as exc:
            raise StorageError() from exc

    def get_bytes(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self.config.bucket, Key=key)
            return bytes(response["Body"].read())
        except EndpointConnectionError as exc:
            raise HostUnreachable() from exc
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchKey"}:
                raise ObjectNotFound() from exc
            raise StorageError() from exc

    def put_bytes(self, data: bytes, key: str) -> None:
        try:
            self._client.put_object(Bucket=self.config.bucket, Key=key, Body=data)
        except (ClientError, EndpointConnectionError) as exc:
            raise StorageError() from exc

    def get_range(self, key: str, start: int) -> bytes:
        """Bytes from `start` to end of object (RFC 9110 Range). Empty if `start` is at
        or beyond the object end. Used to tail job logs by offset (ADR-0007 §6)."""
        try:
            response = self._client.get_object(
                Bucket=self.config.bucket, Key=key, Range=f"bytes={start}-"
            )
            return bytes(response["Body"].read())
        except EndpointConnectionError as exc:
            raise HostUnreachable() from exc
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchKey"}:
                raise ObjectNotFound() from exc
            if code in {"416", "InvalidRange"}:  # start past EOF → nothing new
                return b""
            raise StorageError() from exc

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.config.bucket, Key=key)
            return True
        except ClientError:
            return False

    def list_keys(self, prefix: str) -> Iterator[tuple[str, Any]]:
        """Yields (key, last_modified) under prefix."""
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.config.bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                yield item["Key"], item["LastModified"]

    def delete_prefix(self, prefix: str) -> int:
        keys = [key for key, _ in self.list_keys(prefix)]
        for batch_start in range(0, len(keys), 1000):
            batch = keys[batch_start : batch_start + 1000]
            self._client.delete_objects(
                Bucket=self.config.bucket,
                Delete={"Objects": [{"Key": key} for key in batch]},
            )
        return len(keys)
