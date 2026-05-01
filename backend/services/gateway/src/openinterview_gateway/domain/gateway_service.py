"""Gateway domain service. Pure orchestration; no HTTP, no SQL."""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from openinterview_schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    TokenUsage,
)

from .keys.interface import KeyResolver
from .providers.interface import LLMProvider, ProviderError
from .rate_limit.limiter import RateLimiter
from .rate_limit.tiers import TierCatalog
from .routing.catalog import ModelCatalog
from .usage.interface import UsageEvent, UsageRepository


class GatewayError(Exception):
    def __init__(self, message: str, *, status: int) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class TierLookup:
    """Resolves a user's tier name. Injected so tests can stub it."""

    fn: callable  # type: ignore[type-arg]  -- (UUID) -> str

    async def __call__(self, user_id: UUID) -> str:
        result = self.fn(user_id)
        if hasattr(result, "__await__"):
            return await result
        return result


class GatewayService:
    def __init__(
        self,
        *,
        catalog: ModelCatalog,
        keys: KeyResolver,
        provider: LLMProvider,
        limiter: RateLimiter,
        tiers: TierCatalog,
        usage: UsageRepository,
        tier_lookup: TierLookup,
    ) -> None:
        self._catalog = catalog
        self._keys = keys
        self._provider = provider
        self._limiter = limiter
        self._tiers = tiers
        self._usage = usage
        self._tier_lookup = tier_lookup

    async def chat(self, req: ChatCompletionRequest) -> ChatCompletionResponse:
        entry = self._catalog.resolve("chat", req.logical_model)
        creds = await self._keys.resolve(user_id=req.user_id, provider=entry.provider)
        if creds is None:
            raise GatewayError(
                f"no credentials for provider {entry.provider}", status=503
            )
        await self._enforce_rate_limit(user_id=req.user_id, mode=creds.mode)

        start = time.monotonic()
        status_code = 200
        error: str | None = None
        usage = TokenUsage()
        try:
            result = await self._provider.chat(
                endpoint=entry.endpoint,
                api_key=creds.api_key,
                model_id=entry.model_id,
                messages=req.messages,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            )
            usage = result.usage
            return ChatCompletionResponse(
                id=result.id,
                model=result.model,
                provider=entry.provider,
                content=result.content,
                usage=result.usage,
                finish_reason=result.finish_reason,
            )
        except ProviderError as e:
            status_code = e.status
            error = str(e)
            raise GatewayError(error, status=e.status) from e
        finally:
            latency_ms = int((time.monotonic() - start) * 1000)
            await self._usage.record(
                UsageEvent(
                    user_id=req.user_id,
                    mode=creds.mode,
                    logical_model=entry.logical_name,
                    provider=entry.provider,
                    endpoint=entry.endpoint,
                    usage=usage,
                    latency_ms=latency_ms,
                    status=status_code,
                    error=error,
                )
            )

    async def chat_stream(
        self, req: ChatCompletionRequest
    ) -> AsyncIterator[str]:
        entry = self._catalog.resolve("chat", req.logical_model)
        creds = await self._keys.resolve(user_id=req.user_id, provider=entry.provider)
        if creds is None:
            raise GatewayError(
                f"no credentials for provider {entry.provider}", status=503
            )
        await self._enforce_rate_limit(user_id=req.user_id, mode=creds.mode)

        if not hasattr(self._provider, "chat_stream"):
            # Provider doesn't support streaming -- fall back to non-streaming.
            resp = await self.chat(req)
            if resp.content:
                yield resp.content
            return

        start = time.monotonic()
        status_code = 200
        error: str | None = None
        total_chars = 0
        try:
            async for piece in self._provider.chat_stream(
                endpoint=entry.endpoint,
                api_key=creds.api_key,
                model_id=entry.model_id,
                messages=req.messages,
                temperature=req.temperature,
                max_tokens=req.max_tokens,
            ):
                total_chars += len(piece)
                yield piece
        except ProviderError as e:
            status_code = e.status
            error = str(e)
            raise GatewayError(error, status=e.status) from e
        finally:
            latency_ms = int((time.monotonic() - start) * 1000)
            # Streaming responses don't carry token usage; record approximate counts.
            await self._usage.record(
                UsageEvent(
                    user_id=req.user_id,
                    mode=creds.mode,
                    logical_model=entry.logical_name,
                    provider=entry.provider,
                    endpoint=entry.endpoint,
                    usage=TokenUsage(
                        prompt_tokens=0,
                        completion_tokens=max(1, total_chars // 4),
                        total_tokens=max(1, total_chars // 4),
                    ),
                    latency_ms=latency_ms,
                    status=status_code,
                    error=error,
                )
            )

    async def embed(self, req: EmbeddingRequest) -> EmbeddingResponse:
        entry = self._catalog.resolve("embedding", req.logical_model)
        creds = await self._keys.resolve(user_id=req.user_id, provider=entry.provider)
        if creds is None:
            raise GatewayError(
                f"no credentials for provider {entry.provider}", status=503
            )
        await self._enforce_rate_limit(user_id=req.user_id, mode=creds.mode)

        start = time.monotonic()
        status_code = 200
        error: str | None = None
        usage = TokenUsage()
        try:
            result = await self._provider.embed(
                endpoint=entry.endpoint,
                api_key=creds.api_key,
                model_id=entry.model_id,
                inputs=req.inputs,
            )
            usage = result.usage
            return EmbeddingResponse(
                model=result.model,
                provider=entry.provider,
                vectors=result.vectors,
                usage=result.usage,
            )
        except ProviderError as e:
            status_code = e.status
            error = str(e)
            raise GatewayError(error, status=e.status) from e
        finally:
            latency_ms = int((time.monotonic() - start) * 1000)
            await self._usage.record(
                UsageEvent(
                    user_id=req.user_id,
                    mode=creds.mode,
                    logical_model=entry.logical_name,
                    provider=entry.provider,
                    endpoint=entry.endpoint,
                    usage=usage,
                    latency_ms=latency_ms,
                    status=status_code,
                    error=error,
                )
            )

    async def _enforce_rate_limit(self, *, user_id: UUID, mode: str) -> None:
        if mode == "byo":
            return  # BYO has no limits
        tier_name = await self._tier_lookup(user_id)
        tier = self._tiers.get(tier_name)
        key = f"{user_id}:{tier.name}"
        if not self._limiter.allow(key, tier.rate_limit_rpm):
            raise GatewayError("rate limit exceeded", status=429)
