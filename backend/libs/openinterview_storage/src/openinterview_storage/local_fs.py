"""Local filesystem BlobStorage implementation.

- Atomic writes via tmp + rename.
- Cross-tenant safety: refuses any path that escapes the configured root.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import IO, AsyncIterator

from .interface import BlobRef, BlobStorage, BlobStorageError


class LocalFSBlobStorage(BlobStorage):
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, logical_path: str) -> Path:
        if not logical_path or logical_path.startswith("/"):
            raise BlobStorageError(f"invalid logical path: {logical_path!r}")
        target = (self._root / logical_path).resolve()
        try:
            target.relative_to(self._root)
        except ValueError as e:
            raise BlobStorageError(f"path escapes root: {logical_path!r}") from e
        return target

    async def put_bytes(
        self, logical_path: str, data: bytes, content_type: str | None = None
    ) -> BlobRef:
        target = self._resolve(logical_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        def _write() -> int:
            fd, tmp_path = tempfile.mkstemp(
                prefix=".tmp_", dir=str(target.parent)
            )
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, target)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except FileNotFoundError:
                    pass
                raise
            return len(data)

        size = await asyncio.to_thread(_write)
        return BlobRef(logical_path=logical_path, size=size, content_type=content_type)

    async def put_stream(
        self, logical_path: str, stream: IO[bytes], content_type: str | None = None
    ) -> BlobRef:
        data = await asyncio.to_thread(stream.read)
        return await self.put_bytes(logical_path, data, content_type)

    async def get_bytes(self, logical_path: str) -> bytes:
        target = self._resolve(logical_path)
        if not target.exists():
            raise BlobStorageError(f"not found: {logical_path}")
        return await asyncio.to_thread(target.read_bytes)

    async def open_read(self, logical_path: str) -> AsyncIterator[bytes]:
        data = await self.get_bytes(logical_path)

        async def _gen() -> AsyncIterator[bytes]:
            chunk = 64 * 1024
            for i in range(0, len(data), chunk):
                yield data[i : i + chunk]

        return _gen()

    async def delete(self, logical_path: str) -> None:
        target = self._resolve(logical_path)
        if target.is_dir():
            await asyncio.to_thread(shutil.rmtree, target)
        elif target.exists():
            await asyncio.to_thread(target.unlink)

    async def exists(self, logical_path: str) -> bool:
        target = self._resolve(logical_path)
        return target.exists()

    async def list(self, prefix: str) -> list[BlobRef]:
        base = self._resolve(prefix) if prefix else self._root
        if not base.exists():
            return []

        def _walk() -> list[BlobRef]:
            results: list[BlobRef] = []
            if base.is_file():
                rel = base.relative_to(self._root).as_posix()
                results.append(BlobRef(logical_path=rel, size=base.stat().st_size))
                return results
            for p in base.rglob("*"):
                if p.is_file():
                    rel = p.relative_to(self._root).as_posix()
                    results.append(BlobRef(logical_path=rel, size=p.stat().st_size))
            return results

        return await asyncio.to_thread(_walk)

    async def signed_url(self, logical_path: str, ttl_s: int) -> str:
        target = self._resolve(logical_path)
        return target.as_uri()
