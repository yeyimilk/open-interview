from __future__ import annotations

import csv
import io
import json
import re
from html.parser import HTMLParser


class _HTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return "\n".join(self.parts)


class CommonDocumentTextExtractor:
    def extract(self, *, filename: str, content_type: str | None, data: bytes) -> str:
        name = filename.lower()
        ctype = (content_type or "").lower()
        if name.endswith(".pdf") or "pdf" in ctype:
            return self._pdf(data)
        if name.endswith(".docx") or "wordprocessingml" in ctype:
            return self._docx(data)
        if name.endswith(".json") or "json" in ctype:
            return self._json(data)
        if name.endswith(".csv") or "csv" in ctype:
            return self._csv(data)
        if name.endswith((".html", ".htm")) or "html" in ctype:
            return self._html(data)
        return _decode(data)

    def _pdf(self, data: bytes) -> str:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((p.extract_text() or "").strip() for p in reader.pages).strip()

    def _docx(self, data: bytes) -> str:
        from docx import Document

        doc = Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()

    def _json(self, data: bytes) -> str:
        parsed = json.loads(_decode(data))
        return _flatten_json(parsed)

    def _csv(self, data: bytes) -> str:
        text = _decode(data)
        out: list[str] = []
        for row in csv.DictReader(io.StringIO(text)):
            bits = [f"{k}: {v}" for k, v in row.items() if v]
            if bits:
                out.append("; ".join(bits))
        return "\n".join(out) if out else text

    def _html(self, data: bytes) -> str:
        parser = _HTMLTextParser()
        parser.feed(_decode(data))
        return parser.text()


def chunk_text(text: str, *, max_chars: int = 6000) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for para in re.split(r"\n\s*\n", text):
        if size + len(para) > max_chars and buf:
            chunks.append("\n\n".join(buf).strip())
            buf = []
            size = 0
        buf.append(para)
        size += len(para)
    if buf:
        chunks.append("\n\n".join(buf).strip())
    return chunks


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _flatten_json(value, prefix: str = "") -> str:
    lines: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            lines.append(_flatten_json(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            lines.append(_flatten_json(v, f"{prefix}[{i}]"))
    else:
        lines.append(f"{prefix}: {value}")
    return "\n".join(x for x in lines if x.strip())
