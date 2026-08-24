"""Post-commit projection of private memory outbox events."""

from __future__ import annotations

from xhs_food.contracts import MemoryOutboxEvent, SessionWindowPort


class MemoryOutboxProjector:
    """Apply rebuildable Redis session projections after PG commit.

    Projection failures are returned to the caller so the committed outbox row
    can be retried. They never raise into the authority transaction.
    """

    def __init__(
        self,
        session_window: SessionWindowPort,
        *,
        ttl_seconds: int = 86_400,
        warmup_enabled: bool = True,
    ) -> None:
        if ttl_seconds != 86_400:
            raise ValueError("memory session projection TTL must be 24 hours")
        self._session_window = session_window
        self._ttl_seconds = ttl_seconds
        self._warmup_enabled = warmup_enabled

    @property
    def warmup_enabled(self) -> bool:
        return self._warmup_enabled

    def disable_warmup(self) -> None:
        """Stop rebuildable Redis warm-up while retaining authority rows."""

        self._warmup_enabled = False

    async def project(self, event: MemoryOutboxEvent) -> bool:
        session_id = event.scope.session_id
        if not session_id:
            return False
        try:
            if event.event_type == "memory.session.invalidate":
                await self._session_window.clear(session_id)
                return True
            if event.event_type == "memory.session.warm":
                if not self._warmup_enabled:
                    return True
                message = event.payload.get("message")
                if not isinstance(message, dict):
                    return False
                await self._session_window.append(session_id, message, self._ttl_seconds)
                return True
        except Exception:
            return False
        return False


__all__ = ["MemoryOutboxProjector"]
