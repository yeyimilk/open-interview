"""Structure-aware code chunker (Python via ast) + line-window fallback,
plus a markdown-aware doc chunker.

We deliberately keep the surface small. Tree-sitter for more languages can
plug in as another implementation behind the same return shape.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass

from .types import CodeChunk, DocChunk


@dataclass(frozen=True)
class ChunkLimits:
    max_lines: int = 200
    max_chars: int = 6000


class CodeChunker:
    def __init__(self, limits: ChunkLimits | None = None) -> None:
        self._lim = limits or ChunkLimits()

    def chunk(self, *, rel_path: str, language: str, text: str) -> list[CodeChunk]:
        if language == "python":
            return self._chunk_python(rel_path, text)
        return self._chunk_window(rel_path, language, text)

    def _chunk_python(self, rel_path: str, text: str) -> list[CodeChunk]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return self._chunk_window(rel_path, "python", text)

        lines = text.splitlines()
        chunks: list[CodeChunk] = []
        seen_lines: set[int] = set()

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = node.lineno
                end = getattr(node, "end_lineno", start) or start
                body = "\n".join(lines[start - 1 : end])
                if body.strip():
                    chunks.extend(
                        self._maybe_split(rel_path, "python", body, start, node.name)
                    )
                seen_lines.update(range(start, end + 1))

        # Top-level "module body" leftovers (imports, constants, expressions).
        leftover_lines = [i for i, _ in enumerate(lines, start=1) if i not in seen_lines]
        if leftover_lines:
            blocks = _consecutive_blocks(leftover_lines)
            for block_start, block_end in blocks:
                body = "\n".join(lines[block_start - 1 : block_end])
                if body.strip():
                    chunks.extend(
                        self._maybe_split(rel_path, "python", body, block_start, None)
                    )
        return chunks

    def _chunk_window(self, rel_path: str, language: str, text: str) -> list[CodeChunk]:
        lines = text.splitlines()
        chunks: list[CodeChunk] = []
        i = 0
        while i < len(lines):
            j = min(i + self._lim.max_lines, len(lines))
            body = "\n".join(lines[i:j])
            if body.strip():
                chunks.append(
                    CodeChunk(
                        rel_path=rel_path,
                        language=language,
                        text=body[: self._lim.max_chars],
                        symbol=None,
                        start_line=i + 1,
                        end_line=j,
                    )
                )
            i = j
        return chunks

    def _maybe_split(
        self, rel_path: str, language: str, body: str, start_line: int, symbol: str | None
    ) -> list[CodeChunk]:
        if len(body) <= self._lim.max_chars and body.count("\n") <= self._lim.max_lines:
            return [
                CodeChunk(
                    rel_path=rel_path,
                    language=language,
                    text=body,
                    symbol=symbol,
                    start_line=start_line,
                    end_line=start_line + body.count("\n"),
                )
            ]
        # Too big: split by line window inside the symbol.
        out: list[CodeChunk] = []
        lines = body.splitlines()
        i = 0
        part = 0
        while i < len(lines):
            j = min(i + self._lim.max_lines, len(lines))
            piece = "\n".join(lines[i:j])
            if piece.strip():
                out.append(
                    CodeChunk(
                        rel_path=rel_path,
                        language=language,
                        text=piece[: self._lim.max_chars],
                        symbol=f"{symbol}#part{part}" if symbol else None,
                        start_line=start_line + i,
                        end_line=start_line + j - 1,
                    )
                )
                part += 1
            i = j
        return out


def _consecutive_blocks(line_nums: list[int]) -> list[tuple[int, int]]:
    if not line_nums:
        return []
    out: list[tuple[int, int]] = []
    s = e = line_nums[0]
    for n in line_nums[1:]:
        if n == e + 1:
            e = n
        else:
            out.append((s, e))
            s = e = n
    out.append((s, e))
    return out


class DocChunker:
    def __init__(self, limits: ChunkLimits | None = None) -> None:
        self._lim = limits or ChunkLimits()

    def chunk(self, *, rel_path: str, text: str) -> list[DocChunk]:
        # Naive markdown chunking: split on top-level headings; size-cap each block.
        lines = text.splitlines()
        sections: list[tuple[str | None, int, int]] = []
        cur_title: str | None = None
        cur_start = 1
        for i, line in enumerate(lines, start=1):
            if line.startswith("#"):
                if i > cur_start:
                    sections.append((cur_title, cur_start, i - 1))
                cur_title = line.lstrip("#").strip() or None
                cur_start = i
        sections.append((cur_title, cur_start, len(lines)))

        chunks: list[DocChunk] = []
        for title, s, e in sections:
            block = "\n".join(lines[s - 1 : e])
            if not block.strip():
                continue
            i = s
            while i <= e:
                j = min(i + self._lim.max_lines - 1, e)
                piece = "\n".join(lines[i - 1 : j])
                if piece.strip():
                    chunks.append(
                        DocChunk(
                            rel_path=rel_path,
                            text=piece[: self._lim.max_chars],
                            section=title,
                            start_line=i,
                            end_line=j,
                        )
                    )
                i = j + 1
        return chunks
