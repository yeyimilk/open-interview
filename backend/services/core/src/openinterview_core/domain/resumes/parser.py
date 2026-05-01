"""Resume text extraction (PDF/DOCX/MD/TXT) and structured parsing via LLM."""
from __future__ import annotations

import json
from typing import Protocol
from uuid import UUID

from openinterview_schemas import ChatMessage

from .types import Claim, ParsedResume


class ResumeTextExtractor:
    """Best-effort text extraction. Falls back to UTF-8 decode for unknown types.

    PDF/DOCX support is opt-in via optional deps; if missing we still accept the
    upload and store the raw bytes' UTF-8 attempt.
    """

    def extract(self, *, filename: str, content_type: str, data: bytes) -> str:
        lower = filename.lower()
        if lower.endswith(".pdf") or content_type == "application/pdf":
            text = self._extract_pdf(data)
        elif lower.endswith(".docx") or "officedocument.wordprocessingml" in content_type:
            text = self._extract_docx(data)
        else:
            text = _safe_decode(data)
        # Final guard: strip NUL bytes (Postgres TEXT can't store them) and
        # ensure the result is plausibly text (binary fallback would have NULs).
        return _sanitize_text(text or "")

    def _extract_pdf(self, data: bytes) -> str | None:
        try:
            import pypdf  # type: ignore
        except ImportError:  # pragma: no cover - optional dep
            return None
        try:
            import io

            r = pypdf.PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in r.pages).strip() or None
        except Exception:  # pragma: no cover
            return None

    def _extract_docx(self, data: bytes) -> str | None:
        try:
            import io

            from docx import Document  # type: ignore
        except ImportError:  # pragma: no cover - optional dep
            return None
        try:
            doc = Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs).strip() or None
        except Exception:  # pragma: no cover
            return None


def _safe_decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _sanitize_text(text: str) -> str:
    """Remove characters Postgres TEXT can't store (NUL) and trim very long blobs.

    If the input still looks binary after stripping NULs, return a placeholder so
    we don't silently store garbage that breaks downstream LLM calls.
    """
    if not text:
        return ""
    cleaned = text.replace("\x00", "")
    # Heuristic: if more than 10% of characters are non-printable control chars,
    # treat as binary that failed extraction.
    if cleaned:
        ctrl = sum(
            1
            for ch in cleaned
            if ord(ch) < 32 and ch not in ("\n", "\r", "\t")
        )
        if ctrl / max(1, len(cleaned)) > 0.10:
            return "[unable to extract text from this file format -- install pypdf / python-docx]"
    return cleaned[:200_000]


# ---------------- Parser ----------------

class ResumeParser(Protocol):
    async def parse(self, *, user_id: UUID, text: str) -> ParsedResume: ...


class LLMResumeParser(ResumeParser):
    def __init__(self, gateway, logical_model: str = "chat-fast") -> None:
        self._gw = gateway
        self._model = logical_model

    async def parse(self, *, user_id: UUID, text: str) -> ParsedResume:
        prompt = (
            "Parse this resume into STRICT JSON with keys: name, contacts (object), "
            "skills (list[str]), experience (list of {title, company, period, bullets:[str]}), "
            "projects (list of {name, summary, bullets:[str]}), education (list), "
            "claims (list of objects {text, section}) where each claim is a single concrete "
            "achievement worth verifying in an interview. JSON only, no prose.\n\n"
            f"RESUME:\n{text[:12000]}"
        )
        r = await self._gw.chat(
            user_id=user_id,
            logical_model=self._model,
            messages=[ChatMessage(role="user", content=prompt)],
        )
        data = _safe_json(r.content, default={})
        claims_raw = data.get("claims") or []
        claims = []
        for c in claims_raw:
            if isinstance(c, dict) and c.get("text"):
                claims.append(Claim(text=str(c["text"]), section=str(c.get("section") or "") or None))
            elif isinstance(c, str):
                claims.append(Claim(text=c))
        return ParsedResume(
            raw_text=text,
            name=str(data.get("name") or "") or None,
            contacts=data.get("contacts") or {},
            skills=[str(s) for s in (data.get("skills") or [])],
            experience=list(data.get("experience") or []),
            projects=list(data.get("projects") or []),
            education=list(data.get("education") or []),
            claims=claims,
        )


def _safe_json(text: str, *, default):
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return default
