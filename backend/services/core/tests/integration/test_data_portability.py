from __future__ import annotations

import json
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest

pytest.importorskip("aiosqlite")

from sqlalchemy import select  # noqa: E402

from openinterview_core.domain.users import DataPortabilityService  # noqa: E402
from openinterview_core.infra.db import Database  # noqa: E402
from openinterview_db import (  # noqa: E402
    Base,
    ChatMessage,
    ChatSession,
    MessengerLink,
    MessengerPairToken,
    Project,
    ProjectFile,
    QAItem,
    QASet,
    Resume,
    User,
    UserApiKey,
)
from openinterview_storage import BlobRef  # noqa: E402


class FakeBlob:
    def __init__(self, data: dict[str, bytes]) -> None:
        self.data = data
        self.deleted_prefixes: list[str] = []

    async def list(self, prefix: str) -> list[BlobRef]:
        return [
            BlobRef(logical_path=path, size=len(data))
            for path, data in self.data.items()
            if path.startswith(prefix)
        ]

    async def get_bytes(self, logical_path: str) -> bytes:
        return self.data[logical_path]

    async def delete(self, logical_path: str) -> None:
        self.deleted_prefixes.append(logical_path)
        for path in list(self.data):
            if path.startswith(logical_path):
                del self.data[path]


class FakeVectorStore:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete_collection(self, collection: str) -> None:
        self.deleted.append(collection)


@pytest.mark.asyncio
async def test_export_redacts_secrets_and_wipe_preserves_user(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/portability.db")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    user_id = uuid4()
    project_id = uuid4()
    resume_id = uuid4()
    qa_set_id = uuid4()
    chat_session_id = uuid4()
    async with db.sessionmaker() as s:
        s.add(
            User(
                id=user_id,
                email="user@example.com",
                display_name="User",
                password_hash="secret-hash",
                tier="free",
                is_admin=False,
            )
        )
        s.add(
            UserApiKey(
                user_id=user_id,
                provider="openai",
                label="personal",
                encrypted_key=b"ciphertext",
            )
        )
        s.add(
            Project(
                id=project_id,
                user_id=user_id,
                name="demo",
                source_type="zip",
                status="ready",
            )
        )
        s.add(
            ProjectFile(
                user_id=user_id,
                project_id=project_id,
                rel_path="app.py",
                language="python",
                bytes=12,
            )
        )
        s.add(
            Resume(
                id=resume_id,
                user_id=user_id,
                original_filename="resume.pdf",
                content_type="application/pdf",
                text="Ada",
                parsed={"claims": [{"text": "Built API"}]},
            )
        )
        s.add(
            QASet(
                id=qa_set_id,
                user_id=user_id,
                project_id=project_id,
                scope="project",
                position="swe",
                level="mid",
                status="ready",
                total=1,
            )
        )
        s.add(
            QAItem(
                qa_set_id=qa_set_id,
                user_id=user_id,
                category="system_design",
                level="mid",
                question="How is it deployed?",
                ideal_answer="With health checks.",
            )
        )
        s.add(
            ChatSession(
                id=chat_session_id,
                user_id=user_id,
                mode="mentor",
                project_id=project_id,
                title="Mentor",
            )
        )
        s.add(
            ChatMessage(
                session_id=chat_session_id,
                user_id=user_id,
                role="user",
                content="hello",
            )
        )
        s.add(
            MessengerLink(
                user_id=user_id,
                channel="whatsapp",
                external_id="15551234567@s.whatsapp.net",
            )
        )
        s.add(
            MessengerPairToken(
                user_id=user_id,
                channel="whatsapp",
                token_hash="hash",
                expires_at=datetime.now(timezone.utc),
            )
        )
        await s.commit()

    blob = FakeBlob(
        {
            f"users/{user_id}/resume.pdf": b"resume bytes",
            f"users/{user_id}/exports/old.zip": b"skip me",
        }
    )
    vector = FakeVectorStore()

    async with db.sessionmaker() as s:
        service = DataPortabilityService(session=s, blob=blob, vector_store=vector)
        exported = await service.export_user_zip(user_id=user_id)

    with ZipFile(BytesIO(exported)) as zf:
        payload = json.loads(zf.read("data.json"))
        assert payload["user"]["email"] == "user@example.com"
        assert "password_hash" not in payload["user"]
        assert "encrypted_key" not in payload["api_keys"][0]
        assert "token_hash" not in payload["messenger_pair_tokens"][0]
        assert zf.read(f"blobs/users/{user_id}/resume.pdf") == b"resume bytes"
        assert f"blobs/users/{user_id}/exports/old.zip" not in zf.namelist()

    async with db.sessionmaker() as s:
        service = DataPortabilityService(session=s, blob=blob, vector_store=vector)
        result = await service.wipe_user_data(user_id=user_id)

    assert result["status"] == "ok"
    assert blob.deleted_prefixes == [f"users/{user_id}"]
    assert vector.deleted

    async with db.sessionmaker() as s:
        assert await s.get(User, user_id) is not None
        assert (await s.execute(select(Project))).scalars().all() == []
        assert (await s.execute(select(Resume))).scalars().all() == []
        assert (await s.execute(select(ChatSession))).scalars().all() == []
        assert (await s.execute(select(UserApiKey))).scalars().all() == []

    await db.dispose()
