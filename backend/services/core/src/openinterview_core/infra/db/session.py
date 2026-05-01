from __future__ import annotations

from typing import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from openinterview_db import make_engine, make_sessionmaker


class Database:
    def __init__(self, url: str, echo: bool = False) -> None:
        self._engine: AsyncEngine = make_engine(url, echo=echo)
        self._sessionmaker: async_sessionmaker[AsyncSession] = make_sessionmaker(self._engine)

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        return self._sessionmaker

    def session(self) -> AsyncSession:
        return self._sessionmaker()

    async def dispose(self) -> None:
        await self._engine.dispose()


async def get_session_dep(request: Request) -> AsyncIterator[AsyncSession]:
    db: Database = request.app.state.db
    async with db.session() as s:
        yield s
