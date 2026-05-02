"""Narrow facade the kernel uses to drive mentor/interviewer agents.

Implementations live in core's domain layer; the SDK depends only on
this Protocol so that one day messengers can be split into a separate
service that talks to core over HTTP.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(slots=True)
class ProjectBrief:
    id: UUID
    name: str
    status: str
    short_id: str  # first 8 chars of id, for users to type


@dataclass(slots=True)
class ResumeBrief:
    id: UUID
    filename: str
    n_claims: int
    n_mapped: int
    short_id: str


@dataclass(slots=True)
class SessionBrief:
    id: UUID
    mode: str  # mentor | interviewer | general | chat
    project_name: str | None
    turn_count: int
    status: str  # active | ended
    age_human: str  # "2h ago"
    short_id: str


class AgentFacade(Protocol):
    """All session lifecycle + turn dispatch the kernel needs."""

    async def resolve_project_id(
        self, *, user_id: UUID, name_or_id: str | None
    ) -> UUID | None: ...

    async def resolve_resume_id(
        self, *, user_id: UUID, name_or_id: str | None
    ) -> UUID | None:
        """Resolve a resume by UUID, short-id prefix, or filename match.

        ``None`` for ``name_or_id`` means "most recent resume". Returns
        ``None`` if the user has no resumes (or the lookup fails)."""
        ...

    async def start_mentor_session(
        self, *, user_id: UUID, project_id: UUID | None
    ) -> tuple[UUID, str]:
        """Returns (chat_session_id, opening_text)."""
        ...

    async def send_mentor_message(
        self, *, user_id: UUID, session_id: UUID, content: str
    ) -> str: ...

    async def start_interview_session(
        self,
        *,
        user_id: UUID,
        project_id: UUID,
        position: str,
        level: str,
    ) -> tuple[UUID, str]:
        """Returns (chat_session_id, first_question_text). Project-scoped."""
        ...

    async def start_interview_session_for_resume(
        self,
        *,
        user_id: UUID,
        resume_id: UUID,
        position: str,
        level: str,
    ) -> tuple[UUID, str]:
        """Resume-driven counterpart. Returns (chat_session_id, opener)."""
        ...

    async def send_interview_message(
        self, *, user_id: UUID, session_id: UUID, content: str
    ) -> str: ...

    async def end_session(
        self, *, user_id: UUID, session_id: UUID, mode: str
    ) -> str:
        """Mark the session ended and return a human summary."""
        ...

    # ---- general /chat mode (workspace-wide) -----------------------------

    async def start_general_session(
        self, *, user_id: UUID
    ) -> tuple[UUID, str]: ...

    async def send_general_message(
        self, *, user_id: UUID, session_id: UUID, content: str
    ) -> str: ...

    # ---- workspace introspection -----------------------------------------

    async def list_projects(
        self, *, user_id: UUID, limit: int = 10
    ) -> list[ProjectBrief]: ...

    async def list_resumes(
        self, *, user_id: UUID, limit: int = 10
    ) -> list[ResumeBrief]: ...

    async def get_resume_detail(
        self, *, user_id: UUID, name_or_id: str
    ) -> str | None:
        """Returns a formatted human string, or None if not found."""
        ...

    async def list_sessions(
        self, *, user_id: UUID, limit: int = 10
    ) -> list[SessionBrief]: ...

    async def resume_session(
        self, *, user_id: UUID, id_prefix: str
    ) -> tuple[UUID, str, str] | None:
        """Returns (chat_session_id, mode, opener) or None if not found."""
        ...

    async def whoami_counts(
        self, *, user_id: UUID
    ) -> dict[str, int]:
        """Returns {projects: N, resumes: N, sessions_active: N, sessions_total: N}."""
        ...
