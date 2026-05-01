import io
import zipfile

from openinterview_core.domain.projects.extractor import ZipExtractor


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_extracts_safe_files() -> None:
    blob = _zip_bytes({"a/b.py": b"print(1)", "a/README.md": b"# r"})
    out = list(ZipExtractor().extract(blob))
    paths = {e.rel_path for e in out}
    assert paths == {"a/b.py", "a/README.md"}


def test_skips_traversal_and_ignored_dirs() -> None:
    blob = _zip_bytes({
        "../escape.py": b"x",
        "/abs.py": b"x",
        "node_modules/lib/x.js": b"x",
        ".git/HEAD": b"x",
        "ok/m.py": b"x",
    })
    out = list(ZipExtractor().extract(blob))
    paths = {e.rel_path for e in out}
    assert paths == {"ok/m.py"}


def test_skips_binary_extensions() -> None:
    blob = _zip_bytes({"x/img.png": b"\x89PNG", "x/m.py": b"x"})
    out = list(ZipExtractor().extract(blob))
    assert {e.rel_path for e in out} == {"x/m.py"}
