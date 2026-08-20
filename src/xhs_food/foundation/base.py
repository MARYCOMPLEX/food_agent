"""Shared lifecycle guards for target infrastructure adapters."""

from __future__ import annotations


class TargetAdapterDisabled(RuntimeError):
    """Raised before a disabled structural adapter can create or call a client."""

    def __init__(self, adapter_name: str) -> None:
        super().__init__(f"target adapter {adapter_name!r} is disabled")
        self.adapter_name = adapter_name


def require_enabled(enabled: bool, adapter_name: str) -> None:
    if not enabled:
        raise TargetAdapterDisabled(adapter_name)


__all__ = ["TargetAdapterDisabled", "require_enabled"]
