"""Embedding interface + a Gateway-backed implementation."""
from __future__ import annotations

from typing import Protocol
from uuid import UUID


class Embedder(Protocol):
    async def embed(self, *, user_id: UUID, texts: list[str]) -> list[list[float]]: ...


class GatewayEmbedder(Embedder):
    def __init__(self, gateway, logical_model: str = "embed-default") -> None:
        self._gw = gateway
        self._model = logical_model

    async def embed(self, *, user_id: UUID, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = await self._gw.embed(user_id=user_id, logical_model=self._model, inputs=texts)
        return resp.vectors
