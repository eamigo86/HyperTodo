"""Private immutable intents delivered through the public after-commit broker."""

import base64
import logging
from collections.abc import Iterable
from dataclasses import dataclass

from django.db import transaction

from .realtime_changes import (
    EntitySet,
    capture_entities,
    current_mutation,
    supports_changes,
)
from .realtime_config import RealtimeConfig, get_realtime_config

logger = logging.getLogger(__name__)
_RESOURCE_ORDER = ("tasks", "categories", "ui")


def _component(value: object) -> str:
    return (
        base64.urlsafe_b64encode(str(value).encode("utf-8"))
        .rstrip(b"=")
        .decode("ascii")
    )


def private_topic(using: str, owner: object) -> str:
    """Encode database alias and owner as independently delimited components.

    Args:
        using: Server-selected database alias.
        owner: Persisted primary key, never a client topic parameter.

    Returns:
        Private broker topic without wildcard characters.
    """
    return f"private.{_component(using)}.{_component(owner)}"


def ui_topic(using: str) -> str:
    """Select the shared UI topic for one server-selected database alias.

    Args:
        using: Template database alias.

    Returns:
        Alias-scoped topic, never a template name.
    """
    return f"ui.{_component(using)}"


@dataclass(frozen=True, slots=True)
class Notification:
    """Internal routing and coarse resources; routing never enters SSE data."""

    using: str
    topics: tuple[str, ...]
    resources: tuple[str, ...]
    version: int = 1
    mutation_id: str | None = None
    entities: EntitySet | None = None

    @property
    def payload(self) -> dict[str, object]:
        """Return a fresh public wire payload without routing metadata.

        Returns:
            Canonical resources and negotiated opaque change metadata.
        """
        data = {"version": self.version, "resources": list(self.resources)}
        if self.version == 2:
            data.update(
                mutation_id=self.mutation_id,
                entities=self.entities.payload if self.entities else None,
            )
        return data


def _publish(config: RealtimeConfig, intent: Notification) -> None:
    from dj_hyperview.realtime import RedisBroker

    RedisBroker(config.redis_url, namespace=config.namespace).publish_after_commit(
        {"event": "invalidate", "data": intent.payload},
        intent.topics,
        using=intent.using,
    )


def _deliver(config: RealtimeConfig, intent: Notification) -> None:
    try:
        _publish(config, intent)
    except Exception:
        # Do not log Redis credentials, payloads, model keys or exception text.
        # The business transaction has committed; never retry or claim rollback.
        logger.warning("realtime-publication-failed")


def notify_after_commit(
    *,
    using: str,
    owners: Iterable[object],
    resources: Iterable[str],
    config: RealtimeConfig | None = None,
    entities: Iterable[tuple[str, object]] | None = None,
) -> None:
    """Capture immutable private routing and defer delivery on the actual alias.

    Args:
        using: Database alias on which the mutation occurred.
        owners: Persisted old/new and related task owners.
        resources: Known coarse resource names.
        config: Configuration already captured by the mutation receiver.
        entities: Server-selected resource/model-key pairs; unknown stays broad.

    Raises:
        ValueError: If a caller supplies unknown or empty resources.
    """
    config = config or get_realtime_config()
    if config is None:
        return
    selected = frozenset(resources)
    if not selected or not selected.issubset(_RESOURCE_ORDER):
        raise ValueError("Unknown realtime resources")
    topics = tuple(sorted({private_topic(using, owner) for owner in owners}))
    if not topics:
        return
    precision = capture_entities(using, entities)
    if precision is not None and any(
        resource not in selected for resource, _ in precision.items
    ):
        precision = None
    intent = Notification(
        using,
        topics,
        tuple(r for r in _RESOURCE_ORDER if r in selected),
        version=2 if supports_changes() else 1,
        mutation_id=current_mutation(),
        entities=precision,
    )
    transaction.on_commit(lambda: _deliver(config, intent), using=using)


def notify_template_commit(*, using: str) -> None:
    """Deliver a public package hint which is already outside its transaction.

    Args:
        using: Alias captured by the package's after-commit event.
    """
    config = get_realtime_config()
    if config is not None:
        _deliver(config, Notification(using, (ui_topic(using),), ("ui",)))
