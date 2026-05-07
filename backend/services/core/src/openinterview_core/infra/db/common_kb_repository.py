from __future__ import annotations

import re
from collections import Counter, defaultdict
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from openinterview_db import (
    CommonKBDocument,
    CommonKBItem,
    CommonKBItemTag,
    CommonKBSource,
    CommonKBSpace,
    CommonKBTag,
    CompanyInterviewProfile,
    UserInterviewPreference,
)


def normalize_tag(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def normalize_company(value: str) -> str:
    return normalize_tag(value).replace("-", "_")


class SqlCommonKBRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_or_create_space(
        self, *, key: str, name: str, description: str | None = None, enabled: bool = True
    ) -> CommonKBSpace:
        key = normalize_tag(key)
        q = select(CommonKBSpace).where(CommonKBSpace.key == key)
        row = (await self._s.execute(q)).scalar_one_or_none()
        if row:
            return row
        row = CommonKBSpace(key=key, name=name, description=description, enabled=enabled)
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def list_spaces(self, *, enabled_only: bool = False) -> list[CommonKBSpace]:
        q = select(CommonKBSpace).order_by(CommonKBSpace.key.asc())
        if enabled_only:
            q = q.where(CommonKBSpace.enabled.is_(True))
        return list((await self._s.execute(q)).scalars())

    async def get_space_by_key(self, key: str) -> CommonKBSpace | None:
        q = select(CommonKBSpace).where(CommonKBSpace.key == normalize_tag(key))
        return (await self._s.execute(q)).scalar_one_or_none()

    async def create_source(
        self,
        *,
        space_id: UUID,
        key: str,
        name: str,
        source_type: str,
        base_url: str | None,
        license: str | None,
        allowed_use: dict | None,
    ) -> CommonKBSource:
        key = normalize_tag(key)
        existing = (await self._s.execute(select(CommonKBSource).where(CommonKBSource.key == key))).scalar_one_or_none()
        if existing:
            return existing
        row = CommonKBSource(
            space_id=space_id,
            key=key,
            name=name,
            source_type=source_type,
            base_url=base_url,
            license=license,
            allowed_use=allowed_use or {"store_text": True},
        )
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def list_sources(self, *, space_key: str | None = None) -> list[CommonKBSource]:
        q = select(CommonKBSource).order_by(CommonKBSource.created_at.desc())
        if space_key:
            space = await self.get_space_by_key(space_key)
            if not space:
                return []
            q = q.where(CommonKBSource.space_id == space.id)
        return list((await self._s.execute(q)).scalars())

    async def get_source(self, source_id: UUID) -> CommonKBSource | None:
        return await self._s.get(CommonKBSource, source_id)

    async def update_source(self, source_id: UUID, **fields) -> CommonKBSource | None:
        row = await self._s.get(CommonKBSource, source_id)
        if not row:
            return None
        for k, v in fields.items():
            if v is not None and hasattr(row, k):
                setattr(row, k, v)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def create_document(
        self,
        *,
        space_id: UUID,
        source_id: UUID | None,
        title: str,
        filename: str | None,
        content_type: str | None,
        blob_path: str | None,
        canonical_url: str | None = None,
        meta: dict | None = None,
    ) -> CommonKBDocument:
        row = CommonKBDocument(
            space_id=space_id,
            source_id=source_id,
            title=title,
            filename=filename,
            content_type=content_type,
            blob_path=blob_path,
            canonical_url=canonical_url,
            status="uploaded",
            meta=meta,
        )
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def get_document(self, document_id: UUID) -> CommonKBDocument | None:
        return await self._s.get(CommonKBDocument, document_id)

    async def get_document_by_hash(
        self, *, source_id: UUID | None, content_hash: str
    ) -> CommonKBDocument | None:
        q = select(CommonKBDocument).where(CommonKBDocument.content_hash == content_hash)
        if source_id is not None:
            q = q.where(CommonKBDocument.source_id == source_id)
        return (await self._s.execute(q)).scalars().first()

    async def list_documents(
        self, *, space_key: str | None = None, status: str | None = None, limit: int = 100
    ) -> list[CommonKBDocument]:
        q = select(CommonKBDocument).order_by(CommonKBDocument.created_at.desc()).limit(max(1, min(limit, 2000)))
        if space_key:
            space = await self.get_space_by_key(space_key)
            if not space:
                return []
            q = q.where(CommonKBDocument.space_id == space.id)
        if status:
            q = q.where(CommonKBDocument.status == status)
        return list((await self._s.execute(q)).scalars())

    async def update_document(self, document_id: UUID, **fields) -> CommonKBDocument | None:
        row = await self._s.get(CommonKBDocument, document_id)
        if not row:
            return None
        for k, v in fields.items():
            if hasattr(row, k):
                setattr(row, k, v)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def document_item_refs(self, document_id: UUID) -> list[tuple[UUID, str]]:
        q = (
            select(CommonKBItem.id, CommonKBSpace.key)
            .join(CommonKBSpace, CommonKBSpace.id == CommonKBItem.space_id)
            .where(CommonKBItem.document_id == document_id)
        )
        return [(item_id, space_key) for item_id, space_key in (await self._s.execute(q)).all()]

    async def delete_document_with_items(self, document_id: UUID) -> bool:
        row = await self._s.get(CommonKBDocument, document_id)
        if row is None:
            return False
        await self.delete_items_for_document(document_id)
        await self._s.delete(row)
        await self._s.commit()
        return True

    async def create_item(
        self,
        *,
        space_id: UUID,
        source_id: UUID | None,
        document_id: UUID | None,
        item_type: str,
        category: str,
        title: str,
        question: str | None = None,
        answer_outline: str | None = None,
        content: str | None = None,
        difficulty: int = 3,
        role_family: str | None = None,
        level: str | None = None,
        company: str | None = None,
        language: str | None = None,
        provenance: dict | None = None,
        tags: list[str] | None = None,
        status: str = "ready",
    ) -> CommonKBItem:
        row = CommonKBItem(
            space_id=space_id,
            source_id=source_id,
            document_id=document_id,
            item_type=item_type,
            category=category,
            title=title[:240],
            question=question,
            answer_outline=answer_outline,
            content=content,
            difficulty=max(1, min(5, int(difficulty or 3))),
            role_family=role_family,
            level=level,
            company=company,
            language=language,
            provenance=provenance,
            status=status,
        )
        self._s.add(row)
        await self._s.flush()
        await self.set_item_tags(row.id, tags or [])
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def delete_items_for_document(self, document_id: UUID) -> None:
        ids = (
            await self._s.execute(
                select(CommonKBItem.id).where(CommonKBItem.document_id == document_id)
            )
        ).scalars().all()
        if ids:
            await self._s.execute(delete(CommonKBItemTag).where(CommonKBItemTag.item_id.in_(ids)))
            await self._s.execute(delete(CommonKBItem).where(CommonKBItem.id.in_(ids)))
            await self._s.flush()

    async def update_item(self, item_id: UUID, *, tags: list[str] | None = None, **fields) -> CommonKBItem | None:
        row = await self._s.get(CommonKBItem, item_id)
        if not row:
            return None
        for k, v in fields.items():
            if v is not None and hasattr(row, k):
                setattr(row, k, v)
        if tags is not None:
            await self.set_item_tags(row.id, tags)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def set_item_tags(self, item_id: UUID, tags: list[str]) -> None:
        await self._s.execute(delete(CommonKBItemTag).where(CommonKBItemTag.item_id == item_id))
        seen: set[str] = set()
        for raw in tags:
            value = str(raw).strip()
            norm = normalize_tag(value)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            tag = (
                await self._s.execute(
                    select(CommonKBTag).where(
                        CommonKBTag.namespace == "topic",
                        CommonKBTag.normalized == norm,
                    )
                )
            ).scalar_one_or_none()
            if tag is None:
                tag = CommonKBTag(namespace="topic", value=value, normalized=norm)
                self._s.add(tag)
                await self._s.flush()
            self._s.add(CommonKBItemTag(item_id=item_id, tag_id=tag.id))

    async def item_tags(self, item_ids: list[UUID]) -> dict[UUID, list[str]]:
        if not item_ids:
            return {}
        q = (
            select(CommonKBItemTag.item_id, CommonKBTag.value)
            .join(CommonKBTag, CommonKBTag.id == CommonKBItemTag.tag_id)
            .where(CommonKBItemTag.item_id.in_(item_ids))
        )
        out: dict[UUID, list[str]] = defaultdict(list)
        for item_id, value in (await self._s.execute(q)).all():
            out[item_id].append(value)
        return out

    async def document_tags(self, document_ids: list[UUID]) -> dict[UUID, list[str]]:
        if not document_ids:
            return {}
        q = (
            select(CommonKBItem.document_id, CommonKBTag.value)
            .join(CommonKBItemTag, CommonKBItemTag.item_id == CommonKBItem.id)
            .join(CommonKBTag, CommonKBTag.id == CommonKBItemTag.tag_id)
            .where(CommonKBItem.document_id.in_(document_ids))
        )
        out: dict[UUID, list[str]] = defaultdict(list)
        seen: dict[UUID, set[str]] = defaultdict(set)
        for document_id, value in (await self._s.execute(q)).all():
            if document_id is None:
                continue
            norm = normalize_tag(value)
            if norm in seen[document_id]:
                continue
            seen[document_id].add(norm)
            out[document_id].append(value)
        return out

    async def list_items(
        self,
        *,
        space_key: str | None = None,
        tag: str | None = None,
        company: str | None = None,
        category: str | None = None,
        language: str | None = None,
        status: str = "ready",
        limit: int = 100,
    ) -> list[CommonKBItem]:
        q = select(CommonKBItem).order_by(CommonKBItem.created_at.desc()).limit(max(1, min(limit, 2000)))
        if status:
            q = q.where(CommonKBItem.status == status)
        if space_key:
            space = await self.get_space_by_key(space_key)
            if not space:
                return []
            q = q.where(CommonKBItem.space_id == space.id)
        if company:
            q = q.where(CommonKBItem.company.ilike(f"%{company}%"))
        if category:
            q = q.where(CommonKBItem.category == category)
        if language:
            q = q.where(CommonKBItem.language.ilike(f"%{language}%"))
        if tag:
            norm = normalize_tag(tag)
            q = (
                q.join(CommonKBItemTag, CommonKBItemTag.item_id == CommonKBItem.id)
                .join(CommonKBTag, CommonKBTag.id == CommonKBItemTag.tag_id)
                .where(CommonKBTag.normalized == norm)
            )
        return list((await self._s.execute(q)).scalars())

    async def get_items_by_ids(self, item_ids: list[UUID]) -> list[CommonKBItem]:
        if not item_ids:
            return []
        q = select(CommonKBItem).where(CommonKBItem.id.in_(item_ids))
        return list((await self._s.execute(q)).scalars())

    async def rebuild_company_profiles(self, *, company_key: str | None = None) -> list[CompanyInterviewProfile]:
        q = select(CommonKBItem).where(
            CommonKBItem.item_type == "company_experience",
            CommonKBItem.company.is_not(None),
            CommonKBItem.status == "ready",
        )
        if company_key:
            q = q.where(CommonKBItem.company.ilike(f"%{company_key.replace('_', ' ')}%"))
        items = list((await self._s.execute(q)).scalars())
        grouped: dict[str, list[CommonKBItem]] = defaultdict(list)
        for it in items:
            if it.company:
                grouped[normalize_company(it.company)].append(it)

        profiles: list[CompanyInterviewProfile] = []
        for key, rows in grouped.items():
            company = rows[0].company or key
            cat_counts = Counter((r.category or "general") for r in rows)
            total = max(1, sum(cat_counts.values()))
            weights = {k: round(v / total, 3) for k, v in cat_counts.items()}
            langs = [r.language for r in rows if r.language]
            lang_counts = Counter(langs)
            source_refs = [
                {"item_id": str(r.id), "title": r.title, "source_id": str(r.source_id) if r.source_id else None}
                for r in rows[:10]
            ]
            profile = (
                await self._s.execute(
                    select(CompanyInterviewProfile).where(CompanyInterviewProfile.company_key == key)
                )
            ).scalar_one_or_none()
            if profile is None:
                profile = CompanyInterviewProfile(company_key=key, company=company)
                self._s.add(profile)
            profile.category_weights = weights
            profile.language_preferences = [k for k, _ in lang_counts.most_common(8)]
            profile.round_patterns = _round_patterns(rows)
            profile.confidence = min(0.95, 0.3 + len(rows) * 0.08)
            profile.source_refs = source_refs
            profile.item_count = len(rows)
            profiles.append(profile)
        await self._s.commit()
        for p in profiles:
            await self._s.refresh(p)
        return profiles

    async def list_company_profiles(self, *, query: str | None = None, limit: int = 50) -> list[CompanyInterviewProfile]:
        q = select(CompanyInterviewProfile).order_by(CompanyInterviewProfile.company.asc()).limit(limit)
        if query:
            q = q.where(CompanyInterviewProfile.company.ilike(f"%{query}%"))
        return list((await self._s.execute(q)).scalars())

    async def get_company_profile(self, company: str) -> CompanyInterviewProfile | None:
        key = normalize_company(company)
        row = (
            await self._s.execute(
                select(CompanyInterviewProfile).where(CompanyInterviewProfile.company_key == key)
            )
        ).scalar_one_or_none()
        if row:
            return row
        return (
            await self._s.execute(
                select(CompanyInterviewProfile)
                .where(CompanyInterviewProfile.company.ilike(f"%{company}%"))
                .order_by(CompanyInterviewProfile.item_count.desc())
            )
        ).scalar_one_or_none()

    async def get_user_preferences(self, *, user_id: UUID) -> UserInterviewPreference | None:
        q = select(UserInterviewPreference).where(UserInterviewPreference.user_id == user_id)
        return (await self._s.execute(q)).scalar_one_or_none()

    async def upsert_user_preferences(
        self,
        *,
        user_id: UUID,
        target_company: str | None,
        category_weights: dict | None,
        languages: list[str] | None,
        interview_style: str | None,
        include_company_style: bool,
    ) -> UserInterviewPreference:
        row = await self.get_user_preferences(user_id=user_id)
        if row is None:
            row = UserInterviewPreference(user_id=user_id)
            self._s.add(row)
        row.target_company = target_company
        row.category_weights = category_weights
        row.languages = languages or []
        row.interview_style = interview_style
        row.include_company_style = include_company_style
        await self._s.commit()
        await self._s.refresh(row)
        return row


def _round_patterns(items: list[CommonKBItem]) -> list[dict]:
    counts = Counter()
    for it in items:
        prov = it.provenance or {}
        round_name = prov.get("round") or prov.get("interview_round") or it.category
        if round_name:
            counts[str(round_name)] += 1
    return [{"round": k, "count": v} for k, v in counts.most_common(8)]
