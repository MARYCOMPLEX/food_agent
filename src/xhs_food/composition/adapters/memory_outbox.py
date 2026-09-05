"""Post-commit projection of private memory outbox events."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from datetime import UTC, datetime
from typing import Any, cast

from xhs_food.contracts import (
    MemoryIsolationKey,
    MemoryOutboxEvent,
    MemoryOutboxProjectorPort,
    MemoryRepositoryPort,
    MemorySessionWindowPort,
    SessionWindowPort,
)


class MemoryOutboxProjector:
    """Apply rebuildable Redis session projections after PG commit.

    Projection failures are returned to the caller so the committed outbox row
    can be retried. They never raise into the authority transaction.
    """

    def __init__(
        self,
        session_window: MemorySessionWindowPort | SessionWindowPort,
        *,
        ttl_seconds: int = 86_400,
        warmup_enabled: bool = True,
        derived_projector: MemoryOutboxProjectorPort | None = None,
    ) -> None:
        if ttl_seconds != 86_400:
            raise ValueError("memory session projection TTL must be 24 hours")
        self._session_window = session_window
        self._ttl_seconds = ttl_seconds
        self._warmup_enabled = warmup_enabled
        self._derived_projector = derived_projector
        self._authority_versions: dict[tuple[str, str, str, str | None], int] = {}
        self._projected_events: set[str] = set()
        self._projection_lock = asyncio.Lock()

    @property
    def warmup_enabled(self) -> bool:
        return self._warmup_enabled

    def disable_warmup(self) -> None:
        """Stop rebuildable Redis warm-up while retaining authority rows."""

        self._warmup_enabled = False

    async def project(self, event: MemoryOutboxEvent) -> bool:
        event_key = _event_key(event)
        authority_version = _authority_version(event)
        async with self._projection_lock:
            # Replayed outbox deliveries are acknowledged after their first
            # successful projection.  A newer authority watermark fences an
            # older delivery before it can touch a cache.
            scope_key = _scope_key(event.scope)
            latest = self._authority_versions.get(scope_key, -1)
            if event_key in self._projected_events or authority_version < latest:
                return True
            try:
                projected = await self._project_event(event, authority_version)
            except Exception:
                return False
            if projected:
                self._authority_versions[scope_key] = max(latest, authority_version)
                self._projected_events.add(event_key)
            return projected

    async def _project_event(self, event: MemoryOutboxEvent, authority_version: int) -> bool:
        if event.event_type in {
            "memory.summary.project",
            "memory.index.project",
            "memory.preference.project",
        }:
            if self._derived_projector is None:
                return False
            return bool(await self._derived_projector.project(event))

        session_id = event.scope.session_id
        if event.event_type in {
            "memory.session.invalidate",
            "memory.claim.source.invalidate",
            "memory.feedback.project",
        }:
            if not session_id:
                return True
            return bool(
                await self._call_versioned(
                    "clear", event.scope, authority_version, event.outbox_id
                )
            )
        if event.event_type in {"memory.session.warm", "memory.claim.target.warm"}:
            if not session_id:
                return False
            if not self._warmup_enabled:
                return True
            message = event.payload.get("message")
            if message is None and event.event_type == "memory.claim.target.warm":
                # Claim events invalidate the target projection when there is no
                # concrete session message to warm.  The next read then rebuilds
                # from PostgreSQL authority under the full target scope.
                return bool(
                    await self._call_versioned(
                        "clear", event.scope, authority_version, event.outbox_id
                    )
                )
            if not isinstance(message, dict):
                return False
            return bool(
                await self._call_versioned(
                    "append", event.scope, message, self._ttl_seconds, authority_version, event.outbox_id
                )
            )
        return False

    async def _call_versioned(
        self,
        method_name: str,
        scope: MemoryIsolationKey,
        *args: object,
    ) -> Any:
        versioned_name = f"{method_name}_if_newer"
        versioned_method = getattr(self._session_window, versioned_name, None)
        if callable(versioned_method):
            call = cast(Any, versioned_method)
            if method_name == "append":
                message, ttl_seconds, authority_version, event_id = args
                result = call(
                    scope,
                    message,
                    ttl_seconds,
                    authority_version,
                    event_id,
                )
            else:
                authority_version, event_id = args
                result = call(scope, authority_version, event_id)
            if inspect.isawaitable(result):
                return await result
            return result
        if method_name == "append":
            result = await self._call(method_name, scope, *args[:2])
        else:
            result = await self._call(method_name, scope)
        # Legacy SessionWindowPort mutators return None; reaching this point
        # without an exception is still a successful projection.
        return True if result is None else result

    async def _call(self, method_name: str, scope: MemoryIsolationKey, *args: object) -> Any:
        """Invoke a scoped port while preserving the legacy session adapter.

        New memory projections receive the complete isolation key.  The existing
        legacy adapter predates B3 and accepts only ``session_id``; detecting that
        boundary by its first parameter name keeps compatibility without dropping
        tenant/subject scope for new adapters.
        """

        method = getattr(self._session_window, method_name)
        parameters = tuple(inspect.signature(method).parameters.values())
        first_name = parameters[0].name if parameters else "scope"
        target: MemoryIsolationKey | str
        if first_name in {"session_id", "session", "key"}:
            if scope.session_id is None:
                raise ValueError("memory session projection requires session_id")
            target = scope.session_id
        else:
            target = scope
        result = method(target, *args)
        if inspect.isawaitable(result):
            return await result
        return result


class MemoryOutboxReplayer:
    """Replay committed projection work and acknowledge it only on success."""

    def __init__(
        self,
        repository: MemoryRepositoryPort,
        projector: MemoryOutboxProjectorPort,
    ) -> None:
        self._repository = repository
        self._projector = projector

    async def replay(
        self,
        *,
        available_at: datetime | None = None,
        limit: int = 100,
    ) -> int:
        if not 1 <= limit <= 1000:
            raise ValueError("outbox replay limit must be between 1 and 1000")
        watermark = available_at or datetime.now(UTC)
        events = await self._repository.list_pending_outbox(
            available_at=watermark,
            limit=limit,
        )
        processed = 0
        for event in events:
            if not await self._projector.project(event):
                continue
            if await self._repository.mark_outbox_processed(
                outbox_id=event.outbox_id,
                processed_at=watermark,
            ):
                processed += 1
        return processed


def _authority_version(event: MemoryOutboxEvent) -> int:
    """Read the explicit fence, accepting payload-only events from old writers."""

    if event.authority_version:
        return event.authority_version
    value = event.payload.get("authorityVersion", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("memory outbox authorityVersion must be a non-negative integer")
    return value


def _scope_key(scope: MemoryIsolationKey) -> tuple[str, str, str, str | None]:
    subject_id = scope.user_id if scope.kind == "user" else scope.anonymous_subject_id
    return (scope.tenant_id, str(scope.kind), subject_id, scope.session_id)


def _event_key(event: MemoryOutboxEvent) -> str:
    return hashlib.sha256(event.outbox_id.encode("utf-8")).hexdigest()


__all__ = ["MemoryOutboxProjector", "MemoryOutboxReplayer"]
