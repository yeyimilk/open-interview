from __future__ import annotations

import uuid

import pytest

pytest.importorskip("aiosqlite")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from openinterview_core.app import create_app  # noqa: E402
from openinterview_core.config import Settings  # noqa: E402
from openinterview_core.infra.db.common_kb_repository import SqlCommonKBRepository  # noqa: E402
from openinterview_core.infra.vector import InMemoryVectorStore, VectorRecord  # noqa: E402
from openinterview_core.infra.vector import vector_collection_for_common_kb  # noqa: E402


def _settings(tmp_path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'admin_kb.db'}",
        openinterview_data_dir=str(tmp_path / "data"),
    )


async def _register_admin(client: AsyncClient) -> str:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "owner-kb@example.com",
            "password": "hunter2hunter2",
            "display_name": "Owner",
        },
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner-kb@example.com", "password": "hunter2hunter2"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_admin_batch_delete_documents_removes_items_vectors_and_blobs(tmp_path) -> None:
    app = create_app(_settings(tmp_path))
    app.state.vector_store = InMemoryVectorStore()
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token = await _register_admin(client)

            async with app.state.db.session() as session:
                repo = SqlCommonKBRepository(session)
                space = await repo.get_or_create_space(key="leetcode", name="LeetCode")
                doc_a = await repo.create_document(
                    space_id=space.id,
                    source_id=None,
                    title="Graph patterns",
                    filename="graphs.md",
                    content_type="text/markdown",
                    blob_path="common/kb/documents/doc-a/graphs.md",
                )
                doc_b = await repo.create_document(
                    space_id=space.id,
                    source_id=None,
                    title="DP patterns",
                    filename="dp.md",
                    content_type="text/markdown",
                    blob_path="common/kb/documents/doc-b/dp.md",
                )
                item_a = await repo.create_item(
                    space_id=space.id,
                    source_id=None,
                    document_id=doc_a.id,
                    item_type="question",
                    category="algorithms",
                    title="Shortest path",
                    question="When do you use Dijkstra?",
                    tags=["graph"],
                )
                item_b = await repo.create_item(
                    space_id=space.id,
                    source_id=None,
                    document_id=doc_b.id,
                    item_type="question",
                    category="algorithms",
                    title="Knapsack",
                    question="How do you model 0/1 knapsack?",
                    tags=["dp"],
                )

            await app.state.blob.put_bytes(doc_a.blob_path, b"graph", content_type="text/markdown")
            await app.state.blob.put_bytes(doc_b.blob_path, b"dp", content_type="text/markdown")
            collection = vector_collection_for_common_kb("leetcode")
            await app.state.vector_store.upsert(
                collection=collection,
                records=[
                    VectorRecord(id=str(item_a.id), text="graph evidence", metadata={}),
                    VectorRecord(id=str(item_b.id), text="dp evidence", metadata={}),
                ],
                embeddings=[[1.0, 0.0], [0.0, 1.0]],
            )

            missing_id = uuid.uuid4()
            r = await client.post(
                "/api/v1/admin/kb/documents:batch-delete",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "document_ids": [
                        str(doc_a.id),
                        str(doc_b.id),
                        str(doc_b.id),
                        str(missing_id),
                    ],
                },
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert set(body["deleted_ids"]) == {str(doc_a.id), str(doc_b.id)}
            assert body["missing_ids"] == [str(missing_id)]

            async with app.state.db.session() as session:
                repo = SqlCommonKBRepository(session)
                assert await repo.get_document(doc_a.id) is None
                assert await repo.get_document(doc_b.id) is None
                assert await repo.list_items(tag="graph") == []
                assert await repo.list_items(tag="dp") == []

            matches = await app.state.vector_store.query(
                collection=collection,
                embedding=[1.0, 0.0],
                k=10,
            )
            assert matches == []
            assert not await app.state.blob.exists(doc_a.blob_path)
            assert not await app.state.blob.exists(doc_b.blob_path)
