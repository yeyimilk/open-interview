"""Composition root: builds the GatewayService from settings + state."""
from __future__ import annotations

from typing import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from openinterview_db import User

from .config import Settings
from .domain.gateway_service import GatewayService, TierLookup
from .domain.providers.interface import LLMProvider
from .domain.rate_limit.limiter import RateLimiter
from .domain.rate_limit.tiers import TierCatalog
from .domain.routing.catalog import ModelCatalog
from .infra.db.usage_repository import SqlUsageRepository
from .infra.keys.sql_resolver import SqlKeyResolver
from .infra.providers.openai_compatible import OpenAICompatibleProvider


def shared_keys_from_settings(s: Settings) -> dict[str, str]:
    raw = {
        "openai": s.shared_key_openai,
        "anthropic": s.shared_key_anthropic,
        "ollama": s.shared_key_ollama,
        "openrouter": s.shared_key_openrouter,
        "together": s.shared_key_together,
    }
    return {k: v for k, v in raw.items() if v}


def make_tier_lookup(sm: async_sessionmaker[AsyncSession]) -> TierLookup:
    async def _lookup(user_id: UUID) -> str:
        async with sm() as session:
            row = (
                await session.execute(select(User.tier).where(User.id == user_id))
            ).scalar_one_or_none()
        return row or "free"

    return TierLookup(fn=_lookup)


def build_service(
    *,
    settings: Settings,
    catalog: ModelCatalog,
    tiers: TierCatalog,
    sessionmaker: async_sessionmaker[AsyncSession],
    decrypt_fn: Callable[[bytes], str],
    provider: LLMProvider | None = None,
) -> GatewayService:
    return GatewayService(
        catalog=catalog,
        keys=SqlKeyResolver(
            sessionmaker=sessionmaker,
            decrypt=decrypt_fn,
            shared_keys=shared_keys_from_settings(settings),
        ),
        provider=provider or OpenAICompatibleProvider(timeout_s=settings.provider_timeout_s),
        limiter=RateLimiter(),
        tiers=tiers,
        usage=SqlUsageRepository(sessionmaker),
        tier_lookup=make_tier_lookup(sessionmaker),
    )
