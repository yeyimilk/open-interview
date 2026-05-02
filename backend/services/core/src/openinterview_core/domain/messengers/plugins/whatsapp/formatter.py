"""Convert generic markdown produced by the LLM into text that renders
nicely on WhatsApp's mobile UI.

WhatsApp's text styling is a small subset of markdown:
  *bold*           (single asterisks)
  _italic_         (single underscores)
  ~strike~         (single tildes)
  ```mono```       (triple backticks, multiline code block)
  `mono`           (single backticks, inline mono)
  > quoted line    (per-line blockquote)

Plain markdown features that DO NOT render and look ugly on phone screens:
  **bold** / __bold__   → shown literally
  # / ## / ### headings → "# " shown literally
  [label](url)          → shown literally
  | a | b |             → tables look like noise
  ---/===               → horizontal rules render as dashes

This formatter rewrites those into the WhatsApp-friendly subset and
tightens whitespace.

Code fences (```...```) are preserved verbatim.
"""
from __future__ import annotations

import re

_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_BOLD_DOUBLE_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_BOLD_UNDERSCORE_RE = re.compile(r"__(.+?)__", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", re.MULTILINE)
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(?!\*)", re.MULTILINE)
_BLOCKQUOTE_RE = re.compile(r"^(\s*)>\s?", re.MULTILINE)
_TRIPLE_NEWLINE_RE = re.compile(r"\n{3,}")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$", re.MULTILINE)


def to_whatsapp(text: str) -> str:
    if not text:
        return text

    # Protect code fences from rewrites; restore them at the end.
    fences: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        fences.append(match.group(0))
        return f"\x00FENCE{len(fences) - 1}\x00"

    body = _FENCE_RE.sub(_stash, text)

    body = _IMAGE_RE.sub(lambda m: m.group(2), body)
    body = _LINK_RE.sub(_render_link, body)

    body = _BOLD_DOUBLE_RE.sub(r"*\1*", body)
    body = _BOLD_UNDERSCORE_RE.sub(r"*\1*", body)

    body = _HEADING_RE.sub(lambda m: f"*{m.group(2).strip()}*", body)

    body = _TABLE_SEP_RE.sub("", body)
    body = _flatten_tables(body)

    body = _HR_RE.sub("", body)

    body = _BULLET_RE.sub(r"\1• ", body)

    body = _BLOCKQUOTE_RE.sub(r"\1> ", body)

    body = _TRIPLE_NEWLINE_RE.sub("\n\n", body)
    body = body.strip()

    for i, fence in enumerate(fences):
        body = body.replace(f"\x00FENCE{i}\x00", fence)

    return body


def _render_link(match: re.Match[str]) -> str:
    label = match.group(1).strip()
    url = match.group(2).strip()
    if not label or label == url:
        return url
    return f"{label}: {url}"


def _flatten_tables(text: str) -> str:
    out_lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            cells = [c for c in cells if c]
            if cells:
                out_lines.append(" | ".join(cells))
            continue
        out_lines.append(line)
    return "\n".join(out_lines)
