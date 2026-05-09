"""AgentFacade implementation that bridges to core's mentor/interviewer
domain modules. Lives outside the SDK so the SDK stays platform-agnostic.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openinterview_db import ChatMessage, ChatSession, ClaimMapping, Project, Resume

from ..interviewer import InterviewerAgent, SessionEvaluator
from ..mentor import MentorAgent
from ..qa import QAGenerationService
from ..workspace import workspace_brief
from ...infra.db.chat_repository import SqlChatRepository
from ...infra.db.qa_repository import SqlQARepository
from .sdk.agent_facade import (
    AgentFacade,
    ProjectBrief,
    ResumeBrief,
    SessionBrief,
)


def _short(u: UUID) -> str:
    return str(u).split("-", 1)[0]


def _humanize_age(ts: datetime | None) -> str:
    if ts is None:
        return "?"
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = now - ts
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}h ago"
    days = hrs // 24
    return f"{days}d ago"


class CoreAgentFacade(AgentFacade):
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        mentor: MentorAgent,
        interviewer: InterviewerAgent,
        evaluator: SessionEvaluator,
        qa: QAGenerationService,
    ) -> None:
        self._sm = sessionmaker
        self._mentor = mentor
        self._interviewer = interviewer
        self._eval = evaluator
        self._qa = qa

    async def resolve_resume_id(
        self, *, user_id: UUID, name_or_id: str | None
    ) -> UUID | None:
        """Resolve a resume the same way ``get_resume_detail`` does — UUID
        first, then 8-char short-id prefix, then case-insensitive filename
        substring. ``None`` returns the most recent resume."""
        async with self._sm() as s:
            if not name_or_id:
                row = (
                    await s.execute(
                        select(Resume)
                        .where(Resume.user_id == user_id)
                        .order_by(Resume.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                return row.id if row else None
            # Try UUID exact match.
            try:
                rid = UUID(name_or_id)
            except (ValueError, AttributeError):
                rid = None
            if rid is not None:
                row = await s.get(Resume, rid)
                if row and row.user_id == user_id:
                    return row.id
            rows = (
                await s.execute(
                    select(Resume)
                    .where(Resume.user_id == user_id)
                    .order_by(Resume.created_at.desc())
                )
            ).scalars().all()
            low = name_or_id.lower()
            for r in rows:
                if str(r.id).lower().startswith(low):
                    return r.id
            for r in rows:
                if low in (r.original_filename or "").lower():
                    return r.id
        return None

    async def resolve_project_id(
        self, *, user_id: UUID, name_or_id: str | None
    ) -> UUID | None:
        if not name_or_id:
            # No name given — pick the user's most recently created ready project.
            async with self._sm() as s:
                row = (
                    await s.execute(
                        select(Project)
                        .where(Project.user_id == user_id, Project.status == "ready")
                        .order_by(Project.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                return row.id if row else None
        # Exact UUID match first, then case-insensitive name.
        try:
            pid = UUID(name_or_id)
        except (ValueError, AttributeError):
            pid = None
        async with self._sm() as s:
            if pid is not None:
                row = await s.get(Project, pid)
                if row and row.user_id == user_id:
                    return row.id
            row = (
                await s.execute(
                    select(Project)
                    .where(
                        Project.user_id == user_id,
                        Project.name.ilike(name_or_id),
                    )
                    .order_by(Project.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return row.id if row else None

    # ---------- mentor ------------------------------------------------------

    async def start_mentor_session(
        self, *, user_id: UUID, project_id: UUID | None
    ) -> tuple[UUID, str]:
        async with self._sm() as s:
            sess = await SqlChatRepository(s).create_session(
                user_id=user_id, mode="mentor", project_id=project_id, title=None
            )
            sid = sess.id
        opening = "Mentor mode is on. Ask anything about your project."
        return sid, opening

    async def send_mentor_message(
        self, *, user_id: UUID, session_id: UUID, content: str
    ) -> str:
        # Persist user message.
        async with self._sm() as s:
            await SqlChatRepository(s).append_message(
                session_id=session_id, user_id=user_id, role="user", content=content
            )
            sess = await SqlChatRepository(s).get_session(
                user_id=user_id, session_id=session_id
            )
            project_id = sess.project_id if sess else None

        # Stream tokens, collapse to final string.
        chunks: list[str] = []
        async for ev in self._mentor.stream(
            user_id=user_id,
            session_id=session_id,
            project_id=project_id,
            user_input=content,
        ):
            if ev.get("type") == "token":
                chunks.append(ev.get("content", ""))
        full = "".join(chunks).strip() or "(no response)"

        async with self._sm() as s:
            await SqlChatRepository(s).append_message(
                session_id=session_id,
                user_id=user_id,
                role="assistant",
                content=full,
            )
        return full

    # ---------- interviewer -------------------------------------------------

    async def start_interview_session(
        self,
        *,
        user_id: UUID,
        project_id: UUID,
        position: str,
        level: str,
    ) -> tuple[UUID, str]:
        async with self._sm() as s:
            qa_repo = SqlQARepository(s)
            qa_set = await qa_repo.get_or_create_set(
                user_id=user_id,
                project_id=project_id,
                position=position,
                level=level,
            )
            chat_repo = SqlChatRepository(s)
            sess = await chat_repo.create_session(
                user_id=user_id,
                mode="interviewer",
                project_id=project_id,
                title=f"Mock interview ({position}, {level})",
                target={
                    "qa_set_id": str(qa_set.id),
                    "position": position,
                    "level": level,
                    "n_questions": 5,
                    "asked_ids": [],
                    "current_question": "",
                    "current_ideal_answer": "",
                    "thread_state": {},
                },
            )
            await s.commit()
            sid = sess.id
            qa_set_id = qa_set.id
            qa_total = qa_set.total

        if qa_total == 0:
            return (
                sid,
                "Generating interview questions for this project — try /status in a few seconds.",
            )

        first = await self._interviewer.turn(
            user_id=user_id,
            session_id=sid,
            qa_set_id=qa_set_id,
            user_input="",
            asked_ids=set(),
            prev_question="",
            prev_ideal_answer="",
            thread_state={},
        )
        question = first.get("chosen_question") or "Tell me about this project."
        opening = f"Question 1:\n{question}"

        # Persist + update target.
        async with self._sm() as s:
            chat_repo = SqlChatRepository(s)
            await chat_repo.append_message(
                session_id=sid,
                user_id=user_id,
                role="assistant",
                content=opening,
                meta={
                    "opening": True,
                    "next_action": first.get("next_action"),
                    "follow_up_axis": first.get("follow_up_axis"),
                    "thread_state": first.get("thread_state"),
                },
            )
            row = await chat_repo.get_session(user_id=user_id, session_id=sid)
            if row is not None:
                new_target = dict(row.target or {})
                new_target["asked_ids"] = [str(i) for i in first.get("asked_ids", set())]
                new_target["current_question"] = first.get("chosen_question", "")
                new_target["current_ideal_answer"] = first.get("ideal_answer", "")
                new_target["thread_state"] = first.get("thread_state") or {}
                row.target = new_target
            await s.commit()
        return sid, opening

    async def start_interview_session_for_resume(
        self,
        *,
        user_id: UUID,
        resume_id: UUID,
        position: str,
        level: str,
    ) -> tuple[UUID, str]:
        """Resume-driven kickoff over WhatsApp / messaging. Mirrors
        :meth:`start_interview_session` but routes through the resume QA
        pipeline. The session has no pinned ``project_id``; the question
        header surfaces the claim being probed."""
        async with self._sm() as s:
            resume = await s.get(Resume, resume_id)
            if resume is None or resume.user_id != user_id:
                return (UUID(int=0), "Resume not found.")
            qa_repo = SqlQARepository(s)
            qa_set = await qa_repo.get_or_create_set_for_resume(
                user_id=user_id,
                resume_id=resume_id,
                position=position,
                level=level,
            )
            chat_repo = SqlChatRepository(s)
            fname = (resume.original_filename or "resume").rsplit(".", 1)[0][:40]
            sess = await chat_repo.create_session(
                user_id=user_id,
                mode="interviewer",
                project_id=None,
                title=f"Mock interview ({position}, {level}) — {fname}",
                target={
                    "qa_set_id": str(qa_set.id),
                    "scope": "resume",
                    "resume_id": str(resume_id),
                    "resume_filename": resume.original_filename,
                    "position": position,
                    "level": level,
                    "n_questions": 5,
                    "asked_ids": [],
                    "recent_claims": [],
                    "current_question": "",
                    "current_ideal_answer": "",
                    "thread_state": {},
                },
            )
            await s.commit()
            sid = sess.id
            qa_set_id = qa_set.id
            qa_total = qa_set.total

        if qa_total == 0:
            import asyncio as _asyncio

            _asyncio.create_task(
                self._qa.run_for_resume(
                    user_id=user_id,
                    resume_id=resume_id,
                    position=position,
                    level=level,
                )
            )
            return (
                sid,
                "Generating interview questions from your resume — "
                "try /status in a few seconds.",
            )

        first = await self._interviewer.turn(
            user_id=user_id,
            session_id=sid,
            qa_set_id=qa_set_id,
            user_input="",
            asked_ids=set(),
            prev_question="",
            prev_ideal_answer="",
            recent_claims=[],
            thread_state={},
        )
        question = first.get("chosen_question") or "Tell me about a recent project."
        claim = first.get("claim")
        opening = (
            f"About this on your resume:\n> {claim}\n\nQuestion 1:\n{question}"
            if claim
            else f"Question 1:\n{question}"
        )

        async with self._sm() as s:
            chat_repo = SqlChatRepository(s)
            await chat_repo.append_message(
                session_id=sid,
                user_id=user_id,
                role="assistant",
                content=opening,
                meta={
                    "opening": True,
                    "next_action": first.get("next_action"),
                    "follow_up_axis": first.get("follow_up_axis"),
                    "thread_state": first.get("thread_state"),
                },
            )
            row = await chat_repo.get_session(user_id=user_id, session_id=sid)
            if row is not None:
                new_target = dict(row.target or {})
                new_target["asked_ids"] = [
                    str(i) for i in first.get("asked_ids", set())
                ]
                new_target["recent_claims"] = first.get("recent_claims", [])
                new_target["current_question"] = first.get("chosen_question", "")
                new_target["current_ideal_answer"] = first.get("ideal_answer", "")
                new_target["thread_state"] = first.get("thread_state") or {}
                row.target = new_target
            await s.commit()
        return sid, opening

    async def send_interview_message(
        self, *, user_id: UUID, session_id: UUID, content: str
    ) -> str:
        async with self._sm() as s:
            chat_repo = SqlChatRepository(s)
            sess = await chat_repo.get_session(
                user_id=user_id, session_id=session_id
            )
            if sess is None:
                return "Session not found."
            target = dict(sess.target or {})
            qa_set_id = (
                UUID(target.get("qa_set_id")) if target.get("qa_set_id") else None
            )
            asked_ids = {UUID(x) for x in target.get("asked_ids", [])}
            prev_q = str(target.get("current_question") or "")
            prev_a = str(target.get("current_ideal_answer") or "")
            recent_claims = [str(c) for c in (target.get("recent_claims") or [])]
            thread_state = (
                target.get("thread_state")
                if isinstance(target.get("thread_state"), dict)
                else {}
            )
            await chat_repo.append_message(
                session_id=session_id, user_id=user_id, role="user", content=content
            )
            await s.commit()

        if qa_set_id is None:
            return "This interview session is missing its question bank."

        result = await self._interviewer.turn(
            user_id=user_id,
            session_id=session_id,
            qa_set_id=qa_set_id,
            user_input=content,
            asked_ids=asked_ids,
            prev_question=prev_q,
            prev_ideal_answer=prev_a,
            recent_claims=recent_claims,
            thread_state=thread_state,
        )
        text = result.get("final", "").strip() or "(no response)"

        async with self._sm() as s:
            chat_repo = SqlChatRepository(s)
            await chat_repo.append_message(
                session_id=session_id,
                user_id=user_id,
                role="assistant",
                content=text,
                meta={
                    "evaluation": result.get("evaluation"),
                    "next_action": result.get("next_action"),
                    "follow_up_axis": result.get("follow_up_axis"),
                    "thread_state": result.get("thread_state"),
                },
            )
            row = await chat_repo.get_session(user_id=user_id, session_id=session_id)
            if row is not None:
                new_target = dict(row.target or {})
                new_target["asked_ids"] = [str(i) for i in result.get("asked_ids", set())]
                new_target["recent_claims"] = result.get("recent_claims", [])
                new_target["current_question"] = result.get("chosen_question", "")
                new_target["current_ideal_answer"] = result.get("ideal_answer", "")
                new_target["thread_state"] = result.get("thread_state") or {}
                row.target = new_target
            await s.commit()
        return text

    # ---------- end ---------------------------------------------------------

    async def end_session(
        self, *, user_id: UUID, session_id: UUID, mode: str
    ) -> str:
        async with self._sm() as s:
            chat_repo = SqlChatRepository(s)
            sess = await chat_repo.get_session(
                user_id=user_id, session_id=session_id
            )
            if sess is None:
                return "Session not found."
            if sess.status != "ended":
                await chat_repo.end_session(session_id=session_id)
            await s.commit()

        if mode == "mentor":
            return "Mentor session ended."

        try:
            await self._eval.evaluate(user_id=user_id, session_id=session_id)
        except Exception:
            return "Interview ended. Evaluation could not be generated."

        async with self._sm() as s:
            chat_repo = SqlChatRepository(s)
            ev = await chat_repo.get_evaluation(user_id=user_id, session_id=session_id)
        if ev is None:
            return "Interview ended."
        lines = [
            "Interview ended.",
            f"Overall score: {ev.overall_score:.1f} / 5",
        ]
        if ev.summary:
            lines.append(f"Summary: {ev.summary}")
        if ev.strengths:
            lines.append("Strengths: " + "; ".join(ev.strengths))
        if ev.weaknesses:
            lines.append("Weaknesses: " + "; ".join(ev.weaknesses))
        return "\n".join(lines)

    # ---------- general /chat mode -----------------------------------------

    async def start_general_session(
        self, *, user_id: UUID
    ) -> tuple[UUID, str]:
        """Open a workspace-wide chat session.

        We persist it as ``mode='general'`` with no project pin so the
        existing mentor agent runs in cross-workspace mode. The opener
        is intentionally short — users in /chat mode mostly want to
        start typing immediately.
        """
        async with self._sm() as s:
            sess = await SqlChatRepository(s).create_session(
                user_id=user_id, mode="general", project_id=None, title=None
            )
            sid = sess.id
        return sid, "Chat mode is on. Ask anything."

    async def send_general_message(
        self, *, user_id: UUID, session_id: UUID, content: str
    ) -> str:
        # /chat uses a dedicated streaming entry on MentorAgent that has
        # no mentor framing and no project tools — just memory recall +
        # plain LLM. This avoids the "let me dive deeper into X" loop the
        # full mentor prompt was inducing on workspace-less questions.
        ws_ctx = await workspace_brief(sessionmaker=self._sm, user_id=user_id)

        async with self._sm() as s:
            await SqlChatRepository(s).append_message(
                session_id=session_id, user_id=user_id, role="user", content=content
            )
            await s.commit()

        chunks: list[str] = []
        async for ev in self._mentor.general_stream(
            user_id=user_id,
            session_id=session_id,
            workspace_brief=ws_ctx,
            user_input=content,
        ):
            if ev.get("type") == "token":
                chunks.append(ev.get("content", ""))
        full = "".join(chunks).strip() or "(no response)"

        async with self._sm() as s:
            await SqlChatRepository(s).append_message(
                session_id=session_id,
                user_id=user_id,
                role="assistant",
                content=full,
            )
            await s.commit()
        return full



    # ---------- workspace introspection ------------------------------------

    async def list_projects(
        self, *, user_id: UUID, limit: int = 10
    ) -> list[ProjectBrief]:
        async with self._sm() as s:
            rows = (
                await s.execute(
                    select(Project)
                    .where(Project.user_id == user_id)
                    .order_by(Project.created_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
        return [
            ProjectBrief(
                id=r.id,
                name=r.name,
                status=r.status,
                short_id=_short(r.id),
            )
            for r in rows
        ]

    async def list_resumes(
        self, *, user_id: UUID, limit: int = 10
    ) -> list[ResumeBrief]:
        async with self._sm() as s:
            rows = (
                await s.execute(
                    select(Resume)
                    .where(Resume.user_id == user_id)
                    .order_by(Resume.created_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
            briefs: list[ResumeBrief] = []
            for r in rows:
                claims = (r.parsed or {}).get("claims") if isinstance(r.parsed, dict) else None
                n_claims = len(claims) if isinstance(claims, list) else 0
                n_mapped = (
                    await s.execute(
                        select(func.count(ClaimMapping.id)).where(
                            ClaimMapping.user_id == user_id,
                            ClaimMapping.resume_id == r.id,
                            ClaimMapping.project_id.isnot(None),
                        )
                    )
                ).scalar_one()
                briefs.append(
                    ResumeBrief(
                        id=r.id,
                        filename=r.original_filename,
                        n_claims=n_claims,
                        n_mapped=int(n_mapped or 0),
                        short_id=_short(r.id),
                    )
                )
        return briefs

    async def get_resume_detail(
        self, *, user_id: UUID, name_or_id: str
    ) -> str | None:
        async with self._sm() as s:
            row: Resume | None = None
            try:
                rid = UUID(name_or_id)
                cand = await s.get(Resume, rid)
                if cand and cand.user_id == user_id:
                    row = cand
            except (ValueError, AttributeError):
                pass
            if row is None:
                # Prefix match on UUID first (so users can type 8-char prefix).
                rows = (
                    await s.execute(
                        select(Resume)
                        .where(Resume.user_id == user_id)
                        .order_by(Resume.created_at.desc())
                    )
                ).scalars().all()
                low = name_or_id.lower()
                for r in rows:
                    if str(r.id).lower().startswith(low):
                        row = r
                        break
                if row is None:
                    for r in rows:
                        if low in (r.original_filename or "").lower():
                            row = r
                            break
            if row is None:
                return None

            parsed = row.parsed if isinstance(row.parsed, dict) else {}
            summary = parsed.get("summary") or "(no summary)"
            role = parsed.get("role") or parsed.get("title") or ""
            skills = parsed.get("skills") or []
            claims = parsed.get("claims") or []
            n_mapped = (
                await s.execute(
                    select(func.count(ClaimMapping.id)).where(
                        ClaimMapping.user_id == user_id,
                        ClaimMapping.resume_id == row.id,
                        ClaimMapping.project_id.isnot(None),
                    )
                )
            ).scalar_one()

        lines: list[str] = []
        lines.append(f"Resume: {row.original_filename}  ({_short(row.id)})")
        if role:
            lines.append(f"Role: {role}")
        lines.append(f"Summary: {summary}")
        if skills:
            top_skills = skills[:10] if isinstance(skills, list) else [str(skills)]
            lines.append("Top skills: " + ", ".join(str(x) for x in top_skills))
        lines.append(
            f"Claims: {len(claims) if isinstance(claims, list) else 0} "
            f"({int(n_mapped or 0)} mapped to projects)"
        )
        if isinstance(claims, list) and claims:
            lines.append("\nClaims:")
            for i, c in enumerate(claims[:15], 1):
                if isinstance(c, dict):
                    lines.append(f"  {i}. {c.get('text') or c.get('claim') or c}")
                else:
                    lines.append(f"  {i}. {c}")
            if len(claims) > 15:
                lines.append(f"  … and {len(claims) - 15} more")
        return "\n".join(lines)

    async def list_sessions(
        self, *, user_id: UUID, limit: int = 10
    ) -> list[SessionBrief]:
        async with self._sm() as s:
            rows = (
                await s.execute(
                    select(ChatSession)
                    .where(ChatSession.user_id == user_id)
                    .order_by(ChatSession.created_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
            # Bulk-load project names for the rows that pin a project.
            pids = {r.project_id for r in rows if r.project_id}
            name_by_pid: dict[UUID, str] = {}
            if pids:
                proj_rows = (
                    await s.execute(
                        select(Project).where(Project.id.in_(pids))
                    )
                ).scalars().all()
                name_by_pid = {p.id: p.name for p in proj_rows}
        out: list[SessionBrief] = []
        for r in rows:
            out.append(
                SessionBrief(
                    id=r.id,
                    mode=r.mode,
                    project_name=name_by_pid.get(r.project_id) if r.project_id else None,
                    turn_count=r.turn_count,
                    status=r.status,
                    age_human=_humanize_age(r.created_at),
                    short_id=_short(r.id),
                )
            )
        return out

    async def resume_session(
        self, *, user_id: UUID, id_prefix: str
    ) -> tuple[UUID, str, str] | None:
        if not id_prefix:
            return None
        low = id_prefix.lower().strip()
        async with self._sm() as s:
            rows = (
                await s.execute(
                    select(ChatSession)
                    .where(ChatSession.user_id == user_id)
                    .order_by(ChatSession.created_at.desc())
                )
            ).scalars().all()
            match: ChatSession | None = None
            for r in rows:
                if str(r.id).lower().startswith(low):
                    match = r
                    break
            if match is None:
                return None
            if match.status == "ended":
                return (
                    match.id,
                    match.mode,
                    f"Session {_short(match.id)} is already ended — start a new one.",
                )
            # Fetch last assistant message for context preview.
            last_assistant = (
                await s.execute(
                    select(ChatMessage)
                    .where(
                        ChatMessage.session_id == match.id,
                        ChatMessage.role == "assistant",
                    )
                    .order_by(ChatMessage.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        preview = ""
        if last_assistant is not None:
            txt = (last_assistant.content or "").strip()
            preview = txt if len(txt) <= 200 else txt[:200] + "…"
        opener_lines = [
            f"Resumed {match.mode} session ({_short(match.id)}, "
            f"{match.turn_count} turns)."
        ]
        if preview:
            opener_lines.append(f"Last assistant said:\n{preview}")
        opener_lines.append("Continue the conversation.")
        return match.id, match.mode, "\n\n".join(opener_lines)

    async def whoami_counts(
        self, *, user_id: UUID
    ) -> dict[str, int]:
        async with self._sm() as s:
            n_projects = (
                await s.execute(
                    select(func.count(Project.id)).where(Project.user_id == user_id)
                )
            ).scalar_one()
            n_resumes = (
                await s.execute(
                    select(func.count(Resume.id)).where(Resume.user_id == user_id)
                )
            ).scalar_one()
            n_sessions_total = (
                await s.execute(
                    select(func.count(ChatSession.id)).where(
                        ChatSession.user_id == user_id
                    )
                )
            ).scalar_one()
            n_sessions_active = (
                await s.execute(
                    select(func.count(ChatSession.id)).where(
                        ChatSession.user_id == user_id,
                        ChatSession.status == "active",
                    )
                )
            ).scalar_one()
        return {
            "projects": int(n_projects or 0),
            "resumes": int(n_resumes or 0),
            "sessions_total": int(n_sessions_total or 0),
            "sessions_active": int(n_sessions_active or 0),
        }
