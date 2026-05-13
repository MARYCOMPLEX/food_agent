# -*- coding: utf-8 -*-
"""Domain exception hierarchy for xhs_food.

All custom errors descend from :class:`XHSFoodError`. System boundaries
(API handlers, background tasks) catch this top-level base; internal
business logic should raise the most specific subclass that fits and
otherwise let unexpected exceptions propagate.
"""
from __future__ import annotations


class XHSFoodError(Exception):
    """Base class for every xhs_food domain error."""


class ConfigError(XHSFoodError):
    """Missing or invalid configuration (env vars, credentials)."""


class SpiderError(XHSFoodError):
    """XHS scraping layer failure (network, auth, parsing)."""


class XHSAuthError(SpiderError):
    """XHS cookie / signing / login problem."""


class LLMError(XHSFoodError):
    """LLM provider call failed or returned unusable output."""


class LLMResponseParseError(LLMError):
    """LLM returned text that could not be parsed into the expected shape."""


class IntentError(XHSFoodError):
    """Could not derive a usable intent from user input."""


class StorageError(XHSFoodError):
    """Persistence layer (Postgres / Redis) failure."""


class EventBusError(XHSFoodError):
    """Event bus publish/subscribe failure."""
