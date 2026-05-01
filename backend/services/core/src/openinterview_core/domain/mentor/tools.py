"""LLM-callable tools that let the Mentor agent browse a project.

The agent passes these definitions to the gateway as OpenAI-compatible tool
schemas. When the model emits tool_calls, ``ToolRuntime.dispatch`` runs them
locally against ``ProjectFs`` and returns string results to feed back into the
conversation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from openinterview_schemas import ToolDefinition

from ..projects.fs import ProjectFs


# Per-turn budget knobs.
MAX_TOOL_TURNS = 8
MAX_TOTAL_RESULT_CHARS = 24_000


def project_tool_definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            type="function",
            function={
                "name": "list_dir",
                "description": (
                    "List files and immediate subdirectories under a project path. "
                    "Use '' (empty string) for the project root."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Project-relative directory (e.g. 'src/auth'). Empty for root.",
                            "default": "",
                        },
                    },
                },
            },
        ),
        ToolDefinition(
            type="function",
            function={
                "name": "read_file",
                "description": (
                    "Read a UTF-8 text file from the project. Returns content plus "
                    "language and total_lines. Use start_line/end_line for big files."
                ),
                "parameters": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string"},
                        "start_line": {"type": "integer", "minimum": 1, "default": 1},
                        "end_line": {"type": "integer", "minimum": 1},
                    },
                },
            },
        ),
        ToolDefinition(
            type="function",
            function={
                "name": "grep",
                "description": (
                    "Regex search across project files. Returns up to 80 hits with "
                    "filename, line number, and a snippet."
                ),
                "parameters": {
                    "type": "object",
                    "required": ["pattern"],
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Python regex.",
                        },
                        "glob": {
                            "type": "string",
                            "description": "Optional glob filter (e.g. '**/*.py').",
                        },
                        "case_sensitive": {"type": "boolean", "default": False},
                    },
                },
            },
        ),
        ToolDefinition(
            type="function",
            function={
                "name": "tree",
                "description": "Show a depth-bounded tree of the project (max ~300 entries).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "max_depth": {"type": "integer", "minimum": 1, "maximum": 6, "default": 3},
                    },
                },
            },
        ),
    ]


@dataclass
class ToolCallEvent:
    """Surface trace for the UI."""

    name: str
    args: dict
    result_preview: str  # first ~200 chars


class ToolRuntime:
    def __init__(self, fs: ProjectFs) -> None:
        self._fs = fs
        self._used_chars = 0

    @property
    def used_chars(self) -> int:
        return self._used_chars

    def dispatch(self, name: str, raw_args: str) -> str:
        try:
            args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            return f"ERROR: invalid JSON arguments: {raw_args!r}"
        try:
            if name == "list_dir":
                entries = self._fs.list_dir(args.get("path", ""))
                payload = [
                    {"path": e.path, "kind": e.kind, "size": e.size}
                    for e in entries
                ]
                out = json.dumps(payload, ensure_ascii=False)
            elif name == "read_file":
                r = self._fs.read_file(
                    args["path"],
                    start_line=int(args.get("start_line", 1)),
                    end_line=args.get("end_line"),
                )
                out = json.dumps(
                    {
                        "path": r.path,
                        "language": r.language,
                        "total_lines": r.total_lines,
                        "is_truncated": r.is_truncated,
                        "content": r.content,
                    },
                    ensure_ascii=False,
                )
            elif name == "grep":
                hits = self._fs.grep(
                    args["pattern"],
                    glob=args.get("glob"),
                    case_sensitive=bool(args.get("case_sensitive", False)),
                )
                out = json.dumps(
                    [
                        {"path": h.path, "line": h.line, "snippet": h.snippet}
                        for h in hits
                    ],
                    ensure_ascii=False,
                )
            elif name == "tree":
                out = self._fs.tree(max_depth=int(args.get("max_depth", 3)))
            else:
                out = f"ERROR: unknown tool {name!r}"
        except FileNotFoundError as e:
            out = f"ERROR: file not found: {e}"
        except ValueError as e:
            out = f"ERROR: {e}"
        except Exception as e:  # noqa: BLE001
            out = f"ERROR: {type(e).__name__}: {e}"

        # Enforce total budget.
        remaining = MAX_TOTAL_RESULT_CHARS - self._used_chars
        if len(out) > remaining:
            out = out[: max(0, remaining)] + "\n... (truncated by budget)"
        self._used_chars += len(out)
        return out
