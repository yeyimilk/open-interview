from __future__ import annotations

import uuid

from openinterview_core.infra.vector import vector_collection_for_user_project


def test_project_vector_collection_name_is_chroma_safe() -> None:
    name = vector_collection_for_user_project(str(uuid.uuid4()), str(uuid.uuid4()))

    assert 3 <= len(name) <= 63
    assert name[0].isalnum()
    assert name[-1].isalnum()
    assert all(ch.isalnum() or ch in "_-" for ch in name)
