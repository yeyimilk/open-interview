"""Mentor agent.

State machine:

  recall_memory -> retrieve_vector_context -> tool_loop ↔ respond_stream

The tool loop lets the LLM call read-only ``ProjectFs`` tools (list_dir,
read_file, grep, tree) so the mentor can browse the user's repo when the
vector retrieval is insufficient. Tool turns are non-streaming (we need the
``tool_calls`` field). When the model returns no further tool_calls, we
stream the final answer.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from openinterview_schemas import ChatMessage as ChatMessageDTO
from openinterview_schemas import RetrieveRequest, RetrievalPurpose, RetrievalSource
from openinterview_schemas import RetrievedChunk
from openinterview_schemas import ToolCall

from ..projects.fs import ProjectFs
from ..retrieval import RetrievalService
from .tools import (
    MAX_TOOL_TURNS,
    MAX_TOTAL_RESULT_CHARS,
    ToolRuntime,
    project_tool_definitions,
)


class MentorAgent:
    def __init__(
        self,
        *,
        gateway,
        retrieval_service: RetrievalService,
        blob=None,
        chat_logical_model: str = "chat-fast",
    ) -> None:
        self._gw = gateway
        self._retrieval = retrieval_service
        self._blob = blob
        self._model = chat_logical_model

    # ------- helpers -------

    def _build_general_messages(
        self,
        *,
        working_messages: list[dict],
        memory_ctx: list[dict],
        workspace_brief: str,
        workspace_ctx: list[dict],
        common_ctx: list[dict],
        user_input: str,
    ) -> list[ChatMessageDTO]:
        """Build messages for /chat (general) mode — a plain assistant
        with workspace awareness but no mentor framing and no tools.

        The system prompt is intentionally tight so the model gives ONE
        focused answer per user turn instead of self-prompting like a
        coach (e.g. "let me know if you want me to dive deeper into X" →
        followed by it deciding to dive deeper anyway).
        """
        ctx_lines: list[str] = []
        if workspace_brief:
            ctx_lines.append(f"USER WORKSPACE: {workspace_brief}")
        if memory_ctx:
            ctx_lines.append("\nWHAT WE KNOW ABOUT THE USER:")
            for lt in memory_ctx[:6]:
                ctx_lines.append(f"- [{lt['kind']}] {lt['content']}")
        if workspace_ctx:
            ctx_lines.append("\nRELEVANT WORKSPACE CONTEXT:")
            for c in workspace_ctx[:8]:
                ctx_lines.append(f"- [{c['source']}] {c['title']}: {c['snippet']}")
        if common_ctx:
            ctx_lines.append("\nCOMMON INTERVIEW KB:")
            for c in common_ctx[:5]:
                ctx_lines.append(
                    f"- [{c['source']} / {c['category']}] {c['title']}: {c['snippet']}"
                )

        system = (
            "You are a helpful general-purpose assistant accessed over a "
            "messaging app (WhatsApp). Answer the user's question directly "
            "and concisely. Do NOT propose your own follow-up tasks, do "
            "NOT continue elaborating after a complete answer, and do NOT "
            "ask the user multiple questions back. One focused reply per "
            "turn. If the user references their workspace (projects, "
            "resumes, sessions), acknowledge what's there but don't browse "
            "code unless they ask explicitly. Keep replies short enough "
            "for a phone screen unless the user asks for depth."
        )
        if ctx_lines:
            system = system + "\n\n" + "\n".join(ctx_lines)

        history: list[ChatMessageDTO] = [
            ChatMessageDTO(role="system", content=system)
        ]
        for m in working_messages:
            role = m.get("role", "user")
            if role not in ("user", "assistant", "system"):
                role = "user"
            history.append(
                ChatMessageDTO(role=role, content=m.get("content", ""))
            )
        history.append(ChatMessageDTO(role="user", content=user_input))
        return history

    def _build_messages(
        self,
        *,
        working_messages: list[dict],
        memory_ctx: list[dict],
        proj_ctx: list[dict],
        resume_ctx: list[dict],
        common_ctx: list[dict],
        user_input: str,
        has_project: bool,
    ) -> list[ChatMessageDTO]:
        ctx_lines: list[str] = []
        episodic = [m for m in memory_ctx if m["source"] == "episodic_memory"]
        long_term = [m for m in memory_ctx if m["source"] == "long_term_memory"]
        if episodic:
            ctx_lines.append("RECENT SESSION SUMMARIES:")
            for s in episodic[:5]:
                ctx_lines.append(f"- {s['content']}")
        if long_term:
            ctx_lines.append("\nWHAT WE KNOW ABOUT YOU:")
            for lt in long_term[:6]:
                ctx_lines.append(f"- [{lt['kind']}] {lt['content']}")
        if proj_ctx:
            ctx_lines.append("\nRELEVANT PROJECT EVIDENCE (vector search):")
            for c in proj_ctx[:5]:
                ctx_lines.append(f"- {c['rel_path']}: {c['snippet']}")
        if resume_ctx:
            ctx_lines.append("\nRELEVANT RESUME CONTEXT:")
            for c in resume_ctx[:4]:
                ctx_lines.append(f"- {c['title']}: {c['snippet']}")
        if common_ctx:
            ctx_lines.append("\nRELEVANT COMMON KB (public interview prep):")
            for c in common_ctx[:6]:
                ctx_lines.append(
                    f"- [{c['source']} / {c['category']}] {c['title']}: {c['snippet']}"
                )

        system = (
            "You are an expert SWE/Applied AI interview coach (Mentor mode). "
            "Be concrete, kind, and reference the user's project when possible. "
            "If the user asks something not covered, explain general principles "
            "AND show how to apply them to their project. Clearly label whether "
            "evidence comes from the user's project/resume or from common interview KB."
        )
        if has_project:
            system += (
                "\n\nYou have read-only tools to inspect the user's project: "
                "`list_dir`, `read_file`, `grep`, `tree`. Use them when the "
                "vector evidence above is insufficient. Prefer ONE focused "
                "tool call at a time. When you've gathered enough, write the "
                "final answer in plain text (markdown-friendly) without "
                "calling tools."
            )
        if ctx_lines:
            system = system + "\n\n" + "\n".join(ctx_lines)

        history: list[ChatMessageDTO] = [
            ChatMessageDTO(role="system", content=system)
        ]
        for m in working_messages:
            role = m.get("role", "user")
            if role not in ("user", "assistant", "system"):
                role = "user"
            history.append(
                ChatMessageDTO(role=role, content=m.get("content", ""))
            )
        history.append(ChatMessageDTO(role="user", content=user_input))
        return history

    async def _load_fs(
        self, user_id: UUID, project_id: UUID
    ) -> ProjectFs | None:
        if self._blob is None:
            return None
        try:
            return await ProjectFs.from_blob(
                blob=self._blob, user_id=user_id, project_id=project_id
            )
        except Exception:
            return None

    # ------- general /chat entry -------

    async def general_stream(
        self,
        *,
        user_id: UUID,
        session_id: UUID | None,
        workspace_brief: str,
        user_input: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Plain LLM chat with memory recall but no project tools and
        no mentor framing. Used by /chat (general) mode."""
        retrieved = await self._retrieval.retrieve(
            RetrieveRequest(
                user_id=user_id,
                session_id=session_id,
                query=user_input,
                purpose=RetrievalPurpose.general_chat,
                top_k=18,
                per_source_top_k={
                    "working_memory": 12,
                    "long_term_memory": 5,
                    "project": 2,
                    "resume": 3,
                    "common_kb": 5,
                },
                context_char_budget=6500,
            )
        )
        messages = self._build_general_messages(
            working_messages=_working_messages(retrieved.chunks),
            memory_ctx=_memory_context(retrieved.chunks),
            workspace_brief=workspace_brief,
            workspace_ctx=_workspace_context(retrieved.chunks),
            common_ctx=_common_context(retrieved.chunks),
            user_input=user_input,
        )
        chunks: list[str] = []
        try:
            async for piece in self._gw.chat_stream(
                user_id=user_id,
                logical_model=self._model,
                messages=messages,
            ):
                if not piece:
                    continue
                chunks.append(piece)
                yield {"type": "token", "content": piece}
        except Exception as e:  # noqa: BLE001
            err = f"(LLM error: {e})"
            chunks.append(err)
            yield {"type": "token", "content": err}
        yield {"type": "done", "content": "".join(chunks)}

    # ------- main entry -------

    async def stream(
        self,
        *,
        user_id: UUID,
        session_id: UUID | None,
        project_id: UUID | None,
        user_input: str,
    ) -> AsyncIterator[dict[str, Any]]:
        fs: ProjectFs | None = None
        project_ids = [project_id] if project_id is not None else None
        if project_id is not None:
            fs = await self._load_fs(user_id, project_id)
        retrieved = await self._retrieval.retrieve(
            RetrieveRequest(
                user_id=user_id,
                session_id=session_id,
                query=user_input,
                purpose=RetrievalPurpose.mentor,
                project_ids=project_ids,
                top_k=18,
                per_source_top_k={
                    "working_memory": 12,
                    "episodic_memory": 5,
                    "long_term_memory": 6,
                    "project": 6,
                    "common_kb": 6,
                },
                context_char_budget=7000,
            )
        )

        messages = self._build_messages(
            working_messages=_working_messages(retrieved.chunks),
            memory_ctx=_memory_context(retrieved.chunks),
            proj_ctx=_project_context(retrieved.chunks),
            resume_ctx=_resume_context(retrieved.chunks),
            common_ctx=_common_context(retrieved.chunks),
            user_input=user_input,
            has_project=fs is not None,
        )

        chunks: list[str] = []

        # Tool loop (only if we have a project filesystem available).
        if fs is not None:
            runtime = ToolRuntime(fs)
            tools = project_tool_definitions()
            for turn in range(MAX_TOOL_TURNS):
                try:
                    resp = await self._gw.chat(
                        user_id=user_id,
                        logical_model=self._model,
                        messages=messages,
                        tools=tools,
                        tool_choice="auto",
                    )
                except Exception as e:  # noqa: BLE001
                    err = f"(LLM error: {e})"
                    yield {"type": "token", "content": err}
                    chunks.append(err)
                    yield {"type": "done", "content": "".join(chunks)}
                    return

                tool_calls = resp.tool_calls or []
                if not tool_calls:
                    # No more tool calls -> stream the final answer using a
                    # second pass without tools so we get token-level streaming.
                    if resp.content:
                        # Some models reply directly even with tools enabled.
                        for piece in _split_for_stream(resp.content):
                            chunks.append(piece)
                            yield {"type": "token", "content": piece}
                        yield {"type": "done", "content": "".join(chunks)}
                        return
                    break  # fall through to streaming pass

                # Surface tool calls + run each, append tool messages for next turn.
                assistant_msg = ChatMessageDTO(
                    role="assistant",
                    content=resp.content or "",
                    tool_calls=[
                        ToolCall(
                            id=tc.id,
                            type="function",
                            function=tc.function,
                        )
                        for tc in tool_calls
                    ],
                )
                messages.append(assistant_msg)

                for tc in tool_calls:
                    name = (tc.function or {}).get("name", "")
                    raw_args = (tc.function or {}).get("arguments", "") or ""
                    try:
                        parsed_args = (
                            json.loads(raw_args) if raw_args else {}
                        )
                    except Exception:
                        parsed_args = {"_raw": raw_args}
                    yield {
                        "type": "tool_call",
                        "name": name,
                        "args": parsed_args,
                    }
                    result = runtime.dispatch(name, raw_args)
                    yield {
                        "type": "tool_result",
                        "name": name,
                        "preview": result[:240],
                    }
                    messages.append(
                        ChatMessageDTO(
                            role="tool",
                            tool_call_id=tc.id,
                            name=name,
                            content=result,
                        )
                    )

                if runtime.used_chars >= MAX_TOTAL_RESULT_CHARS:
                    # Tell the model the budget is exhausted so it wraps up.
                    messages.append(
                        ChatMessageDTO(
                            role="system",
                            content=(
                                "Tool result budget exhausted. Synthesize a "
                                "final answer from gathered evidence."
                            ),
                        )
                    )
                    break

        # Streaming pass (no tools): produce the final answer to the user.
        try:
            async for piece in self._gw.chat_stream(
                user_id=user_id,
                logical_model=self._model,
                messages=messages,
            ):
                if not piece:
                    continue
                chunks.append(piece)
                yield {"type": "token", "content": piece}
        except Exception as e:  # noqa: BLE001
            err = f"(LLM error: {e})"
            chunks.append(err)
            yield {"type": "token", "content": err}

        yield {"type": "done", "content": "".join(chunks)}


def _split_for_stream(text: str, *, chunk: int = 40):
    """Yield small slices so non-streaming content still trickles to the UI."""
    for i in range(0, len(text), chunk):
        yield text[i : i + chunk]


def _working_messages(chunks: list[RetrievedChunk]) -> list[dict]:
    return [
        {
            "role": str(c.metadata.get("role") or "user"),
            "content": c.text,
        }
        for c in chunks
        if c.source == RetrievalSource.working_memory
    ]


def _memory_context(chunks: list[RetrievedChunk]) -> list[dict]:
    out: list[dict] = []
    for c in chunks:
        if c.source not in {
            RetrievalSource.episodic_memory,
            RetrievalSource.long_term_memory,
        }:
            continue
        out.append(
            {
                "source": c.source.value,
                "kind": str(c.metadata.get("kind") or c.title or "fact"),
                "content": c.text,
                "score": c.score,
            }
        )
    return out


def _project_context(chunks: list[RetrievedChunk]) -> list[dict]:
    return [
        {
            "rel_path": c.citation.rel_path or c.title or "",
            "snippet": c.text[:600],
            "score": c.score,
            "project_id": str(c.citation.project_id) if c.citation.project_id else None,
        }
        for c in chunks
        if c.source == RetrievalSource.project
    ]


def _resume_context(chunks: list[RetrievedChunk]) -> list[dict]:
    return [
        {"title": c.title or c.source.value, "snippet": c.text[:600], "score": c.score}
        for c in chunks
        if c.source in {RetrievalSource.resume, RetrievalSource.resume_claim}
    ]


def _workspace_context(chunks: list[RetrievedChunk]) -> list[dict]:
    out: list[dict] = []
    for c in chunks:
        if c.source == RetrievalSource.project:
            out.append(
                {
                    "source": "project",
                    "title": c.citation.rel_path or c.title or "",
                    "snippet": c.text[:500],
                }
            )
        elif c.source in {RetrievalSource.resume, RetrievalSource.resume_claim}:
            out.append(
                {
                    "source": c.source.value,
                    "title": c.title or "",
                    "snippet": c.text[:500],
                }
            )
    return out


def _common_context(chunks: list[RetrievedChunk]) -> list[dict]:
    return [
        {
            "title": c.title or "",
            "category": str(c.metadata.get("category") or "general"),
            "source": str(c.metadata.get("source") or "common"),
            "snippet": c.text[:500],
            "company": c.metadata.get("company"),
            "language": c.metadata.get("language"),
        }
        for c in chunks
        if c.source == RetrievalSource.common_kb
    ]
