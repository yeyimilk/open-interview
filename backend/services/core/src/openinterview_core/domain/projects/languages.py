"""Language detection by file extension. Conservative; we only deeply parse
languages we have first-class support for (Python in v1) and use line-window
chunking for the rest."""
from __future__ import annotations

from pathlib import PurePosixPath

EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".swift": "swift",
    ".m": "objc",
    ".mm": "objc",
    ".scala": "scala",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".sql": "sql",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".vue": "vue",
}

DOC_EXTS: set[str] = {".md", ".markdown", ".rst", ".txt", ".adoc"}

# Languages we parse with structure-aware chunkers (v1: python via ast).
LANGS_WE_PARSE = {"python"}


def detect_language(rel_path: str) -> str | None:
    ext = PurePosixPath(rel_path).suffix.lower()
    if ext in EXT_TO_LANG:
        return EXT_TO_LANG[ext]
    if ext in DOC_EXTS:
        return "doc"
    return None
