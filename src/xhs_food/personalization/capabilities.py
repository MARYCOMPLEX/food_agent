"""Capability intersection for personalized source and tool selection."""

from __future__ import annotations

from collections.abc import Set

from xhs_food.contracts import (
    EffectiveCapabilities,
    PersonalizationPolicy,
    intersect_personalized_capabilities,
)


class PersonalizationCapabilityResolver:
    """Enforce Pack and request authorization before applying a subset."""

    def resolve(
        self,
        policy: PersonalizationPolicy,
        *,
        pack_sources: Set[str],
        authorized_sources: Set[str],
        pack_tools: Set[str],
        authorized_tools: Set[str],
    ) -> EffectiveCapabilities:
        explicit_sources = bool(policy.selected_source_subset)
        explicit_tools = bool(policy.selected_tool_subset)
        selected_sources = (
            set(policy.selected_source_subset)
            if explicit_sources
            else set(pack_sources) & set(authorized_sources)
        )
        selected_tools = (
            set(policy.selected_tool_subset)
            if explicit_tools
            else set(pack_tools) & set(authorized_tools)
        )
        unauthorized_sources = (
            selected_sources - set(pack_sources) | (selected_sources - set(authorized_sources))
            if explicit_sources
            else set()
        )
        unauthorized_tools = (
            selected_tools - set(pack_tools) | (selected_tools - set(authorized_tools))
            if explicit_tools
            else set()
        )
        if unauthorized_sources:
            raise PermissionError(
                "personalization selected source is outside Pack/request authorization: "
                + ", ".join(sorted(unauthorized_sources))
            )
        if unauthorized_tools:
            raise PermissionError(
                "personalization selected tool is outside Pack/request authorization: "
                + ", ".join(sorted(unauthorized_tools))
            )
        return intersect_personalized_capabilities(
            pack_sources=set(pack_sources),
            authorized_sources=set(authorized_sources),
            selected_sources=selected_sources,
            pack_tools=set(pack_tools),
            authorized_tools=set(authorized_tools),
            selected_tools=selected_tools,
        )


__all__ = ["PersonalizationCapabilityResolver"]
