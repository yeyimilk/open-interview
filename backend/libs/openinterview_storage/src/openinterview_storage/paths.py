"""Tenant-safe logical path builders.

Application code MUST use these helpers instead of constructing paths inline.
This guarantees every path is scoped to a user_id and prevents cross-tenant
path traversal by accident.
"""
from __future__ import annotations

import re
from uuid import UUID

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


def _safe(segment: str) -> str:
    if not segment or segment in {".", ".."} or "/" in segment or "\\" in segment:
        raise ValueError(f"unsafe path segment: {segment!r}")
    return segment


def _uid(user_id: str | UUID) -> str:
    s = str(user_id)
    if not _SAFE_SEGMENT.match(s):
        raise ValueError(f"invalid user_id: {s!r}")
    return s


def user_root(user_id: str | UUID) -> str:
    return f"users/{_uid(user_id)}"


def project_source(user_id: str | UUID, project_id: str | UUID, rel: str) -> str:
    rel_clean = "/".join(_safe(p) for p in rel.split("/") if p)
    return f"{user_root(user_id)}/projects/{_uid(project_id)}/source/{rel_clean}"


def project_diagram(user_id: str | UUID, project_id: str | UUID, name: str) -> str:
    return f"{user_root(user_id)}/projects/{_uid(project_id)}/diagrams/{_safe(name)}"


def qa_shard(user_id: str | UUID, qa_run_id: str | UUID, shard_idx: int) -> str:
    return f"{user_root(user_id)}/qa/{_uid(qa_run_id)}/shard_{int(shard_idx):05d}.json"


def resume_original(user_id: str | UUID, resume_id: str | UUID, ext: str) -> str:
    return f"{user_root(user_id)}/resumes/{_uid(resume_id)}/original.{_safe(ext)}"


def export_archive(user_id: str | UUID, export_id: str | UUID) -> str:
    return f"{user_root(user_id)}/exports/{_uid(export_id)}.zip"


def common_kb_document(document_id: str | UUID, filename: str = "original") -> str:
    return f"common/kb/documents/{_uid(document_id)}/{_safe(filename)}"
