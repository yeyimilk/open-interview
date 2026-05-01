"""Stubs for cloud BlobStorage backends.

These declare the public interface and config shape for v1; concrete
implementations land in M1+ when we wire actual cloud deployments.
The stub raises NotImplementedError so misconfiguration fails loudly.
"""
from __future__ import annotations

from typing import IO, AsyncIterator

from .interface import BlobRef, BlobStorage, BlobStorageError


class _NotImplementedBackend(BlobStorage):
    backend_name: str = "cloud"

    def _not_impl(self) -> BlobStorageError:
        return BlobStorageError(
            f"{self.backend_name} backend is configured but its implementation "
            f"is not yet wired in v1. Use STORAGE_BACKEND=local for now."
        )

    async def put_bytes(self, logical_path, data, content_type=None) -> BlobRef:  # type: ignore[override]
        raise self._not_impl()

    async def put_stream(self, logical_path, stream: IO[bytes], content_type=None) -> BlobRef:  # type: ignore[override]
        raise self._not_impl()

    async def get_bytes(self, logical_path) -> bytes:  # type: ignore[override]
        raise self._not_impl()

    async def open_read(self, logical_path) -> AsyncIterator[bytes]:  # type: ignore[override]
        raise self._not_impl()

    async def delete(self, logical_path) -> None:  # type: ignore[override]
        raise self._not_impl()

    async def exists(self, logical_path) -> bool:  # type: ignore[override]
        raise self._not_impl()

    async def list(self, prefix) -> list[BlobRef]:  # type: ignore[override]
        raise self._not_impl()

    async def signed_url(self, logical_path, ttl_s) -> str:  # type: ignore[override]
        raise self._not_impl()


class S3BlobStorage(_NotImplementedBackend):
    backend_name = "s3"

    def __init__(self, bucket: str, prefix: str = "", region: str | None = None) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.region = region


class AzureBlobStorage(_NotImplementedBackend):
    backend_name = "azure"

    def __init__(self, account: str, container: str, prefix: str = "") -> None:
        self.account = account
        self.container = container
        self.prefix = prefix.strip("/")


class GCSBlobStorage(_NotImplementedBackend):
    backend_name = "gcs"

    def __init__(self, bucket: str, prefix: str = "") -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
