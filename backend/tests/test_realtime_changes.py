"""Negotiated non-authoritative change correlation and exact entity projection."""

import copy
import json
import re
from collections.abc import Iterator
from types import ModuleType

import pytest
from django.contrib.auth.models import AbstractUser
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction
from django.http import HttpResponse, HttpResponseNotModified
from django.test import Client, RequestFactory
from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks, Settings

from tests.test_realtime_stream import authenticated as authenticated
from todo.models import Task
from todo.session_contract import (
    CLIENT_CONTRACT,
    CLIENT_CONTRACT_HEADER,
    SESSION_BINDING_HEADER,
)
from todo.session_middleware import SessionBindingResponseMiddleware

FEATURE = "X-HyperTodo-Realtime-Features"
SEED = "X-HyperTodo-Mutation-Seed"
MUTATION = "X-HyperTodo-Mutation-ID"
CONFIG = {"REDIS_URL": "redis://127.0.0.1:6379/14", "NAMESPACE": "change-tests"}


def module() -> ModuleType:
    """Import the realtime changes module when a test needs it.

    Returns:
        The todo.realtime_changes module.
    """
    from todo import realtime_changes

    return realtime_changes


def request(
    *,
    method: str = "POST",
    mutation: str = "a" * 32 + "00000001",
    feature: str = "changes-v2",
) -> WSGIRequest:
    """Build a request that carries the feature and mutation origin headers.

    Args:
        method: HTTP method of the request.
        mutation: Mutation origin value the client sends.
        feature: Realtime feature the client advertises.

    Returns:
        A request marked as realtime negotiated.
    """
    req = getattr(RequestFactory(), method.lower())(
        "/hv/tasks/", headers={FEATURE: feature, MUTATION: mutation}
    )
    req.hv_realtime_v1 = True
    return req


@pytest.mark.parametrize("status", [200, 304, 422])
def test_bound_response_seed_is_fresh_and_not_replayed_from_cached_object(
    status: int,
) -> None:
    """A bound response gets a fresh seed, never one replayed from a cached object.

    Args:
        status: Status code of the response that is marked.
    """
    req = request(method="GET")
    response = (
        HttpResponseNotModified() if status == 304 else HttpResponse(status=status)
    )
    response[SESSION_BINDING_HEADER] = "verified-owned-binding"
    response[SEED] = "f" * 32  # simulated cached response metadata
    module().mark_changes_response(req, response)
    first = response[SEED]
    module().mark_changes_response(req, response)
    assert re.fullmatch("[0-9a-f]{32}", first)
    assert response[SEED] != first != "f" * 32
    assert response[FEATURE] == "changes-v2"
    assert FEATURE.lower() in response["Vary"].lower()
    assert "no-store" in response["Cache-Control"]


@pytest.mark.parametrize(
    "case", ["legacy", "unknown-feature", "no-binding", "error", "old-package"]
)
def test_unverified_or_old_capability_cannot_advertise_seed(
    case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy, unverified or old-package request never gets a seed advertised.

    Args:
        case: Reason the capability is unverified or old.
        monkeypatch: Patches the code under test for this test.
    """
    import dj_hyperview.realtime as api

    req = request()
    response = HttpResponse(status=503 if case == "error" else 200)
    response[SESSION_BINDING_HEADER] = "verified-owned-binding"
    response[SEED] = "old-shared-seed"
    response[FEATURE] = "changes-v2"
    if case == "legacy":
        req.hv_realtime_v1 = False
    elif case == "unknown-feature":
        req.META["HTTP_X_HYPERTODO_REALTIME_FEATURES"] = "changes-v3"
    elif case == "no-binding":
        del response[SESSION_BINDING_HEADER]
    elif case == "old-package":
        monkeypatch.delattr(api, "INVALIDATION_VERSIONS")
    module().mark_changes_response(req, response)
    assert SEED not in response and FEATURE not in response


@pytest.mark.parametrize(
    "mutation",
    ["a" * 39, "a" * 41, "A" * 40, "hvs1.private-session", "", "a" * 40 + "\n"],
)
def test_invalid_origin_is_unknown_without_auth_or_request_rejection(
    mutation: str,
) -> None:
    """An invalid mutation origin reads as unknown and rejects nothing.

    Args:
        mutation: Mutation origin value the client sends.
    """
    with module().mutation_context(request(mutation=mutation)):
        assert module().current_mutation() is None


def test_context_is_operation_not_owner_and_restores_after_failure() -> None:
    """The mutation context names the operation and is restored after a failure."""
    assert module().current_mutation() is None
    with module().mutation_context(request()):
        assert module().current_mutation() == "a" * 32 + "00000001"
        with pytest.raises(RuntimeError):
            with module().mutation_context(request(mutation="b" * 40)):
                assert module().current_mutation() == "b" * 40
                raise RuntimeError
        assert module().current_mutation() == "a" * 32 + "00000001"
        with module().mutation_context(request(method="GET")):
            assert module().current_mutation() is None
    assert module().current_mutation() is None


def test_entity_hmac_is_alias_resource_specific_and_secret_rotation_changes_epoch(
    settings: Settings,
) -> None:
    """Entity keys depend on alias and resource, and a new secret changes the epoch.

    Args:
        settings: Django settings overridden by this test.
    """
    settings.SECRET_KEY = "owned-fixture-secret"
    value = module().capture_entities("default", [("tasks", "private-id")])
    data = value.payload
    assert re.fullmatch("[0-9a-f]{16}", data["epoch"])
    assert re.fullmatch("[0-9a-f]{64}", data["items"][0]["key"])
    assert "private-id" not in json.dumps(data)
    assert (
        module().capture_entities("replica", [("tasks", "private-id")]).payload != data
    )
    assert (
        module().capture_entities("default", [("categories", "private-id")]).payload
        != data
    )
    data["items"].clear()
    assert len(value.payload["items"]) == 1
    previous = value.payload
    settings.SECRET_KEY = "owned-fixture-secret-rotated"
    assert (
        module().capture_entities("default", [("tasks", "private-id")]).payload["epoch"]
        != previous["epoch"]
    )


@pytest.mark.parametrize(
    "rows",
    [
        None,
        [],
        [("tasks", None)],
        [("foreign", "x")],
        [("tasks", str(i)) for i in range(33)],
    ],
)
def test_unknown_or_overflow_entities_are_broad_not_partial(
    rows: list[tuple[str, str | None]] | None,
) -> None:
    """Unknown or overflowing entity sets are dropped, so invalidation stays broad.

    Args:
        rows: Entity rows handed to the capture.
    """
    assert module().capture_entities("default", rows) is None


def test_entity_capture_stops_at_overflow_and_deduplicates() -> None:
    """Entity capture stops at the overflow limit and drops duplicate entities."""
    seen = []

    def rows() -> Iterator[tuple[str, str]]:
        for n in range(1000):
            seen.append(n)
            yield "tasks", str(n)

    assert module().capture_entities("default", rows()) is None
    assert len(seen) == 33
    assert (
        len(module().capture_entities("default", [("tasks", "x")] * 2).payload["items"])
        == 1
    )


def rich() -> dict[str, object]:
    """Build an invalidate event that carries a mutation origin and entities.

    Returns:
        The invalidate event with a mutation origin and entities.
    """
    return {
        "event": "invalidate",
        "data": {
            "version": 2,
            "resources": ["tasks"],
            "mutation_id": "a" * 40,
            "entities": {
                "epoch": "b" * 16,
                "items": [{"resource": "tasks", "key": "c" * 64}],
            },
        },
    }


@pytest.mark.parametrize("negotiated", [True, False])
def test_stream_projects_rich_event_only_for_negotiated_client(
    negotiated: bool,
) -> None:
    """The stream projects the rich event only for a client that negotiated changes.

    Args:
        negotiated: Whether the client negotiated change precision.
    """
    from todo.realtime_stream import _event

    value = rich()
    expected = (
        copy.deepcopy(value)
        if negotiated
        else {"event": "invalidate", "data": {"version": 1, "resources": ["tasks"]}}
    )
    assert _event(value, changes_v2=negotiated) == expected
    # A new client talking to an old server still has no origin/precision proof.
    assert _event(
        {"event": "invalidate", "data": {"version": 1, "resources": ["tasks"]}},
        changes_v2=True,
    )["data"] == {"version": 1, "resources": ["tasks"]}
    assert _event({"event": "resync", "data": {"version": 1}}, changes_v2=True) == {
        "event": "resync",
        "data": {"version": 1},
    }


@pytest.mark.parametrize(
    "case",
    ["extra", "mutation", "entity", "epoch", "duplicate", "foreign", "v2-resync"],
)
def test_stream_rejects_invalid_rich_envelope_even_when_projecting_legacy(
    case: str,
) -> None:
    """The stream rejects an invalid rich envelope even when projecting the legacy form.

    Args:
        case: Way the rich envelope is made invalid.
    """
    from todo.realtime_stream import _event

    value = rich()
    if case == "extra":
        value["data"]["actor"] = "private"
    elif case == "mutation":
        value["data"]["mutation_id"] = "A" * 40
    elif case == "entity":
        value["data"]["entities"]["items"][0]["key"] = "invalid"
    elif case == "epoch":
        value["data"]["entities"]["epoch"] = "unknown"
    elif case == "duplicate":
        value["data"]["entities"]["items"] *= 2
    elif case == "foreign":
        value["data"]["entities"]["items"][0]["resource"] = "ui"
    else:
        value = {"event": "resync", "data": {"version": 2}}
    with pytest.raises(ValueError, match="invalid-realtime-event"):
        _event(value, changes_v2=False)


@pytest.mark.django_db
def test_origin_and_entities_snapshot_before_commit_outlives_request_context(
    user: AbstractUser,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """The origin and entities are captured before commit and outlive the request.

    Args:
        user: Signed-in user who owns the data in this test.
        settings: Django settings overridden by this test.
        monkeypatch: Patches the code under test for this test.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    from todo import realtime_notifications as notifications

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG}
    seen = []
    monkeypatch.setattr(
        notifications, "_publish", lambda config, intent: seen.append(intent)
    )
    with django_capture_on_commit_callbacks(execute=True):
        with module().mutation_context(request()):
            task = Task.objects.create(user=user, title="Private title")
        assert not seen
    assert len(seen) == 1
    data = seen[0].payload
    assert data["version"] == 2 and data["mutation_id"] == "a" * 32 + "00000001"
    assert (
        data["entities"]
        == module().capture_entities("default", [("tasks", task.pk)]).payload
    )
    assert str(task.pk) not in json.dumps(data) and "Private" not in json.dumps(data)
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            with module().mutation_context(request(mutation="b" * 40)):
                task.title = "Rolled back"
                task.save()
            transaction.set_rollback(True)
    assert len(seen) == 1


@pytest.mark.django_db
def test_guarded_http_seed_and_post_context_not_admin_or_binding_failure(
    client: Client,
    user: AbstractUser,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """The session-state seed becomes the origin of a guarded POST; failures carry none.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
        settings: Django settings overridden by this test.
        monkeypatch: Patches the code under test for this test.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    from todo import realtime_notifications as notifications

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG}
    client.force_login(user)
    task = Task.objects.create(user=user, title="Private")
    headers = {CLIENT_CONTRACT_HEADER: CLIENT_CONTRACT, FEATURE: "changes-v2"}
    state = client.get("/hv/session-state/", headers=headers)
    assert state.status_code == 200 and re.fullmatch("[0-9a-f]{32}", state[SEED])
    headers["X-HyperTodo-Expected-Session"] = state[SESSION_BINDING_HEADER]
    headers[MUTATION] = state[SEED] + "00000001"
    seen = []
    monkeypatch.setattr(
        notifications, "_publish", lambda config, intent: seen.append(intent)
    )
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(f"/hv/tasks/{task.pk}/toggle/", headers=headers)
    assert response.status_code == 200 and len(seen) == 1
    assert seen[0].payload["mutation_id"] == headers[MUTATION]
    headers["X-HyperTodo-Expected-Session"] = "bad"
    denied = client.post(f"/hv/tasks/{task.pk}/toggle/", headers=headers)
    assert denied.status_code == 400 and SEED not in denied
    assert len(seen) == 1 and module().current_mutation() is None


def test_replaced_final_response_cannot_advertise_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A final response that replaces the original one cannot advertise a seed.

    Args:
        monkeypatch: Patches the code under test for this test.
    """
    req = request()
    original = HttpResponse()
    replaced = HttpResponse(status=503)
    replaced[SEED] = "cached"
    replaced[FEATURE] = "changes-v2"
    req._hv_session_response = (original, 200)
    response = SessionBindingResponseMiddleware(lambda _: replaced)(req)
    assert SEED not in response and FEATURE not in response


@pytest.mark.django_db
def test_a21_capability_fallback_emits_exact_v1_intent(
    user: AbstractUser,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """Without the package capability the notification falls back to version 1.

    Args:
        user: Signed-in user who owns the data in this test.
        settings: Django settings overridden by this test.
        monkeypatch: Patches the code under test for this test.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    import dj_hyperview.realtime as api

    from todo import realtime_notifications as notifications

    monkeypatch.delattr(api, "INVALIDATION_VERSIONS")
    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG}
    seen = []
    monkeypatch.setattr(
        notifications, "_publish", lambda config, intent: seen.append(intent)
    )
    with django_capture_on_commit_callbacks(execute=True):
        with module().mutation_context(request()):
            Task.objects.create(user=user, title="Legacy")
    assert seen[0].payload == {"version": 1, "resources": ["tasks"]}


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("negotiated", [True, False])
def test_actual_asgi_projects_events_and_emits_seed_only_after_ack(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    monkeypatch: pytest.MonkeyPatch,
    negotiated: bool,
) -> None:
    """The real ASGI chain projects events and emits the seed only after the ack.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        monkeypatch: Patches the code under test for this test.
        negotiated: Whether the client negotiated change precision.
    """
    from asgiref.sync import async_to_sync

    from tests.test_realtime_endpoint import asgi_exchange
    from tests.test_realtime_stream import Broker, Subscription
    from todo import realtime_views

    req = authenticated[2]
    if negotiated:
        req.META["HTTP_X_HYPERTODO_REALTIME_FEATURES"] = "changes-v2"

    async def run() -> None:
        sub = Subscription(rich())
        monkeypatch.setattr(realtime_views, "_broker", lambda config: Broker(sub))
        sent = await asgi_exchange(req)
        headers = {key.lower(): value for key, value in sent[0]["headers"]}
        assert sent[0]["status"] == 200 and sub.closed == 1
        assert (SEED.lower().encode() in headers) is negotiated
        if negotiated:
            assert re.fullmatch(b"[0-9a-f]{32}", headers[SEED.lower().encode()])
        body = b"".join(item.get("body", b"") for item in sent)
        data = json.loads(body.split(b"data: ", 1)[1])
        assert (
            data == rich()["data"]
            if negotiated
            else data == {"version": 1, "resources": ["tasks"]}
        )

    async_to_sync(run)()


@pytest.mark.django_db
def test_incompatible_precision_never_drops_resource_invalidation(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """An incompatible entity precision still publishes the resource invalidation.

    Args:
        settings: Django settings overridden by this test.
        monkeypatch: Patches the code under test for this test.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    from todo import realtime_notifications as notifications

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG}
    seen = []
    monkeypatch.setattr(
        notifications, "_publish", lambda config, intent: seen.append(intent)
    )
    with django_capture_on_commit_callbacks(execute=True):
        notifications.notify_after_commit(
            using="default", owners=(1,), resources=("tasks",), entities=(("ui", 1),)
        )
    assert seen[0].payload == {
        "version": 2,
        "resources": ["tasks"],
        "mutation_id": None,
        "entities": None,
    }
