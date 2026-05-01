"""BlobStorage interface. All file artifacts go through this abstraction.

Application code uses logical paths only; backends resolve them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import IO, AsyncIterator, Protocol, runtime_checkable


class BlobStorageError(Exception):
    """Raised for storage-layer errors."""


@dataclass(frozen=True)
class BlobRef:
    logical_path: str
    size: int | None = None
    content_type: str | None = None
    etag: str | None = None


@runtime_checkable
class BlobStorage(Protocol):
    """Async, backend-agnostic blob store."""

    async def put_bytes(
        self,
        logical_path: str,
        data: bytes,
        content_type: str | None = None,
    ) -> BlobRef: ...

    async def put_stream(
        self,
        logical_path: str,
        stream: IO[bytes],
        content_type: str | None = None,
    ) -> BlobRef: ...

    async def get_bytes(self, logical_path: str) -> bytes: ...

    async def open_read(self, logical_path: str) -> AsyncIterator[bytes]: ...

    async def delete(self, logical_path: str) -> None: ...

    async def exists(self, logical_path: str) -> bool: ...

    async def list(self, prefix: str) -> list[BlobRef]: ...

    async def signed_url(self, logical_path: str, ttl_s: int) -> str: ...
