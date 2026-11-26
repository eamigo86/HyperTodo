"""The real Django ASGI chain and public package SSE response ownership."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Never

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from dj_hyperview.realtime import realtime_asgi
from django.conf import settings as django_settings
from django.contrib.auth.models import AbstractUser
from django.contrib.sessions.models import Session
from django.core.asgi import get_asgi_application
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpRequest, HttpResponse
from django.test import Client
from pytest_django.fixtures import Settings

from tests.test_realtime_stream import (
    RESYNC,
    Broker,
    Subscription,
)
from tests.test_realtime_stream import (
    authenticated as authenticated,
)

pytestmark = pytest.mark.django_db(transaction=True)


async def asgi_exchange(
    request: WSGIRequest,
    *,
    before_send: Callable[[dict[str, object]], Awaitable[None]] | None = None,
    disconnect_after_body: bool = True,
    script_name: str = "",
) -> list[dict[str, object]]:
    """Run one request through the real ASGI application and collect what it sends.

    Args:
        request: Request the ASGI scope is built from.
        before_send: Coroutine function awaited for every event the application sends.
        disconnect_after_body: Whether the client disconnects once the response body is
        sent.
        script_name: Script prefix the application is mounted under.

    Returns:
        The ASGI events the application sent.
    """
    queue = asyncio.Queue()
    sent = []
    queue.put_nowait({"type": "http.request", "body": b"", "more_body": False})
    cookie_name = django_settings.SESSION_COOKIE_NAME
    cookie = f"{cookie_name}={request.COOKIES.get(cookie_name, '')}"
    headers = [(b"host", b"testserver"), (b"cookie", cookie.encode())]
    headers.extend(
        (key.lower().encode(), value.encode())
        for key, value in request.headers.items()
        if key.lower().startswith("x-hypertodo") or key.lower() == "origin"
    )
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": request.method,
        "scheme": "http",
        "path": f"{script_name}/realtime/events/",
        "raw_path": f"{script_name}/realtime/events/".encode(),
        "query_string": request.META.get("QUERY_STRING", "").encode(),
        "root_path": script_name,
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 41000),
        "headers": headers,
    }

    async def send(event: dict[str, object]) -> None:
        sent.append(event)
        if before_send:
            await before_send(event)
        if disconnect_after_body and event["type"] == "http.response.body":
            queue.put_nowait({"type": "http.disconnect"})

    await asyncio.wait_for(
        realtime_asgi(get_asgi_application())(scope, queue.get, send), 3
    )
    return sent


def test_real_asgi_initial_resync_then_disconnect_closes_subscription(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real ASGI chain resyncs first and closes the subscription on disconnect.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        monkeypatch: Patches the code under test for this test.
    """
    from todo import realtime_views
    from todo.realtime_stream import admissions

    async def run() -> None:
        sub = Subscription(RESYNC)
        monkeypatch.setattr(realtime_views, "_broker", lambda config: Broker(sub))
        sent = await asgi_exchange(authenticated[2])
        start = sent[0]
        assert start["type"] == "http.response.start" and start["status"] == 200
        headers = {key.lower(): value for key, value in start["headers"]}
        assert headers[b"content-type"].startswith(b"text/event-stream")
        assert headers[b"x-hypertodo-session-binding"].decode() == authenticated[3]
        assert b"x-hypertodo-theme" not in headers
        assert b"access-control-allow-origin" not in headers
        body = b"".join(item.get("body", b"") for item in sent)
        assert body == b'event: resync\ndata: {"version":1}\n\n'
        assert sub.closed == 1 and admissions.total == 0

    async_to_sync(run)()


def test_the_stream_runs_under_a_script_name_without_presentation_headers(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stream runs under a script name and carries no presentation headers.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        monkeypatch: Patches the code under test for this test.
    """
    from todo import realtime_views
    from todo.realtime_stream import admissions

    async def run() -> None:
        sub = Subscription(RESYNC)
        monkeypatch.setattr(realtime_views, "_broker", lambda config: Broker(sub))
        sent = await asgi_exchange(authenticated[2], script_name="/app")
        assert sent[0]["status"] == 200
        headers = {key.lower(): value for key, value in sent[0]["headers"]}
        assert headers[b"content-type"].startswith(b"text/event-stream")
        # The route is still recognised behind the prefix, so the presentation
        # middleware stands aside exactly as it does at the root.
        assert b"x-hypertodo-theme" not in headers
        assert sub.closed == 1 and admissions.total == 0

    async_to_sync(run)()


def test_a_non_get_method_is_rejected_before_csrf_under_a_script_name(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """A non-GET method is rejected before the CSRF check, even under a script name.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    request = authenticated[2]
    request.method = "POST"

    sent = async_to_sync(asgi_exchange)(request, script_name="/app")

    assert sent[0]["status"] == 405
    headers = {key.lower(): value for key, value in sent[0]["headers"]}
    assert headers[b"allow"] == b"GET"


@pytest.mark.parametrize(
    "case,status",
    [
        ("disabled", 404),
        ("method", 405),
        ("contract", 403),
        ("mismatch", 403),
        ("origin", 403),
        ("query", 403),
        ("anonymous", 401),
    ],
)
def test_real_asgi_denials_never_subscribe_or_include_private_metadata(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    case: str,
    status: int,
) -> None:
    """Real ASGI denials never subscribe to the broker or expose private metadata.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        monkeypatch: Patches the code under test for this test.
        settings: Django settings overridden by this test.
        case: Kind of denial the request is set up to trigger.
        status: Status code the denial is expected to return.
    """
    from todo import realtime_views

    request = authenticated[2]
    if case == "disabled":
        settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": None}
    elif case == "method":
        request.method = "PUT"
    elif case == "contract":
        request.META["HTTP_X_HYPERTODO_CLIENT_CONTRACT"] = "unknown"
    elif case == "mismatch":
        request.META["HTTP_X_HYPERTODO_EXPECTED_SESSION"] = "hvs1." + "x" * 43
    elif case == "origin":
        request.META["HTTP_ORIGIN"] = "http://evil.example"
    elif case == "query":
        request.META["QUERY_STRING"] = "topics=foreign"
    else:
        request.COOKIES.clear()

    def forbidden(config: object) -> Never:
        raise AssertionError("denial must not acquire broker")

    monkeypatch.setattr(realtime_views, "_broker", forbidden)
    sent = async_to_sync(asgi_exchange)(request)
    assert sent[0]["status"] == status
    headers = {key.lower(): value for key, value in sent[0]["headers"]}
    assert headers[b"content-type"].startswith(b"application/json")
    for name in [
        b"x-hypertodo-theme",
        b"x-hypertodo-session-binding",
        b"location",
        b"access-control-allow-origin",
    ]:
        assert name not in headers
    if status == 405:
        assert headers[b"allow"] == b"GET"
    assert b"no-store" in headers[b"cache-control"]


def test_no_headers_before_broker_ack_and_fresh_auth_check(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No headers are sent before the broker ack and the fresh authentication check.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        monkeypatch: Patches the code under test for this test.
    """
    from todo import realtime_views
    from todo.realtime_stream import admissions

    async def run() -> None:
        sub = Subscription(RESYNC)
        started = asyncio.Event()
        release = asyncio.Event()
        response_started = False

        class DeferredBroker:
            async def subscribe(self, topics: Sequence[str]) -> Subscription:
                started.set()
                await release.wait()
                return sub

        monkeypatch.setattr(realtime_views, "_broker", lambda config: DeferredBroker())

        async def on_send(event: dict[str, object]) -> None:
            nonlocal response_started
            response_started = True

        task = asyncio.create_task(asgi_exchange(authenticated[2], before_send=on_send))
        await started.wait()
        assert not response_started and admissions.total == 1

        def revoke_from_independent_connection() -> None:
            from django.db import connection

            try:
                Session.objects.filter(
                    session_key=authenticated[2]._test_session_key
                ).delete()
            finally:
                # Django intentionally keeps in-memory test connections open, and
                # this actor thread comes from the default executor, which the
                # identity checks share: close the SQLite handle, and tell Django's
                # wrapper so the next job on this thread opens a fresh one.
                if connection.connection is not None:
                    connection.connection.close()
                    connection.connection = None

        await sync_to_async(
            revoke_from_independent_connection, thread_sensitive=False
        )()
        release.set()
        sent = await task
        assert sent[0]["status"] == 401
        assert sub.closed == 1 and admissions.total == 0

    # Capture sync session key before entering async; no ORM through cached client.
    key = authenticated[0].session.session_key
    authenticated[2]._test_session_key = key
    async_to_sync(run)()


def test_response_constructor_failure_releases_before_503(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing response constructor releases the reservation before the 503 answer.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        monkeypatch: Patches the code under test for this test.
    """
    from todo import realtime_views
    from todo.realtime_stream import admissions

    async def run() -> None:
        sub = Subscription(RESYNC)
        monkeypatch.setattr(realtime_views, "_broker", lambda config: Broker(sub))

        def fail(*args: object, **kwargs: object) -> Never:
            raise RuntimeError("private constructor failure")

        monkeypatch.setattr(realtime_views, "sse_response", fail)
        sent = await asgi_exchange(authenticated[2])
        assert sent[0]["status"] == 503
        assert sub.closed == 1 and admissions.total == 0
        assert b"private" not in b"".join(item.get("body", b"") for item in sent)

    async_to_sync(run)()


@pytest.mark.parametrize("method", ["POST", "DELETE", "PUT", "OPTIONS", "HEAD"])
@pytest.mark.parametrize("enabled", [True, False])
def test_non_get_method_rejected_before_csrf_without_business(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    method: str,
    enabled: bool,
) -> None:
    """A non-GET method is rejected before the CSRF check and before any business work.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        monkeypatch: Patches the code under test for this test.
        settings: Django settings overridden by this test.
        method: HTTP method of the request.
        enabled: Whether realtime is enabled in the settings.
    """
    from todo import realtime_views

    request = authenticated[2]
    request.method = method
    if not enabled:
        settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": None}

    def forbidden(config: object) -> Never:
        raise AssertionError("method rejection must not acquire broker")

    monkeypatch.setattr(realtime_views, "_broker", forbidden)
    sent = async_to_sync(asgi_exchange)(request)
    assert sent[0]["status"] == (405 if enabled else 404)
    headers = {key.lower(): value for key, value in sent[0]["headers"]}
    assert headers.get(b"allow") == (b"GET" if enabled else None)
    assert b"x-hypertodo-session-binding" not in headers


@pytest.mark.parametrize("path", ["/realtime/events/extra", "/hv/login/"])
def test_method_guard_does_not_match_other_routes(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str], path: str
) -> None:
    """The method guard leaves other routes to their own handlers.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        path: Path of a route that is not the stream.
    """
    from django.http import HttpResponse

    from todo.realtime_middleware import RealtimeMethodMiddleware

    request = authenticated[2]
    request.path = request.path_info = path
    request.method = "POST"
    seen = []

    def next_handler(incoming: HttpRequest) -> HttpResponse:
        seen.append(incoming)
        return HttpResponse(status=418)

    response = RealtimeMethodMiddleware(next_handler)(request)
    assert seen == [request] and response.status_code == 418


@pytest.mark.parametrize("method,expected,calls", [("GET", 418, 1), ("POST", 405, 0)])
def test_async_method_middleware_preserves_async_handler(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    method: str,
    expected: int,
    calls: int,
) -> None:
    """The method middleware keeps an asynchronous handler asynchronous.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        method: HTTP method of the request.
        expected: Status code the middleware is expected to return.
        calls: Number of times the wrapped handler is expected to run.
    """
    from django.http import HttpResponse

    from todo.realtime_middleware import RealtimeMethodMiddleware

    request = authenticated[2]
    request.method = method

    async def run() -> None:
        seen = []

        async def next_handler(incoming: HttpRequest) -> HttpResponse:
            seen.append(incoming)
            return HttpResponse(status=418)

        response = await RealtimeMethodMiddleware(next_handler)(request)
        assert response.status_code == expected and len(seen) == calls

    async_to_sync(run)()


def test_view_itself_refuses_methods_even_without_middleware(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """The view refuses unsupported methods even without the middleware.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    from todo.realtime_views import events

    authenticated[2].method = "DELETE"
    response = async_to_sync(events)(authenticated[2])
    assert response.status_code == 405 and response["Allow"] == "GET"


def test_cancel_before_subscription_ack_releases_reservation(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling before the subscription is acknowledged releases the reservation.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        monkeypatch: Patches the code under test for this test.
    """
    from todo import realtime_views
    from todo.realtime_stream import admissions

    async def run() -> None:
        started = asyncio.Event()

        class WaitingBroker:
            async def subscribe(self, topics: Sequence[str]) -> None:
                started.set()
                await asyncio.Event().wait()

        monkeypatch.setattr(realtime_views, "_broker", lambda config: WaitingBroker())
        pending = asyncio.create_task(realtime_views.events(authenticated[2]))
        await started.wait()
        assert admissions.total == 1
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert admissions.total == 0

    async_to_sync(run)()


def test_real_broker_factory_constructs_without_network(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real broker factory builds a Redis broker without opening a connection.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        monkeypatch: Patches the code under test for this test.
    """
    import socket

    from dj_hyperview.realtime import RedisBroker

    from todo.realtime_auth import authorize
    from todo.realtime_views import _broker

    access = async_to_sync(authorize)(authenticated[2])

    def forbidden(*args: object, **kwargs: object) -> Never:
        raise AssertionError("constructor must not connect")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    assert isinstance(_broker(access.config), RedisBroker)
