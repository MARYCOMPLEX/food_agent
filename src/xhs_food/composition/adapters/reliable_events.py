"""Reliable task event projection adapters owned by the Composition Root."""

from __future__ import annotations

from collections.abc import Callable

from xhs_food.contracts import EventBusPort, EventEnvelope, TaskEvent

TaskTopicResolver = Callable[[TaskEvent], str]


class ReliableTaskEventBusPublisher:
    """Publish Coordinator-owned ``TaskEvent`` values through an EventBus port.

    The adapter only serializes the internal event at the Foundation boundary;
    it does not assign task status, terminal identity, or replay semantics.
    The caller supplies the topic resolver so session and task stream naming
    remain an explicit Composition-Root decision.
    """

    def __init__(
        self,
        event_bus: EventBusPort,
        *,
        topic_resolver: TaskTopicResolver | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._topic_resolver = topic_resolver or (lambda event: event.task_id)

    async def publish_task_event(self, event: TaskEvent, *, idempotency_key: str) -> str:
        if not idempotency_key:
            raise ValueError("reliable task event idempotency key must be non-empty")
        topic = self._topic_resolver(event)
        if not topic:
            raise ValueError("reliable task event topic must be non-empty")
        envelope = EventEnvelope(
            event_id=event.event_id,
            topic=topic,
            payload={
                "eventType": event.event_type,
                "idempotencyKey": idempotency_key,
                "taskEvent": event.model_dump(mode="json"),
            },
            published_at=event.occurred_at,
        )
        return await self._event_bus.publish(envelope)


__all__ = ["ReliableTaskEventBusPublisher", "TaskTopicResolver"]
