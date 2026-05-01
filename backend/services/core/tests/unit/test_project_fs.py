"""Unit tests for ProjectFs (read-only project filesystem for mentor tools)."""
from __future__ import annotations

import io
import zipfile

import pytest

from openinterview_core.domain.projects.fs import ProjectFs


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_list_dir_root_returns_top_level() -> None:
    fs = ProjectFs.from_zip_bytes(
        _zip({
            "README.md": b"# hi",
            "src/app.py": b"x = 1",
            "src/utils/u.py": b"def f(): pass",
            "tests/test_app.py": b"def test(): pass",
        })
    )
    entries = fs.list_dir("")
    paths = {(e.path, e.kind) for e in entries}
    assert ("README.md", "file") in paths
    assert ("src", "dir") in paths
    assert ("tests", "dir") in paths


def test_list_dir_subdir_filters() -> None:
    fs = ProjectFs.from_zip_bytes(
        _zip({
            "src/a.py": b"a",
            "src/b/c.py": b"c",
            "other.py": b"o",
        })
    )
    entries = fs.list_dir("src")
    kinds = {(e.path.endswith("a.py")): e.kind for e in entries}
    assert any(e.path == "src/a.py" and e.kind == "file" for e in entries)
    assert any(e.path == "src/b" and e.kind == "dir" for e in entries)
    assert not any(e.path == "other.py" for e in entries)
    _ = kinds


def test_read_file_basic_and_truncate() -> None:
    long = "\n".join(f"line {i}" for i in range(1, 51)).encode()
    fs = ProjectFs.from_zip_bytes(_zip({"src/x.py": long}))
    r = fs.read_file("src/x.py")
    assert r.total_lines == 50
    assert r.language == "python"

    r2 = fs.read_file("src/x.py", start_line=10, end_line=12)
    assert r2.content == "line 10\nline 11\nline 12"
    assert r2.is_truncated is True


def test_read_file_path_traversal_rejected() -> None:
    fs = ProjectFs.from_zip_bytes(_zip({"a.py": b"x"}))
    with pytest.raises(ValueError):
        fs.read_file("../etc/passwd")
    with pytest.raises(ValueError):
        fs.read_file("/etc/passwd")
    with pytest.raises(FileNotFoundError):
        fs.read_file("missing.py")


def test_grep_finds_and_caps() -> None:
    fs = ProjectFs.from_zip_bytes(
        _zip({
            "a.py": b"def login(): pass\ndef logout(): pass\n",
            "b.py": b"# nothing here\n",
            "c.txt": b"login appears here too\n",
        })
    )
    hits = fs.grep("log\\w+")
    assert len(hits) >= 2
    paths = {h.path for h in hits}
    assert "a.py" in paths

    only_py = fs.grep("login", glob="*.py")
    assert all(h.path.endswith(".py") for h in only_py)

    none = fs.grep("ZZZ")
    assert none == []


def test_grep_invalid_regex() -> None:
    fs = ProjectFs.from_zip_bytes(_zip({"a.py": b"x"}))
    with pytest.raises(ValueError):
        fs.grep("[unbalanced")


def test_skip_dirs() -> None:
    fs = ProjectFs.from_zip_bytes(
        _zip({
            "src/a.py": b"x",
            "node_modules/lib/index.js": b"junk",
            ".git/config": b"junk",
        })
    )
    paths = [e.path for e in fs.list_dir("")]
    assert "src" == [p for p in paths if p == "src"][0]
    assert "node_modules" not in paths
    assert ".git" not in paths


def test_top_level_wrapper_dir_stripped() -> None:
    fs = ProjectFs.from_zip_bytes(
        _zip({
            "myrepo-main/src/a.py": b"x",
            "myrepo-main/README.md": b"hi",
        })
    )
    paths = {e.path for e in fs.list_dir("")}
    assert "src" in paths or any(p == "src" for p in paths)
    assert any(e.path == "README.md" for e in fs.list_dir(""))
