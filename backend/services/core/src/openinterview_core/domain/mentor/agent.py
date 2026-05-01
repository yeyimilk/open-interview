"""Mentor agent.

Uses a small LangGraph state machine:

  recall_memory -> retrieve_project_context -> respond_stream -> END

Each node is async. We intentionally keep tools out of the loop for now -- the
respond node calls the gateway directly so we have a stable streaming API.
We use the compiled graph to validate state shape and to enable checkpointing
later (LangGraph's MemorySaver integrates trivially when needed).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from openinterview_schemas import ChatMessage as ChatMessageDTO

from ...infra.vector import (
    VectorStore,
    vector_collection_for_user_project,
)
from ..memory.recall import MemoryRetriever, RecallResult
from ..projects.embedder import GatewayEmbedder


class _State(TypedDict, total=False):
    user_id: UUID
    session_id: UUID | None
    project_id: UUID | None
    user_input: str
    recalled: RecallResult
    project_context: list[dict]
    chunk: str  # streamed pieces of assistant message (for non-streaming path: full final content)
    final: str


class MentorAgent:
    def __init__(
        self,
        *,
        gateway,
        embedder: GatewayEmbedder,
        vector_store: VectorStore,
        retriever: MemoryRetriever,
        chat_logical_model: str = "chat-fast",
    ) -> None:
        self._gw = gateway
        self._embed = embedder
        self._vs = vector_store
        self._retriever = retriever
        self._model = chat_logical_model
        self._graph = self._build_graph()

    def _build_graph(self):
        g = StateGraph(_State)

        async def recall_memory(state: _State) -> dict:
            recalled = await self._retriever.recall(
                user_id=state["user_id"],
                session_id=state.get("session_id"),
                query=state["user_input"],
            )
            return {"recalled": recalled}

        async def retrieve_project(state: _State) -> dict:
            pid = state.get("project_id")
            if not pid:
                return {"project_context": []}
            try:
                vecs = await self._embed.embed(
                    user_id=state["user_id"], texts=[state["user_input"]]
                )
                if not vecs:
                    return {"project_context": []}
                coll = vector_collection_for_user_project(
                    str(state["user_id"]), str(pid)
                )
                matches = await self._vs.query(
                    collection=coll, embedding=vecs[0], k=6
                )
                ctx = [
                    {
                        "rel_path": (m.metadata or {}).get("rel_path", ""),
                        "snippet": m.text[:600],
                        "score": m.score,
                    }
                    for m in matches
                ]
                return {"project_context": ctx}
            except Exception:
                return {"project_context": []}

        async def respond(state: _State) -> dict:
            messages = self._build_messages(state)
            try:
                resp = await self._gw.chat(
                    user_id=state["user_id"],
                    logical_model=self._model,
                    messages=messages,
                )
                content = resp.content
            except Exception as e:
                content = f"(LLM error: {e})"
            return {"final": content}

        g.add_node("recall", recall_memory)
        g.add_node("retrieve", retrieve_project)
        g.add_node("respond", respond)
        g.add_edge(START, "recall")
        g.add_edge("recall", "retrieve")
        g.add_edge("retrieve", "respond")
        g.add_edge("respond", END)
        return g.compile()

    def _build_messages(self, state: _State) -> list[ChatMessageDTO]:
        recalled = state.get("recalled")
        ctx_lines: list[str] = []
        if recalled:
            if recalled.episodic_summaries:
                ctx_lines.append("RECENT SESSION SUMMARIES:")
                for s in recalled.episodic_summaries[:5]:
                    ctx_lines.append(f"- {s}")
            if recalled.long_term:
                ctx_lines.append("\nWHAT WE KNOW ABOUT YOU:")
                for lt in recalled.long_term[:6]:
                    ctx_lines.append(f"- [{lt.kind}] {lt.content}")
        proj = state.get("project_context") or []
        if proj:
            ctx_lines.append("\nRELEVANT PROJECT EVIDENCE:")
            for c in proj[:5]:
                ctx_lines.append(f"- {c['rel_path']}: {c['snippet']}")

        system = (
            "You are an expert SWE/Applied AI interview coach (Mentor mode). "
            "Be concrete, kind, and reference the user's project when possible. "
            "If the user asks something not covered, explain general principles AND "
            "show how to apply them to their project."
        )
        if ctx_lines:
            system = system + "\n\n" + "\n".join(ctx_lines)

        history: list[ChatMessageDTO] = [ChatMessageDTO(role="system", content=system)]
        for m in (recalled.working_messages if recalled else []):
            role = m.get("role", "user")
            if role not in ("user", "assistant", "system"):
                role = "user"
            history.append(ChatMessageDTO(role=role, content=m.get("content", "")))
        history.append(ChatMessageDTO(role="user", content=state["user_input"]))
        return history

    async def stream(
        self,
        *,
        user_id: UUID,
        session_id: UUID | None,
        project_id: UUID | None,
        user_input: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yields events: {'type': 'token', 'content': str} and {'type': 'done', 'content': str}.

        Real token streaming: we run the recall + retrieve nodes (cheap, non-LLM)
        directly to assemble the prompt, then stream the chat-completion deltas
        from the gateway and forward each delta as a 'token' event.
        """
        state: _State = {
            "user_id": user_id,
            "session_id": session_id,
            "project_id": project_id,
            "user_input": user_input,
        }
        # Run pre-LLM nodes inline so we keep their effects but don't wait on the
        # LLM before streaming begins.
        # 1) recall memory
        recalled = await self._retriever.recall(
            user_id=user_id, session_id=session_id, query=user_input
        )
        state["recalled"] = recalled
        # 2) project context
        proj_ctx: list[dict] = []
        if project_id is not None:
            try:
                vecs = await self._embed.embed(user_id=user_id, texts=[user_input])
                if vecs:
                    coll = vector_collection_for_user_project(
                        str(user_id), str(project_id)
                    )
                    matches = await self._vs.query(
                        collection=coll, embedding=vecs[0], k=6
                    )
                    proj_ctx = [
                        {
                            "rel_path": (m.metadata or {}).get("rel_path", ""),
                            "snippet": m.text[:600],
                            "score": m.score,
                        }
                        for m in matches
                    ]
            except Exception:
                proj_ctx = []
        state["project_context"] = proj_ctx

        # 3) stream LLM response
        messages = self._build_messages(state)
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

        full = "".join(chunks)
        yield {"type": "done", "content": full}
