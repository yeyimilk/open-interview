import asyncio
import tempfile
from pathlib import Path

import pytest

from openinterview_storage import paths
from openinterview_storage.factory import BlobStorageConfig, make_blob_storage
from openinterview_storage.interface import BlobStorageError


def test_paths_are_tenant_scoped() -> None:
    p = paths.project_source("u1", "p1", "src/main.py")
    assert p.startswith("users/u1/projects/p1/source/")


def test_paths_reject_traversal() -> None:
    with pytest.raises(ValueError):
        paths.project_source("u1", "p1", "../../etc/passwd")


def test_local_fs_put_get_roundtrip() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as td:
            store = make_blob_storage(
                BlobStorageConfig(backend="local", local_data_dir=td)
            )
            ref = await store.put_bytes("users/u1/projects/p1/source/a.txt", b"hello")
            assert ref.size == 5
            assert await store.exists("users/u1/projects/p1/source/a.txt")
            assert await store.get_bytes("users/u1/projects/p1/source/a.txt") == b"hello"
            assert Path(td, "users/u1/projects/p1/source/a.txt").exists()

    asyncio.run(_run())


def test_local_fs_rejects_path_escape() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as td:
            store = make_blob_storage(
                BlobStorageConfig(backend="local", local_data_dir=td)
            )
            with pytest.raises(BlobStorageError):
                await store.put_bytes("../escape.txt", b"x")

    asyncio.run(_run())
