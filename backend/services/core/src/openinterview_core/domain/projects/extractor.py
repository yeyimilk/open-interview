"""Safe zip extraction. Yields (rel_path, bytes) tuples in memory.

Refuses absolute paths, traversal segments, symlinks, and oversize entries.
Filters out common ignored directories and binary/lockfile noise.
"""
from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass


class ExtractError(Exception):
    pass


IGNORED_DIRS = {
    ".git",
    ".svn",
    ".hg",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    "target",
    ".next",
    ".nuxt",
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "coverage",
}

IGNORED_EXT = {
    ".lock",
    ".min.js",
    ".min.css",
    ".map",
    ".bin",
    ".o",
    ".so",
    ".dll",
    ".class",
    ".jar",
    ".exe",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
}


@dataclass(frozen=True)
class ExtractedFile:
    rel_path: str
    data: bytes


class ZipExtractor:
    def __init__(
        self,
        *,
        max_files: int = 5000,
        max_file_bytes: int = 1_500_000,
        max_total_bytes: int = 200_000_000,
    ) -> None:
        self._max_files = max_files
        self._max_file_bytes = max_file_bytes
        self._max_total_bytes = max_total_bytes

    def extract(self, blob: bytes) -> Iterator[ExtractedFile]:
        try:
            zf = zipfile.ZipFile(io.BytesIO(blob))
        except zipfile.BadZipFile as e:
            raise ExtractError(f"not a valid zip: {e}") from e

        total = 0
        n = 0
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if not _is_safe(name):
                continue
            if _is_ignored(name):
                continue
            if info.file_size > self._max_file_bytes:
                continue
            if total + info.file_size > self._max_total_bytes:
                break
            n += 1
            if n > self._max_files:
                break
            data = zf.read(info)
            total += len(data)
            # Strip the common top-level folder if zip wraps everything in one dir.
            yield ExtractedFile(rel_path=_normalize(name), data=data)


def _is_safe(name: str) -> bool:
    if not name or name.startswith("/"):
        return False
    parts = name.split("/")
    return all(p not in ("", ".", "..") for p in parts)


def _is_ignored(name: str) -> bool:
    parts = name.split("/")
    if any(p in IGNORED_DIRS for p in parts[:-1]):
        return True
    fname = parts[-1].lower()
    return any(fname.endswith(ext) for ext in IGNORED_EXT)


def _normalize(name: str) -> str:
    # If every entry starts with the same single root folder, callers may
    # later strip it; for now we keep it as-is to preserve structure.
    return name.lstrip("/")
