"""B3 Pack/request/personalization capability intersection tests."""

from __future__ import annotations

import pytest

from xhs_food.contracts import PersonalizationPolicy, UserIsolationKey
from xhs_food.personalization import PersonalizationCapabilityResolver


def _policy(
    *,
    sources: tuple[str, ...] = (),
    tools: tuple[str, ...] = (),
) -> PersonalizationPolicy:
    return PersonalizationPolicy(
        policy_id="personalization-capabilities",
        policy_version="personalization-policy/v1",
        isolation_key=UserIsolationKey(
            tenant_id="tenant-cn-1",
            user_id="user-2b4aa1b95c884d64",
        ),
        preference_snapshot_id="snapshot-capabilities",
        preference_snapshot_version=1,
        selected_source_subset=sources,
        selected_tool_subset=tools,
    )


@pytest.mark.unit
def test_capability_resolver_intersects_pack_authorization_and_subset() -> None:
    effective = PersonalizationCapabilityResolver().resolve(
        _policy(sources=("place.lookup",), tools=("place.lookup",)),
        pack_sources={"place.lookup", "reviews.search"},
        authorized_sources={"place.lookup", "reviews.search"},
        pack_tools={"place.lookup", "evidence.search_reviews"},
        authorized_tools={"place.lookup", "evidence.search_reviews"},
    )
    assert effective.sources == ("place.lookup",)
    assert effective.tools == ("place.lookup",)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("sources", "tools", "message"),
    [
        (("private.source",), (), "source"),
        ((), ("admin.tool",), "tool"),
    ],
)
def test_capability_resolver_rejects_unregistered_or_unauthorized_selection(
    sources: tuple[str, ...],
    tools: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(PermissionError, match=message):
        PersonalizationCapabilityResolver().resolve(
            _policy(sources=sources, tools=tools),
            pack_sources={"place.lookup"},
            authorized_sources={"place.lookup"},
            pack_tools={"place.lookup"},
            authorized_tools={"place.lookup"},
        )


@pytest.mark.unit
def test_empty_personalization_subset_defaults_to_pack_then_authorization() -> None:
    effective = PersonalizationCapabilityResolver().resolve(
        _policy(),
        pack_sources={"place.lookup", "reviews.search"},
        authorized_sources={"place.lookup"},
        pack_tools={"place.lookup", "evidence.search_reviews"},
        authorized_tools={"place.lookup"},
    )
    assert effective.sources == ("place.lookup",)
    assert effective.tools == ("place.lookup",)

