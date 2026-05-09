from __future__ import annotations

import json
from datetime import date, datetime
from io import BytesIO
from typing import Any
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import (
    ChatMessage,
    ChatSession,
    ClaimMapping,
    EpisodicMemory,
    GatewayUsageLog,
    IngestRun,
    InterviewEvaluation,
    LongTermMemory,
    MessengerActiveSession,
    MessengerFilter,
    MessengerLink,
    MessengerPairToken,
    Project,
    ProjectDiagram,
    ProjectFile,
    QAGenerationRun,
    QAGenerationShard,
    QAItem,
    QASet,
    Resume,
    User,
    UserApiKey,
    UserInterviewPreference,
    UserModelPreference,
)
from openinterview_logging import get_logger
from openinterview_storage import paths

from ...infra.vector import (
    vector_collection_for_user_memory,
    vector_collection_for_user_project,
    vector_collection_for_user_qa,
)

log = get_logger(__name__)


class DataPortabilityService:
    def __init__(self, *, session: AsyncSession, blob, vector_store) -> None:
        self._s = session
        self._blob = blob
        self._vector = vector_store

    async def export_user_zip(self, *, user_id: UUID) -> bytes:
        user = await self._s.get(User, user_id)
        if user is None:
            raise ValueError("user not found")

        payload = await self._export_payload(user)
        out = BytesIO()
        with ZipFile(out, mode="w", compression=ZIP_DEFLATED) as zf:
            zf.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format": "open-interview-user-export-v1",
                        "generated_at": datetime.utcnow().isoformat() + "Z",
                        "user_id": str(user_id),
                    },
                    indent=2,
                ),
            )
            zf.writestr("data.json", json.dumps(payload, indent=2, sort_keys=True))
            await self._write_user_blobs(zf, user_id=user_id)
        return out.getvalue()

    async def wipe_user_data(self, *, user_id: UUID) -> dict[str, Any]:
        project_ids = [
            row[0]
            for row in (
                await self._s.execute(select(Project.id).where(Project.user_id == user_id))
            ).all()
        ]
        link_ids = [
            row[0]
            for row in (
                await self._s.execute(
                    select(MessengerLink.id).where(MessengerLink.user_id == user_id)
                )
            ).all()
        ]

        counts: dict[str, int] = {}

        async def _delete(name: str, stmt) -> None:
            result = await self._s.execute(stmt)
            counts[name] = int(result.rowcount or 0)

        if link_ids:
            await _delete(
                "messenger_filters",
                delete(MessengerFilter).where(MessengerFilter.link_id.in_(link_ids)),
            )
        await _delete(
            "messenger_active_sessions",
            delete(MessengerActiveSession).where(MessengerActiveSession.user_id == user_id),
        )
        await _delete(
            "messenger_pair_tokens",
            delete(MessengerPairToken).where(MessengerPairToken.user_id == user_id),
        )
        await _delete(
            "messenger_links",
            delete(MessengerLink).where(MessengerLink.user_id == user_id),
        )

        await _delete(
            "episodic_memories",
            delete(EpisodicMemory).where(EpisodicMemory.user_id == user_id),
        )
        await _delete(
            "long_term_memories",
            delete(LongTermMemory).where(LongTermMemory.user_id == user_id),
        )
        await _delete(
            "interview_evaluations",
            delete(InterviewEvaluation).where(InterviewEvaluation.user_id == user_id),
        )
        await _delete(
            "chat_messages",
            delete(ChatMessage).where(ChatMessage.user_id == user_id),
        )
        await _delete(
            "chat_sessions",
            delete(ChatSession).where(ChatSession.user_id == user_id),
        )

        await _delete("qa_items", delete(QAItem).where(QAItem.user_id == user_id))
        await _delete(
            "qa_generation_shards",
            delete(QAGenerationShard).where(QAGenerationShard.qa_set_id.in_(select(QASet.id).where(QASet.user_id == user_id))),
        )
        await _delete(
            "qa_generation_runs",
            delete(QAGenerationRun).where(QAGenerationRun.user_id == user_id),
        )
        await _delete("qa_sets", delete(QASet).where(QASet.user_id == user_id))
        await _delete(
            "claim_mappings",
            delete(ClaimMapping).where(ClaimMapping.user_id == user_id),
        )
        await _delete("resumes", delete(Resume).where(Resume.user_id == user_id))

        await _delete(
            "project_diagrams",
            delete(ProjectDiagram).where(ProjectDiagram.user_id == user_id),
        )
        await _delete(
            "project_files",
            delete(ProjectFile).where(ProjectFile.user_id == user_id),
        )
        await _delete(
            "ingest_runs",
            delete(IngestRun).where(IngestRun.user_id == user_id),
        )
        await _delete("projects", delete(Project).where(Project.user_id == user_id))

        await _delete(
            "user_api_keys",
            delete(UserApiKey).where(UserApiKey.user_id == user_id),
        )
        await _delete(
            "user_model_preferences",
            delete(UserModelPreference).where(UserModelPreference.user_id == user_id),
        )
        await _delete(
            "user_interview_preferences",
            delete(UserInterviewPreference).where(
                UserInterviewPreference.user_id == user_id
            ),
        )
        await _delete(
            "gateway_usage_log",
            delete(GatewayUsageLog).where(GatewayUsageLog.user_id == user_id),
        )
        await self._s.commit()

        vector_deleted = await self._delete_user_vectors(
            user_id=user_id, project_ids=project_ids
        )
        blob_deleted = await self._delete_user_blobs(user_id=user_id)
        log.info(
            "user_data_wiped",
            user_id=str(user_id),
            row_counts=counts,
            vector_deleted=vector_deleted,
            blob_deleted=blob_deleted,
        )
        return {
            "status": "ok",
            "deleted": counts,
            "vectors": vector_deleted,
            "blobs": blob_deleted,
        }

    async def _export_payload(self, user: User) -> dict[str, Any]:
        user_id = user.id
        links = await _rows(self._s, MessengerLink, MessengerLink.user_id == user_id)
        link_ids = [UUID(row["id"]) for row in links]
        filters: list[dict[str, Any]] = []
        if link_ids:
            filters = await _rows(
                self._s, MessengerFilter, MessengerFilter.link_id.in_(link_ids)
            )

        return {
            "user": _row_to_dict(user, exclude={"password_hash"}),
            "api_keys": await _rows(
                self._s, UserApiKey, UserApiKey.user_id == user_id, exclude={"encrypted_key"}
            ),
            "model_preferences": await _rows(
                self._s, UserModelPreference, UserModelPreference.user_id == user_id
            ),
            "projects": await _rows(self._s, Project, Project.user_id == user_id),
            "project_files": await _rows(self._s, ProjectFile, ProjectFile.user_id == user_id),
            "project_diagrams": await _rows(
                self._s, ProjectDiagram, ProjectDiagram.user_id == user_id
            ),
            "ingest_runs": await _rows(self._s, IngestRun, IngestRun.user_id == user_id),
            "resumes": await _rows(self._s, Resume, Resume.user_id == user_id),
            "claim_mappings": await _rows(
                self._s, ClaimMapping, ClaimMapping.user_id == user_id
            ),
            "qa_sets": await _rows(self._s, QASet, QASet.user_id == user_id),
            "qa_generation_runs": await _rows(
                self._s, QAGenerationRun, QAGenerationRun.user_id == user_id
            ),
            "qa_generation_shards": await _rows(
                self._s,
                QAGenerationShard,
                QAGenerationShard.qa_set_id.in_(select(QASet.id).where(QASet.user_id == user_id)),
            ),
            "qa_items": await _rows(self._s, QAItem, QAItem.user_id == user_id),
            "chat_sessions": await _rows(
                self._s, ChatSession, ChatSession.user_id == user_id
            ),
            "chat_messages": await _rows(self._s, ChatMessage, ChatMessage.user_id == user_id),
            "interview_evaluations": await _rows(
                self._s, InterviewEvaluation, InterviewEvaluation.user_id == user_id
            ),
            "episodic_memories": await _rows(
                self._s, EpisodicMemory, EpisodicMemory.user_id == user_id
            ),
            "long_term_memories": await _rows(
                self._s, LongTermMemory, LongTermMemory.user_id == user_id
            ),
            "messenger_links": links,
            "messenger_filters": filters,
            "messenger_active_sessions": await _rows(
                self._s, MessengerActiveSession, MessengerActiveSession.user_id == user_id
            ),
            "messenger_pair_tokens": await _rows(
                self._s,
                MessengerPairToken,
                MessengerPairToken.user_id == user_id,
                exclude={"token_hash"},
            ),
            "interview_preferences": await _rows(
                self._s,
                UserInterviewPreference,
                UserInterviewPreference.user_id == user_id,
            ),
            "gateway_usage_log": await _rows(
                self._s, GatewayUsageLog, GatewayUsageLog.user_id == user_id
            ),
        }

    async def _write_user_blobs(self, zf: ZipFile, *, user_id: UUID) -> None:
        prefix = paths.user_root(user_id)
        try:
            refs = await self._blob.list(prefix)
        except Exception as e:
            zf.writestr("blobs_error.txt", str(e))
            return
        for ref in refs:
            if "/exports/" in ref.logical_path:
                continue
            try:
                data = await self._blob.get_bytes(ref.logical_path)
            except Exception as e:
                zf.writestr(f"blobs/{ref.logical_path}.error.txt", str(e))
                continue
            zf.writestr(f"blobs/{ref.logical_path}", data)

    async def _delete_user_blobs(self, *, user_id: UUID) -> dict[str, Any]:
        prefix = paths.user_root(user_id)
        try:
            refs = await self._blob.list(prefix)
            await self._blob.delete(prefix)
            return {"status": "ok", "count": len(refs)}
        except Exception as e:  # noqa: BLE001
            log.warning("user_blob_delete_failed", user_id=str(user_id), error=str(e))
            return {"status": "failed", "error": str(e)}

    async def _delete_user_vectors(
        self, *, user_id: UUID, project_ids: list[UUID]
    ) -> dict[str, Any]:
        collections = [
            vector_collection_for_user_memory(str(user_id)),
            vector_collection_for_user_qa(str(user_id)),
            *[
                vector_collection_for_user_project(str(user_id), str(project_id))
                for project_id in project_ids
            ],
        ]
        failed: list[dict[str, str]] = []
        for collection in collections:
            try:
                await self._vector.delete_collection(collection)
            except Exception as e:  # noqa: BLE001
                failed.append({"collection": collection, "error": str(e)})
        return {
            "status": "ok" if not failed else "partial",
            "collections": len(collections),
            "failed": failed,
        }


async def _rows(
    session: AsyncSession,
    model,
    where,
    *,
    exclude: set[str] | None = None,
) -> list[dict[str, Any]]:
    result = await session.execute(select(model).where(where))
    return [_row_to_dict(row, exclude=exclude or set()) for row in result.scalars()]


def _row_to_dict(row, *, exclude: set[str] | None = None) -> dict[str, Any]:
    exclude = exclude or set()
    out: dict[str, Any] = {}
    for col in row.__table__.columns:
        if col.name in exclude:
            continue
        out[col.name] = _jsonable(getattr(row, col.name))
    return out


def _jsonable(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"redacted": True, "bytes": len(value)}
    return value
