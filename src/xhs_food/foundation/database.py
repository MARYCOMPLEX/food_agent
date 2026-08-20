"""SQLAlchemy 2 async engine and explicit unit-of-work ownership."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from enum import StrEnum
from types import TracebackType
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from xhs_food.contracts import ErrorScope

from .base import require_enabled
from .failures import foundation_failure_boundary


class RepositorySlot(StrEnum):
    SESSION = "session"
    USER = "user"
    HISTORY = "history"
    FAVORITES = "favorites"
    SEARCH_RESULT = "search_result"
    PUBLIC_EVIDENCE = "public_evidence"


SessionFactory = Callable[[], Any]


class SQLAlchemyUnitOfWork:
    """Own exactly one AsyncSession and transaction for one use case."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Any | None = None
        self._finished = False

    async def __aenter__(self) -> SQLAlchemyUnitOfWork:
        if self._session is not None:
            raise RuntimeError("unit of work cannot be entered twice")
        session = self._session_factory()
        try:
            with foundation_failure_boundary(
                scope=ErrorScope.REPOSITORY,
                operation="repository.transaction.begin",
            ):
                await session.begin()
        except BaseException:
            with suppress(BaseException):
                await session.close()
            raise
        self._session = session
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        del exc_type, exc, traceback
        if self._session is None:
            return None
        try:
            if not self._finished:
                with foundation_failure_boundary(
                    scope=ErrorScope.REPOSITORY,
                    operation="repository.transaction.rollback",
                ):
                    await self._session.rollback()
        finally:
            with foundation_failure_boundary(
                scope=ErrorScope.REPOSITORY,
                operation="repository.session.close",
            ):
                await self._session.close()
            self._session = None
        return None

    async def commit(self) -> None:
        session = self._require_session()
        if self._finished:
            raise RuntimeError("unit of work transaction is already finished")
        with foundation_failure_boundary(
            scope=ErrorScope.REPOSITORY,
            operation="repository.transaction.commit",
        ):
            await session.commit()
        self._finished = True

    async def rollback(self) -> None:
        session = self._require_session()
        if self._finished:
            return
        with foundation_failure_boundary(
            scope=ErrorScope.REPOSITORY,
            operation="repository.transaction.rollback",
        ):
            await session.rollback()
        self._finished = True

    def session_for_adapter(self) -> AsyncSession:
        """Foundation repository adapters share the owner session; callers do not."""

        return self._require_session()

    def _require_session(self) -> Any:
        if self._session is None:
            raise RuntimeError("unit of work is not active")
        return self._session


class SQLAlchemyDatabase:
    """One target async engine/pool, created only after explicit activation."""

    def __init__(
        self,
        database_url: str,
        *,
        enabled: bool = False,
        engine_factory: Callable[..., AsyncEngine] = create_async_engine,
    ) -> None:
        self._database_url = _asyncpg_url(database_url)
        self._enabled = enabled
        self._engine_factory = engine_factory
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    def start(self) -> None:
        require_enabled(self._enabled, "sqlalchemy")
        if self._engine is not None:
            return
        with foundation_failure_boundary(
            scope=ErrorScope.REPOSITORY,
            operation="repository.database.start",
        ):
            self._engine = self._engine_factory(
                self._database_url,
                pool_pre_ping=True,
            )
            self._session_factory = async_sessionmaker(
                self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )

    def unit_of_work(self) -> SQLAlchemyUnitOfWork:
        if self._session_factory is None:
            raise RuntimeError("SQLAlchemy target adapter has not been started")
        return SQLAlchemyUnitOfWork(self._session_factory)

    async def aclose(self) -> None:
        if self._engine is not None:
            with foundation_failure_boundary(
                scope=ErrorScope.REPOSITORY,
                operation="repository.database.close",
            ):
                await self._engine.dispose()
            self._engine = None
            self._session_factory = None


def _asyncpg_url(value: str) -> str:
    if value.startswith("postgresql+asyncpg://"):
        return value
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+asyncpg://", 1)
    raise ValueError("target database URL must use PostgreSQL with asyncpg")


__all__ = [
    "RepositorySlot",
    "SQLAlchemyDatabase",
    "SQLAlchemyUnitOfWork",
]
