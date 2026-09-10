"""Non-authoritative negotiated change metadata; never authentication state."""

import json
import re
import secrets
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import dj_hyperview.realtime as realtime_api
from django.http import HttpRequest, HttpResponse
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.utils.crypto import salted_hmac

from .session_contract import SESSION_BINDING_HEADER

FEATURE_HEADER = "X-HyperTodo-Realtime-Features"
FEATURE = "changes-v2"
SEED_HEADER = "X-HyperTodo-Mutation-Seed"
MUTATION_HEADER = "X-HyperTodo-Mutation-ID"
_RESOURCES = ("tasks", "categories", "ui")
_HEX = re.compile(r"[0-9a-f]+\Z", re.ASCII)
_mutation: ContextVar[str | None] = ContextVar("hypertodo_mutation", default=None)


def supports_changes() -> bool:
    """Return the public wire capability, not a guessed version promise."""
    return 2 in getattr(realtime_api, "INVALIDATION_VERSIONS", ())


def negotiated(request: HttpRequest) -> bool:
    """Recognize an exact feature request without granting any authority."""
    return supports_changes() and request.headers.get(FEATURE_HEADER) == FEATURE


def _hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str) and len(value) == length and bool(_HEX.fullmatch(value))
    )


@contextmanager
def mutation_context(request: HttpRequest | None) -> Iterator[None]:
    """Capture a guarded POST origin and restore it even on exceptions.

    Args:
        request: Already guarded request, or None to clear inherited context.

    Yields:
        No value; the correlation token has no authorization semantics.
    """
    value = None
    if (
        request is not None
        and request.method == "POST"
        and getattr(request, "hv_realtime_v1", False) is True
        and negotiated(request)
    ):
        candidate = request.headers.get(MUTATION_HEADER)
        if _hex(candidate, 40):
            value = candidate
    token = _mutation.set(value)
    try:
        yield
    finally:
        _mutation.reset(token)


def current_mutation() -> str | None:
    """Return this operation's opaque token, never an owner or session ID."""
    return _mutation.get()


def mark_changes_response(request: HttpRequest, response: HttpResponse) -> None:
    """Emit fresh metadata only on a final verified owned response.

    Args:
        request: Guarded HXML or authenticated SSE request.
        response: Final response after its session binding was verified.
    """
    response.headers.pop(SEED_HEADER, None)
    response.headers.pop(FEATURE_HEADER, None)
    patch_vary_headers(response, [FEATURE_HEADER])
    if (
        getattr(request, "hv_realtime_v1", False) is True
        and negotiated(request)
        and SESSION_BINDING_HEADER in response
        and response.status_code < 500
    ):
        response[FEATURE_HEADER] = FEATURE
        response[SEED_HEADER] = secrets.token_hex(16)
        patch_cache_control(response, no_store=True)


@dataclass(frozen=True, slots=True)
class EntitySet:
    """Immutable opaque precision snapshot, never an authorization principal."""

    epoch: str
    items: tuple[tuple[str, str], ...]

    @property
    def payload(self) -> dict[str, object]:
        """Return a fresh nested wire copy, without exposing stored model keys."""
        return {
            "epoch": self.epoch,
            "items": [
                {"resource": resource, "key": key} for resource, key in self.items
            ],
        }


def capture_entities(
    using: str, rows: Iterable[tuple[str, object]] | None
) -> EntitySet | None:
    """Capture at most 32 opaque entity keys; unknown precision stays broad.

    Args:
        using: Actual mutation database alias, never a client-selected topic.
        rows: Server-selected resource/model-key pairs, or unknown.

    Returns:
        Immutable HMAC precision, or None on empty/unknown/overflow input.
    """
    if rows is None:
        return None
    items = set()
    for index, (resource, key) in enumerate(rows):
        if index >= 32 or resource not in _RESOURCES or key is None:
            return None
        value = json.dumps([using, resource, str(key)], separators=(",", ":"))
        opaque = salted_hmac(
            "hypertodo.entity.v2", value, algorithm="sha256"
        ).hexdigest()
        items.add((resource, opaque))
    if not items:
        return None
    epoch = salted_hmac(
        "hypertodo.entity-epoch.v2", "epoch", algorithm="sha256"
    ).hexdigest()[:16]
    return EntitySet(epoch, tuple(sorted(items)))


def capture_wire_metadata(data: Mapping[str, object]) -> dict[str, object]:
    """Validate closed rich metadata even when projecting for a legacy client.

    Args:
        data: Version-two payload with canonical resources checked by the stream.

    Returns:
        Fresh mutation/entity values with no shared mutable references.

    Raises:
        ValueError: If untrusted broker metadata violates the closed contract.
    """
    mutation = data["mutation_id"]
    if mutation is not None and not _hex(mutation, 40):
        raise ValueError("invalid-realtime-event")
    entities = data["entities"]
    if entities is None:
        return {"mutation_id": mutation, "entities": None}
    if not isinstance(entities, Mapping) or set(entities) != {"epoch", "items"}:
        raise ValueError("invalid-realtime-event")
    items = entities["items"]
    if (
        not _hex(entities["epoch"], 16)
        or not isinstance(items, list)
        or not 1 <= len(items) <= 32
    ):
        raise ValueError("invalid-realtime-event")
    pairs = []
    for item in items:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"resource", "key"}
            or not isinstance(item["resource"], str)
            or item["resource"] not in data["resources"]
            or not _hex(item["key"], 64)
            or (item["resource"], item["key"]) in pairs
        ):
            raise ValueError("invalid-realtime-event")
        pairs.append((item["resource"], item["key"]))
    return {
        "mutation_id": mutation,
        "entities": EntitySet(entities["epoch"], tuple(pairs)).payload,
    }
