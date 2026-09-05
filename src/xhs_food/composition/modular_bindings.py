"""Validated capability bindings for the B1/B2/B3 qualification paths.

The plan is deliberately vendor-neutral.  It gives the Composition Root one
place to validate activation ordering and one stable set of logical names,
while concrete SQL, Redis, OpenTelemetry, and Phoenix adapters stay behind
their project-owned ports.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from xhs_food.foundation.config import (
    EvidenceShadowConfigView,
    ObservabilityConfigView,
    PersonalizationCanaryConfigView,
    QueryReuseReadConfigView,
    TargetSettings,
)


class CapabilityMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    CANARY = "canary"


@dataclass(frozen=True, slots=True)
class ModularAdapterOverrides:
    """Optional ports supplied by tests, sidecars, or a deployment factory.

    Values are intentionally typed as ``object`` here.  The Composition Root
    validates the relevant runtime protocols when a binding is selected; this
    module must not import concrete adapters or vendor SDKs.
    """

    evidence_shadow_sink: object | None = None
    canonical_query_shadow: object | None = None
    # Source connectors are optional because the current legacy application
    # supplies them through its own runtime.  When injected here, the root
    # owns the gateway boundary and can apply the B1 decorator before
    # registration.
    source_connectors: Mapping[str, object] | None = None
    source_connector_decorator: Callable[[object], object] | None = None
    source_gateway: object | None = None
    query_family_repository: object | None = None
    memory_repository: object | None = None
    memory_session_window: object | None = None
    observation_port: object | None = None
    evaluation_port: object | None = None
    memory_outbox_projector: object | None = None
    memory_authority_writer: object | None = None
    query_reuse_read: object | None = None


@dataclass(frozen=True, slots=True)
class ModularBindingPlan:
    """Immutable, validated activation plan owned by the Composition Root."""

    evidence_shadow: EvidenceShadowConfigView
    query_reuse_read: QueryReuseReadConfigView
    personalization: PersonalizationCanaryConfigView
    observability: ObservabilityConfigView
    target_adapters_enabled: bool

    @property
    def evidence_mode(self) -> CapabilityMode:
        return CapabilityMode.SHADOW if self.evidence_shadow.enabled else CapabilityMode.OFF

    @property
    def query_mode(self) -> CapabilityMode:
        return CapabilityMode(self.query_reuse_read.mode)

    @property
    def personalization_mode(self) -> CapabilityMode:
        return CapabilityMode(self.personalization.mode)

    @property
    def observability_enabled(self) -> bool:
        return self.observability.enabled

    @property
    def phoenix_enabled(self) -> bool:
        return self.observability.phoenix_enabled

    @property
    def has_evidence_bindings(self) -> bool:
        return self.evidence_mode is not CapabilityMode.OFF or self.query_mode is not CapabilityMode.OFF

    @property
    def has_memory_bindings(self) -> bool:
        return self.personalization_mode is not CapabilityMode.OFF

    def validate(self) -> ModularBindingPlan:
        active_target = (
            self.evidence_mode is not CapabilityMode.OFF
            or self.query_mode is not CapabilityMode.OFF
            or self.personalization_mode is not CapabilityMode.OFF
        )
        if active_target and not self.target_adapters_enabled:
            raise ValueError("B1/B2/B3 activation requires target_adapters_enabled")
        if self.query_mode is CapabilityMode.CANARY and not self.query_reuse_read.b1_gate_approved:
            raise ValueError("B2 canary requires an approved B1 qualification gate")
        if self.phoenix_enabled and not self.observability.enabled:
            raise ValueError("Phoenix export requires OTel to be enabled")
        if self.phoenix_enabled and not self.observability.exporter_endpoint:
            raise ValueError("Phoenix export requires an OTLP exporter endpoint")
        if self.phoenix_enabled and not self.observability.phoenix_evaluation_endpoint:
            raise ValueError("Phoenix evaluation requires an HTTP endpoint")
        return self


def build_modular_binding_plan(target: TargetSettings, owner: Any) -> ModularBindingPlan:
    """Build and validate a plan from immutable owner views.

    ``owner`` is accepted as ``Any`` to keep this module independent from the
    adapter facade implementation; it must expose the four capability views.
    """

    plan = ModularBindingPlan(
        evidence_shadow=owner.evidence_shadow,
        query_reuse_read=owner.query_reuse_read,
        personalization=owner.personalization_canary,
        observability=owner.observability,
        target_adapters_enabled=bool(target.target_adapters_enabled),
    )
    return plan.validate()


__all__ = [
    "CapabilityMode",
    "ModularAdapterOverrides",
    "ModularBindingPlan",
    "build_modular_binding_plan",
]
