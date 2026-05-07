from __future__ import annotations

import hashlib
import asyncio
import json
import re
from dataclasses import dataclass
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openinterview_logging import get_logger
from openinterview_schemas import ChatMessage
from openinterview_storage import BlobStorage, paths

from ...infra.db.common_kb_repository import SqlCommonKBRepository, normalize_tag
from ...infra.vector import VectorRecord, VectorStore, vector_collection_for_common_kb
from ..projects.embedder import GatewayEmbedder
from .extractor import CommonDocumentTextExtractor, chunk_text

SYSTEM_USER_ID = UUID("00000000-0000-0000-0000-000000000000")
log = get_logger(__name__)


@dataclass(frozen=True)
class ExtractedKBItem:
    item_type: str
    category: str
    title: str
    question: str | None
    answer_outline: str | None
    content: str | None
    difficulty: int
    role_family: str | None
    level: str | None
    company: str | None
    language: str | None
    tags: list[str]


class CommonKBProcessingService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        blob: BlobStorage,
        gateway,
        vector_store: VectorStore,
        chat_logical_model: str = "chat-fast",
        embed_logical_model: str = "embed-default",
    ) -> None:
        self._sm = sessionmaker
        self._blob = blob
        self._gw = gateway
        self._vs = vector_store
        self._chat = chat_logical_model
        self._embed = embed_logical_model

    async def process_document(self, *, document_id: UUID, actor_user_id: UUID | None = None) -> list[UUID]:
        async with self._sm() as s:
            repo = SqlCommonKBRepository(s)
            doc = await repo.get_document(document_id)
            if doc is None:
                raise ValueError("document not found")
            await repo.update_document(document_id, status="processing", error=None)
            blob_path = doc.blob_path
            filename = doc.filename or "document.txt"
            content_type = doc.content_type
            space_id = doc.space_id
            source_id = doc.source_id
            doc_meta = doc.meta or {}
            document_tags = _clean_tags(doc_meta.get("tags") if isinstance(doc_meta, dict) else [])
            create_embeddings = bool(doc_meta.get("create_embeddings", True)) if isinstance(doc_meta, dict) else True

        try:
            if not blob_path:
                raise ValueError("document has no blob")
            data = await self._blob.get_bytes(blob_path)
            text = CommonDocumentTextExtractor().extract(
                filename=filename, content_type=content_type or "", data=data
            )
            digest = hashlib.sha256(data).hexdigest()
            store_text = bool((doc_meta.get("allowed_use") or {}).get("store_text", True))
            items = await self._extract_items(
                text=text,
                title=filename,
                actor_user_id=actor_user_id or SYSTEM_USER_ID,
            )
            async with self._sm() as s:
                repo = SqlCommonKBRepository(s)
                await repo.update_document(
                    document_id,
                    extracted_text=text if store_text else None,
                    content_hash=digest,
                    status="processed",
                    error=None,
                )
                await repo.delete_items_for_document(document_id)
                ids: list[UUID] = []
                for it in items:
                    row = await repo.create_item(
                        space_id=space_id,
                        source_id=source_id,
                        document_id=document_id,
                        item_type=it.item_type,
                        category=it.category,
                        title=it.title,
                        question=it.question,
                        answer_outline=it.answer_outline,
                        content=it.content,
                        difficulty=it.difficulty,
                        role_family=it.role_family,
                        level=it.level,
                        company=it.company,
                        language=it.language,
                        provenance={"document_id": str(document_id), "filename": filename},
                        tags=_merge_tags(document_tags, it.tags),
                    )
                    ids.append(row.id)
            if create_embeddings:
                await self.embed_items(item_ids=ids, actor_user_id=actor_user_id or SYSTEM_USER_ID)
            return ids
        except Exception as e:
            async with self._sm() as s:
                await SqlCommonKBRepository(s).update_document(
                    document_id, status="failed", error=str(e)[:1000]
                )
            raise

    async def refresh_source(self, *, source_id: UUID, actor_user_id: UUID | None = None) -> list[UUID]:
        async with self._sm() as s:
            repo = SqlCommonKBRepository(s)
            src = await repo.get_source(source_id)
            if src is None:
                raise ValueError("source not found")
            await repo.update_source(source_id, refresh_status="running", last_error=None)
            base_url = src.base_url
            allowed_use = src.allowed_use or {}
            source_type = src.source_type
            space_id = src.space_id
            name = src.name
        try:
            if not base_url:
                raise ValueError("source has no base_url")
            if source_type not in {"allowlist_url", "html", "markdown", "json", "leetcode_index", "company_experience"}:
                raise ValueError(f"unsupported source_type: {source_type}")
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(base_url)
                resp.raise_for_status()
                data = resp.content
                ctype = resp.headers.get("content-type", "text/html")
            digest = hashlib.sha256(data).hexdigest()
            async with self._sm() as s:
                existing = await SqlCommonKBRepository(s).get_document_by_hash(
                    source_id=source_id, content_hash=digest
                )
                if existing is not None and existing.status == "processed":
                    await SqlCommonKBRepository(s).update_source(
                        source_id, refresh_status="idle", last_error=None
                    )
                    return []
            filename = _filename_from_url(base_url, ctype)
            blob_path = paths.common_kb_document(UUID(bytes=hashlib.md5(base_url.encode()).digest()), filename)
            if allowed_use.get("store_text", True):
                await self._blob.put_bytes(blob_path, data, content_type=ctype)
            else:
                # Store an empty audit blob, but process the fetched bytes in memory.
                await self._blob.put_bytes(blob_path, b"", content_type="text/plain")
            async with self._sm() as s:
                doc = await SqlCommonKBRepository(s).create_document(
                    space_id=space_id,
                    source_id=source_id,
                    title=name,
                    filename=filename,
                    content_type=ctype,
                    blob_path=blob_path,
                    canonical_url=base_url,
                    meta={
                        "allowed_use": allowed_use,
                        "create_embeddings": bool(allowed_use.get("create_embeddings", True)),
                    },
                )
                await SqlCommonKBRepository(s).update_document(doc.id, content_hash=digest)
                doc_id = doc.id
            if not allowed_use.get("store_text", True):
                await self._blob.put_bytes(blob_path, data, content_type=ctype)
                ids = await self.process_document(document_id=doc_id, actor_user_id=actor_user_id)
                await self._blob.put_bytes(blob_path, b"", content_type="text/plain")
            else:
                ids = await self.process_document(document_id=doc_id, actor_user_id=actor_user_id)
            async with self._sm() as s:
                await SqlCommonKBRepository(s).update_source(source_id, refresh_status="idle", last_error=None)
            return ids
        except Exception as e:
            async with self._sm() as s:
                await SqlCommonKBRepository(s).update_source(
                    source_id, refresh_status="failed", last_error=str(e)[:1000]
                )
            raise

    async def embed_items(self, *, item_ids: list[UUID], actor_user_id: UUID | None = None) -> None:
        if not item_ids:
            return
        async with self._sm() as s:
            repo = SqlCommonKBRepository(s)
            items = await repo.get_items_by_ids(item_ids)
            tags = await repo.item_tags([i.id for i in items])
            spaces = {sp.id: sp for sp in await repo.list_spaces()}
        by_space: dict[str, list] = {}
        for it in items:
            sp = spaces.get(it.space_id)
            if sp is None:
                continue
            by_space.setdefault(sp.key, []).append(it)
        embedder = GatewayEmbedder(self._gw, logical_model=self._embed)
        for space_key, rows in by_space.items():
            texts = [_item_text(it, tags.get(it.id, [])) for it in rows]
            vectors: list[list[float]] | None = None
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    vectors = await embedder.embed(user_id=actor_user_id or SYSTEM_USER_ID, texts=texts)
                    break
                except Exception as e:  # noqa: BLE001
                    last_error = e
                    if attempt < 2:
                        await asyncio.sleep(2 * (attempt + 1))
            if vectors is None:
                log.warning(
                    "common_kb_embed_failed",
                    space_key=space_key,
                    item_count=len(rows),
                    error=str(last_error),
                )
                continue
            records = [
                VectorRecord(
                    id=str(it.id),
                    text=texts[i],
                    metadata={
                        "space": space_key,
                        "category": it.category,
                        "title": it.title,
                        "item_type": it.item_type,
                        "company": it.company or "",
                        "language": it.language or "",
                        "difficulty": it.difficulty,
                    },
                )
                for i, it in enumerate(rows)
            ]
            await self._vs.upsert(
                collection=vector_collection_for_common_kb(space_key),
                records=records,
                embeddings=vectors,
            )

    async def rebuild_company_profiles(self, *, company_key: str | None = None) -> int:
        async with self._sm() as s:
            rows = await SqlCommonKBRepository(s).rebuild_company_profiles(company_key=company_key)
            return len(rows)

    async def _extract_items(self, *, text: str, title: str, actor_user_id: UUID) -> list[ExtractedKBItem]:
        chunks = chunk_text(text, max_chars=5500)[:6]
        if not chunks:
            return []
        out: list[ExtractedKBItem] = []
        for chunk in chunks:
            out.extend(await self._extract_chunk_with_llm(chunk=chunk, title=title, actor_user_id=actor_user_id))
        if out:
            return _dedupe(out)
        return _heuristic_items(text=text, title=title)

    async def _extract_chunk_with_llm(self, *, chunk: str, title: str, actor_user_id: UUID) -> list[ExtractedKBItem]:
        prompt = (
            "Extract interview-prep KB items from this document chunk. Return STRICT JSON: "
            '{"items":[{"item_type":str,"category":str,"title":str,"question":str|null,'
            '"answer_outline":str|null,"content":str|null,"difficulty":1-5,'
            '"role_family":str|null,"level":str|null,"company":str|null,'
            '"language":str|null,"tags":[str]}]}. '
            "Allowed categories: algorithms,data_structures,system_design,ai_design,architecture,"
            "behavioral,company_experience,language,testing. "
            "For company interview reports, use item_type=company_experience and include company if stated. "
            "Do not copy long copyrighted problem statements or solutions; summarize concepts/rubrics briefly.\n\n"
            f"DOCUMENT: {title}\nCHUNK:\n{chunk[:5500]}"
        )
        try:
            r = await self._gw.chat(
                user_id=actor_user_id,
                logical_model=self._chat,
                messages=[ChatMessage(role="user", content=prompt)],
            )
            data = _safe_json(r.content, default={})
        except Exception:
            return []
        items: list[ExtractedKBItem] = []
        for raw in data.get("items") or []:
            if not isinstance(raw, dict):
                continue
            title_s = str(raw.get("title") or raw.get("question") or "").strip()
            if not title_s:
                continue
            items.append(
                ExtractedKBItem(
                    item_type=str(raw.get("item_type") or "topic")[:64],
                    category=normalize_tag(str(raw.get("category") or "general")).replace("-", "_"),
                    title=title_s[:240],
                    question=_opt(raw.get("question")),
                    answer_outline=_opt(raw.get("answer_outline")),
                    content=_opt(raw.get("content")),
                    difficulty=max(1, min(5, int(raw.get("difficulty") or 3))),
                    role_family=_opt(raw.get("role_family")),
                    level=_opt(raw.get("level")),
                    company=_opt(raw.get("company")),
                    language=_opt(raw.get("language")),
                    tags=[str(t)[:80] for t in (raw.get("tags") or []) if str(t).strip()][:12],
                )
            )
        return items


def _heuristic_items(*, text: str, title: str) -> list[ExtractedKBItem]:
    items: list[ExtractedKBItem] = []
    for line in text.splitlines():
        s = line.strip(" -*#\t")
        if len(s) < 12:
            continue
        is_question = s.endswith("?") or re.match(r"^(design|implement|explain|tell me|how would)", s, re.I)
        if not is_question:
            continue
        category = _guess_category(s)
        items.append(
            ExtractedKBItem(
                item_type="question",
                category=category,
                title=s[:120],
                question=s,
                answer_outline="A strong answer should cover the main approach, trade-offs, edge cases, and level-appropriate depth.",
                content=None,
                difficulty=3,
                role_family=None,
                level=None,
                company=_guess_company(s),
                language=_guess_language(s),
                tags=[category],
            )
        )
        if len(items) >= 40:
            break
    if not items and text.strip():
        category = _guess_category(text[:1000])
        items.append(
            ExtractedKBItem(
                item_type="topic",
                category=category,
                title=title[:120],
                question=None,
                answer_outline=None,
                content=text[:1800],
                difficulty=3,
                role_family=None,
                level=None,
                company=_guess_company(text[:1000]),
                language=_guess_language(text[:1000]),
                tags=[category],
            )
        )
    return items


def _guess_category(text: str) -> str:
    low = text.lower()
    if any(x in low for x in ("leetcode", "array", "graph", "dynamic programming", "tree", "hashmap")):
        return "algorithms"
    if any(x in low for x in ("system design", "scaling", "cache", "sharding", "consistent hashing")):
        return "system_design"
    if any(x in low for x in ("rag", "agent", "prompt", "embedding", "eval", "llm")):
        return "ai_design"
    if any(x in low for x in ("behavioral", "tell me about a time", "leadership")):
        return "behavioral"
    if any(x in low for x in ("onsite", "phone screen", "round", "interview experience")):
        return "company_experience"
    return "architecture"


def _guess_company(text: str) -> str | None:
    for company in ("Google", "Meta", "Amazon", "Microsoft", "Apple", "OpenAI", "Netflix", "Uber", "Airbnb"):
        if re.search(rf"\b{re.escape(company)}\b", text, re.I):
            return company
    return None


def _guess_language(text: str) -> str | None:
    for lang in ("Python", "Java", "C++", "JavaScript", "TypeScript", "Go", "Rust", "SQL"):
        if re.search(rf"\b{re.escape(lang)}\b", text, re.I):
            return lang
    return None


def _clean_tags(tags) -> list[str]:
    if not isinstance(tags, list):
        return []
    out: list[str] = []
    for raw in tags:
        value = str(raw).strip()
        if value:
            out.append(value[:80])
    return out[:20]


def _merge_tags(*groups: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw in group:
            value = str(raw).strip()
            norm = normalize_tag(value)
            if not value or norm in seen:
                continue
            seen.add(norm)
            out.append(value[:80])
    return out[:20]


def _item_text(item, tags: list[str]) -> str:
    bits = [
        item.title,
        item.question or "",
        item.answer_outline or "",
        item.content or "",
        item.category,
        item.company or "",
        item.language or "",
        " ".join(tags),
    ]
    return "\n".join(b for b in bits if b).strip()


def _dedupe(items: list[ExtractedKBItem]) -> list[ExtractedKBItem]:
    seen: set[str] = set()
    out: list[ExtractedKBItem] = []
    for it in items:
        key = normalize_tag(it.question or it.title)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _safe_json(text: str, *, default):
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
        return json.loads(cleaned)
    except Exception:
        return default


def _opt(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _filename_from_url(url: str, content_type: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1] or "source"
    if "." not in tail:
        if "json" in content_type:
            tail += ".json"
        elif "html" in content_type:
            tail += ".html"
        else:
            tail += ".txt"
    return tail[:180]
