"""Legacy-preserving Query Family read shadow and canary service."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from xhs_food.contracts import (
    QueryReuseReadMode,
    QueryReuseReadOutcome,
    QueryReuseReadSettings,
    QueryReuseRequest,
    QueryReuseShadowReport,
    QueryReuseShadowStatus,
    digest_public_result,
    stable_request_key_hash,
    stable_sample,
)

from .query_reuse import QueryFamilyReuseService

LegacyReader = Callable[[], Awaitable[Any]]


class QueryReuseReadService:
    """Run the new read only when the closed-world gate permits it."""

    def __init__(
        self,
        reuse: QueryFamilyReuseService,
        *,
        settings: QueryReuseReadSettings | None = None,
    ) -> None:
        self._reuse = reuse
        self._settings = settings or QueryReuseReadSettings()

    @property
    def settings(self) -> QueryReuseReadSettings:
        return self._settings

    async def read(
        self,
        request: QueryReuseRequest,
        legacy_reader: LegacyReader,
        *,
        request_key: str,
    ) -> QueryReuseReadOutcome:
        legacy_value = await legacy_reader()
        legacy_digest = digest_public_result(legacy_value)
        key_hash = stable_request_key_hash(request_key)
        mode = self._settings.mode
        eligible = mode is not QueryReuseReadMode.OFF and stable_sample(
            request_key, self._settings.sample_rate
        )
        if not eligible:
            return QueryReuseReadOutcome(
                legacy_result=_json_value(legacy_value),
                served_result=_json_value(legacy_value),
                shadow=QueryReuseShadowReport(
                    request_key_hash=key_hash,
                    status=QueryReuseShadowStatus.SKIPPED,
                    legacy_digest=legacy_digest,
                ),
            )

        try:
            candidate = await self._reuse.resolve(request)
            candidate_value = _json_value(candidate)
            candidate_digest = digest_public_result(candidate_value)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return QueryReuseReadOutcome(
                legacy_result=_json_value(legacy_value),
                served_result=_json_value(legacy_value),
                shadow=QueryReuseShadowReport(
                    request_key_hash=key_hash,
                    status=QueryReuseShadowStatus.FAILED,
                    legacy_digest=legacy_digest,
                    failure_code=_failure_code(exc),
                ),
            )
        status = (
            QueryReuseShadowStatus.MATCH
            if candidate_digest == legacy_digest
            else QueryReuseShadowStatus.MISMATCH
        )
        # A low-confidence/no-match decision is diagnostic only.  A canary
        # release record is also required before a sampled candidate can
        # replace the legacy result.
        has_match = candidate.match is not None
        served = (
            mode is QueryReuseReadMode.CANARY
            and self._settings.canary_gate_approved
            and has_match
        )
        return QueryReuseReadOutcome(
            legacy_result=_json_value(legacy_value),
            candidate=candidate,
            served_result=(
                candidate_value if served else _json_value(legacy_value)
            ),
            served_candidate=served,
            shadow=QueryReuseShadowReport(
                request_key_hash=key_hash,
                status=status,
                legacy_digest=legacy_digest,
                candidate_digest=candidate_digest,
                served_candidate=served,
            ),
        )


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _failure_code(exc: Exception) -> str:
    """Map candidate failures to a bounded label without exporting details."""

    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "dependency_timeout"
    if isinstance(exc, ValueError):
        return "candidate_invalid"
    return "reuse_failed"


__all__ = ["QueryReuseReadService"]
