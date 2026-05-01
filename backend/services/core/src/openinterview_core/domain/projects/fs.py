"""Read-only filesystem view over a project's uploaded source.zip.

Used by the Mentor agent's tool loop so the LLM can list directories, read
files, and grep — Cursor / Claude-Code style. Pure Python, no shell-out.

Safety:
- Paths are normalized; absolute paths and traversal escapes are rejected.
- Reads are size-capped per call to keep tool budgets predictable.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from openinterview_storage import paths
from openinterview_storage.interface import BlobStorage


_LANG_BY_EXT: dict[str, str] = {
    "py": "python",
    "ts": "typescript",
    "tsx": "tsx",
    "js": "javascript",
    "jsx": "jsx",
    "go": "go",
    "rs": "rust",
    "java": "java",
    "kt": "kotlin",
    "rb": "ruby",
    "cs": "csharp",
    "php": "php",
    "swift": "swift",
    "c": "c",
    "h": "c",
    "cpp": "cpp",
    "cc": "cpp",
    "hpp": "cpp",
    "json": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "toml": "toml",
    "md": "markdown",
    "html": "html",
    "css": "css",
    "scss": "scss",
    "sh": "bash",
    "sql": "sql",
}

_SKIP_DIRS = {
    "__MACOSX",
    "node_modules",
    ".git",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".turbo",
    "target",
    "out",
}


def _normalize(rel: str) -> str:
    """Reject absolute paths, drop redundant separators, forbid traversal."""
    if not isinstance(rel, str):
        raise ValueError("path must be a string")
    s = rel.replace("\\", "/").strip()
    if s.startswith("/"):
        raise ValueError("absolute paths are not allowed")
    parts: list[str] = []
    for p in s.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            raise ValueError("path traversal is not allowed")
        parts.append(p)
    return "/".join(parts)


@dataclass(frozen=True)
class DirEntry:
    path: str
    kind: str  # "file" | "dir"
    size: int


@dataclass(frozen=True)
class ReadResult:
    path: str
    content: str
    total_lines: int
    is_truncated: bool
    language: str | None


@dataclass(frozen=True)
class GrepHit:
    path: str
    line: int
    snippet: str


class ProjectFs:
    """In-memory read-only view of a project's source.zip.

    Cheap to construct from already-loaded zip bytes. Keep one per agent turn.
    """

    MAX_READ_BYTES = 256 * 1024  # 256 KB cap per read

    def __init__(self, *, files: dict[str, bytes]) -> None:
        # Normalize keys + drop common build/dep dirs and binary skip-list.
        self._files: dict[str, bytes] = {}
        for k, v in files.items():
            norm = k.replace("\\", "/")
            if any(seg in _SKIP_DIRS for seg in norm.split("/")):
                continue
            # Drop directory entries (some zips include them as 0-byte names ending /)
            if norm.endswith("/"):
                continue
            self._files[norm] = v

    @classmethod
    def from_zip_bytes(cls, data: bytes) -> "ProjectFs":
        files: dict[str, bytes] = {}
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            # Detect a single top-level wrapper directory: every entry must be
            # nested under one common first segment (i.e. that segment is a
            # directory, not a top-level file).
            names = [n for n in zf.namelist() if not n.endswith("/")]
            top: str | None = None
            if len(names) > 1:
                first_segs = {n.split("/", 1)[0] for n in names}
                if (
                    len(first_segs) == 1
                    and all("/" in n for n in names)
                ):
                    top = next(iter(first_segs))
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if top and name.startswith(top + "/"):
                    name = name[len(top) + 1 :]
                if not name:
                    continue
                files[name] = zf.read(info)
        return cls(files=files)

    @classmethod
    async def from_blob(
        cls, *, blob: BlobStorage, user_id: UUID, project_id: UUID
    ) -> "ProjectFs":
        path = f"{paths.user_root(user_id)}/projects/{project_id}/source.zip"
        data = await blob.get_bytes(path)
        return cls.from_zip_bytes(data)

    # --- public API used by the agent ---

    def list_dir(self, rel_dir: str = "", *, max_entries: int = 200) -> list[DirEntry]:
        prefix = _normalize(rel_dir)
        if prefix:
            prefix = prefix + "/"
        seen_dirs: set[str] = set()
        files: list[DirEntry] = []
        for path, data in self._files.items():
            if not path.startswith(prefix):
                continue
            rest = path[len(prefix) :]
            if "/" in rest:
                top = rest.split("/", 1)[0]
                if top and top not in seen_dirs:
                    seen_dirs.add(top)
            else:
                files.append(
                    DirEntry(path=path, kind="file", size=len(data))
                )
        dirs = [
            DirEntry(path=prefix + d, kind="dir", size=0) for d in sorted(seen_dirs)
        ]
        out = dirs + sorted(files, key=lambda e: e.path)
        return out[:max_entries]

    def read_file(
        self, rel_path: str, *, start_line: int = 1, end_line: int | None = None
    ) -> ReadResult:
        norm = _normalize(rel_path)
        data = self._files.get(norm)
        if data is None:
            raise FileNotFoundError(norm)
        if len(data) > self.MAX_READ_BYTES:
            data = data[: self.MAX_READ_BYTES]
            truncated_size = True
        else:
            truncated_size = False
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        total = len(lines)
        s = max(1, start_line)
        e = total if end_line is None else min(total, end_line)
        sub = lines[s - 1 : e]
        truncated = truncated_size or e < total
        ext = norm.rsplit(".", 1)[-1].lower() if "." in norm else ""
        return ReadResult(
            path=norm,
            content="\n".join(sub),
            total_lines=total,
            is_truncated=truncated,
            language=_LANG_BY_EXT.get(ext),
        )

    def grep(
        self,
        pattern: str,
        *,
        glob: str | None = None,
        case_sensitive: bool = False,
        max_results: int = 80,
    ) -> list[GrepHit]:
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            rx = re.compile(pattern, flags)
        except re.error as e:
            raise ValueError(f"invalid regex: {e}") from e
        glob_rx: re.Pattern | None = None
        if glob:
            glob_rx = re.compile(_glob_to_regex(glob))
        hits: list[GrepHit] = []
        for path, data in sorted(self._files.items()):
            if glob_rx and not glob_rx.search(path):
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if rx.search(line):
                    snippet = line.strip()
                    if len(snippet) > 240:
                        snippet = snippet[:240] + "..."
                    hits.append(GrepHit(path=path, line=i, snippet=snippet))
                    if len(hits) >= max_results:
                        return hits
        return hits

    def tree(self, *, max_depth: int = 3, max_entries: int = 300) -> str:
        """Pretty-print a depth-bounded tree."""
        lines: list[str] = []
        seen: set[str] = set()
        for path in sorted(self._files):
            parts = path.split("/")
            if len(parts) - 1 > max_depth:
                continue
            for i in range(1, len(parts) + 1):
                sub = "/".join(parts[:i])
                if sub in seen:
                    continue
                seen.add(sub)
                depth = i - 1
                indent = "  " * depth
                kind = "📄" if i == len(parts) else "📁"
                lines.append(f"{indent}{kind} {parts[i - 1]}")
                if len(lines) >= max_entries:
                    lines.append("...(truncated)")
                    return "\n".join(lines)
        return "\n".join(lines)

    def file_count(self) -> int:
        return len(self._files)


def _glob_to_regex(glob: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(glob):
        c = glob[i]
        if c == "*":
            if i + 1 < len(glob) and glob[i + 1] == "*":
                out.append(".*")
                i += 2
                if i < len(glob) and glob[i] == "/":
                    i += 1
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c in ".+(){}|^$":
            out.append("\\" + c)
            i += 1
        else:
            out.append(c)
            i += 1
    return "(?:^|/)" + "".join(out) + "$"
