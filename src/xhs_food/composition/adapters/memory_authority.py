"""Application-owned ordering for PostgreSQL memory authority writes."""

from __future__ import annotations

from xhs_food.contracts import (
    MemoryAuthorityWrite,
    MemoryOutboxProjectorPort,
    MemoryRepositoryPort,
    MemoryWriteReceipt,
)


class MemoryAuthorityWriter:
    """Commit authority facts before attempting rebuildable projections."""

    def __init__(
        self,
        repository: MemoryRepositoryPort,
        projector: MemoryOutboxProjectorPort,
    ) -> None:
        self._repository = repository
        self._projector = projector

    async def write(self, batch: MemoryAuthorityWrite) -> MemoryWriteReceipt:
        outbox_id = await self._repository.commit_authority_write(batch)
        try:
            projected = await self._projector.project(batch.outbox)
        except Exception:
            projected = False
        return MemoryWriteReceipt(outbox_id=outbox_id, projected=projected)


__all__ = ["MemoryAuthorityWriter"]
