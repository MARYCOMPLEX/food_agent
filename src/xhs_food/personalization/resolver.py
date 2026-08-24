"""Deterministic memory priority resolution for personalized decisions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime

from xhs_food.contracts import (
    ContractPayload,
    MemoryIsolationKey,
    MemoryLayer,
    MemoryRecord,
    MemoryStatus,
    PreferenceSnapshot,
    isolation_key_for,
)


class PreferenceResolver:
    """Resolve private memory without changing public query or evidence identity."""

    def resolve(
        self,
        records: Iterable[MemoryRecord],
        *,
        scope: MemoryIsolationKey,
        snapshot_id: str,
        snapshot_version: int,
        policy_version: str,
        generated_at: datetime,
    ) -> PreferenceSnapshot:
        scoped_records = tuple(records)
        expected_scope = _scope_key(scope)
        for record in scoped_records:
            if _scope_key(isolation_key_for(record)) != expected_scope:
                raise ValueError("memory resolver received a record outside the requested scope")

        active = tuple(
            record
            for record in scoped_records
            if _is_active(record, generated_at)
        )
        source_record_versions: dict[str, str] = {}
        for record in sorted(active, key=_record_order, reverse=True):
            source_record_versions[record.record_id] = _record_version(record)

        explicit_hard_constraints = _values_for_records(
            active,
            lambda record: record.layer is MemoryLayer.EXPLICIT and _is_hard_constraint(record),
        )
        stable_explicit_preferences = _values_for_records(
            active,
            lambda record: record.layer is MemoryLayer.EXPLICIT and not _is_hard_constraint(record),
        )
        session_requirements = _values_for_layer(active, MemoryLayer.SESSION)
        inferred_preferences = _values_for_layer(active, MemoryLayer.INFERRED)
        strategy_feedback = _values_for_layer(active, MemoryLayer.STRATEGY_FEEDBACK)

        return PreferenceSnapshot(
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            isolation_key=scope,
            policy_version=policy_version,
            source_record_versions=source_record_versions,
            explicit_hard_constraints=explicit_hard_constraints,
            session_requirements=session_requirements,
            stable_explicit_preferences=stable_explicit_preferences,
            inferred_preferences=inferred_preferences,
            strategy_feedback=strategy_feedback,
            generated_at=generated_at,
        )

    def effective_constraints(self, snapshot: PreferenceSnapshot) -> ContractPayload:
        """Merge content preferences from weakest to strongest priority.

        Strategy feedback is deliberately excluded: it may tune research
        execution and presentation, but never overrides content constraints.
        """

        effective: ContractPayload = {}
        for bucket in (
            snapshot.inferred_preferences,
            snapshot.stable_explicit_preferences,
            snapshot.session_requirements,
            snapshot.explicit_hard_constraints,
        ):
            effective.update(bucket)
        return effective


def _is_active(record: MemoryRecord, now: datetime) -> bool:
    return (
        record.status is MemoryStatus.ACTIVE
        and record.consent.status.value == "active"
        and record.valid_from <= now
        and (record.expires_at is None or now < record.expires_at)
    )


def _is_hard_constraint(record: MemoryRecord) -> bool:
    if record.layer is not MemoryLayer.EXPLICIT:
        return False
    return record.value.get("kind") == "hard_constraint" or bool(
        record.value.get("hardConstraint") is True
    )


def _values_for_layer(
    records: Iterable[MemoryRecord], layer: MemoryLayer
) -> ContractPayload:
    return _values_for_records(records, lambda record: record.layer is layer)


def _values_for_records(
    records: Iterable[MemoryRecord], predicate: Callable[[MemoryRecord], bool]
) -> ContractPayload:
    values: ContractPayload = {}
    for record in sorted(records, key=_record_order, reverse=True):
        if predicate(record):
            values.setdefault(record.key, record.value)
    return values


def _record_order(record: MemoryRecord) -> tuple[datetime, str]:
    return (record.updated_at, record.record_id)


def _record_version(record: MemoryRecord) -> str:
    return f"{record.schema_version}:{record.policy_version}:{record.updated_at.isoformat()}"


def _scope_key(scope: MemoryIsolationKey) -> tuple[str, str, str, str | None]:
    subject_id = scope.user_id if scope.kind == "user" else scope.anonymous_subject_id
    return (scope.tenant_id, str(scope.kind), subject_id, scope.session_id)


__all__ = ["PreferenceResolver"]
