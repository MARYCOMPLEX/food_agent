"""Composition-owned entry points for the replaceable Phoenix adapters.

The implementation remains in Foundation where vendor/network dependencies are
allowed. This module only re-exports project-owned adapter constructors so the
Composition Root can bind them without exposing Phoenix types to callers.
"""

from xhs_food.foundation.evaluation import (
    PhoenixEvaluationAdapter,
    PhoenixEvaluationGateway,
    build_evaluation_port,
)
from xhs_food.foundation.telemetry import (
    OpenTelemetryObservationPort,
    build_observation_exporter,
)

__all__ = [
    "OpenTelemetryObservationPort",
    "PhoenixEvaluationAdapter",
    "PhoenixEvaluationGateway",
    "build_evaluation_port",
    "build_observation_exporter",
]
