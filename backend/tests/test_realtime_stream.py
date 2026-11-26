"""Fresh Django authentication and bounded app-owned streaming resources."""

import asyncio
import copy
import gc
import threading
from collections.abc import Coroutine, Sequence
from dataclasses import FrozenInstanceError
from datetime import timedelta
from typing import Never, Self

import pytest
from asgiref.sync import ThreadSensitiveContext, async_to_sync
from django.contrib.auth.models import AbstractUser
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.exceptions import ImproperlyConfigured
from django.core.handlers.wsgi import WSGIRequest
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.test import Client, RequestFactory
from django.test.utils import override_script_prefix
from django.utils import timezone
from pytest_django.fixtures import DjangoAssertNumQueries, Settings

from tests.test_session_contract import _confirm
from todo.realtime_auth import Access, Identity
from todo.session_contract import (
    CLIENT_CONTRACT_HEADER,
    EXPECTED_SESSION_HEADER,
)

pytestmark = pytest.mark.django_db(transaction=True)
CONFIG = {"REDIS_URL": "redis://127.0.0.1:6379/14", "NAMESPACE": "stream-tests"}
RESYNC = {"event": "resync", "data": {"version": 1}}
HINT = {"event": "invalidate", "data": {"version": 1, "resources": ["tasks"]}}


@pytest.fixture
def authenticated(
    client: Client, user: AbstractUser, settings: Settings
) -> tuple[Client, AbstractUser, WSGIRequest, str]:
    """Sign a user in and build a realtime stream request bound to that session.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
        settings: Django settings overridden by this test.

    Returns:
        The client, the user, the stream request and the session binding.
    """
    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG.copy()}
    client.force_login(user)
    binding, _ = _confirm(client, True)
    request = RequestFactory().get(
        "/realtime/events/",
        headers={
            CLIENT_CONTRACT_HEADER: "realtime-v1",
            EXPECTED_SESSION_HEADER: binding,
        },
    )
    request.COOKIES[settings.SESSION_COOKIE_NAME] = client.cookies[
        settings.SESSION_COOKIE_NAME
    ].value
    return client, user, request, binding


def access_for(authenticated: tuple[Client, AbstractUser, WSGIRequest, str]) -> Access:
    """Authorize the stream request of an authenticated session.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.

    Returns:
        The access that authorization grants.
    """
    from todo.realtime_auth import authorize

    return async_to_sync(authorize)(authenticated[2])


def test_fresh_auth_uses_database_session_not_cached_request_user(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """Fresh authentication reads the database session, not the cached request user.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    from todo.realtime_auth import authorize, fresh_identity

    client, user, request, binding = authenticated
    request.user = user
    request.session = client.session
    assert request.session.get("_auth_user_id") == str(user.pk)
    access = async_to_sync(authorize)(request)
    assert access.identity.binding == binding
    assert access.identity.using == "default"
    assert access.identity.user_id == str(user.pk)
    with pytest.raises(FrozenInstanceError):
        access.identity.user_id = "other"
    Session.objects.filter(session_key=access.session_key).delete()
    assert request.user.is_authenticated
    assert request.session.get("_auth_user_id") == str(user.pk)
    assert fresh_identity(access.session_key) is None


@pytest.mark.parametrize(
    "revocation", ["expired", "inactive", "password", "deleted", "backend"]
)
def test_real_django_session_revocation(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str], revocation: str
) -> None:
    """Revoking the Django session in any supported way denies authorization.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        revocation: Way the Django session is revoked.
    """
    from todo.realtime_auth import fresh_identity

    client, user, _, _ = authenticated
    key = client.session.session_key
    assert fresh_identity(key) is not None
    if revocation == "expired":
        Session.objects.filter(session_key=key).update(
            expire_date=timezone.now() - timedelta(seconds=1)
        )
    elif revocation == "inactive":
        user.is_active = False
        user.save(update_fields=["is_active"])
    elif revocation == "password":
        user.set_password("changed-fixture-only")
        user.save(update_fields=["password"])
    elif revocation == "deleted":
        Session.objects.filter(session_key=key).delete()
    else:
        session = client.session
        session["_auth_user_backend"] = "unknown.Backend"
        session.save()
    assert fresh_identity(key) is None


def test_a_session_only_a_fallback_secret_verifies_is_not_rotated_or_deleted(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str], settings: Settings
) -> None:
    """A session that only a fallback secret verifies is neither rotated nor deleted.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        settings: Django settings overridden by this test.
    """
    from todo.realtime_auth import fresh_identity
    from todo.session_contract import session_binding

    client, user, _, _ = authenticated
    key = client.session.session_key
    # The secret rotated after this session was issued, so only the fallback still
    # verifies its auth hash. Django answers that with cycle_key(), which deletes the
    # row the client holds; an event stream has no response cookie to hand over the
    # replacement, so the user would be logged out without a word.
    settings.SECRET_KEY_FALLBACKS = [settings.SECRET_KEY]
    settings.SECRET_KEY = "rotated-" + settings.SECRET_KEY
    before = set(Session.objects.values_list("session_key", flat=True))

    identity = fresh_identity(key)

    assert identity is not None and identity.user_id == str(user.pk)
    assert set(Session.objects.values_list("session_key", flat=True)) == before
    held = HttpRequest()
    held.session = SessionStore(session_key=key)
    held.user = user
    assert identity.binding == session_binding(held)


def test_a_session_whose_auth_hash_fails_is_refused_but_left_for_the_next_request(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """A session whose auth hash fails is refused but left for the next request.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    from todo.realtime_auth import fresh_identity

    client, user, _, _ = authenticated
    key = client.session.session_key
    user.set_password("changed-fixture-only")
    user.save(update_fields=["password"])

    assert fresh_identity(key) is None

    # Django's get_user flushes such a session; here that must stay in memory, so the
    # stream never writes. The next ordinary request clears the row with its response.
    assert Session.objects.filter(session_key=key).exists()


def test_each_identity_check_runs_off_the_callers_thread_and_closes_its_connection(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each identity check runs off the caller's thread and closes its connection.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        monkeypatch: Patches the code under test for this test.
    """
    from todo import realtime_auth

    ran, closed = [], []
    real = realtime_auth.fresh_identity
    real_close = realtime_auth.close_old_connections

    def spy(session_key: str | None) -> Identity | None:
        ran.append(threading.get_ident())
        return real(session_key)

    def closing() -> None:
        closed.append(1)
        real_close()

    monkeypatch.setattr(realtime_auth, "fresh_identity", spy)
    monkeypatch.setattr(realtime_auth, "close_old_connections", closing)

    identity = async_to_sync(realtime_auth.fresh_identity_async)(
        authenticated[0].session.session_key
    )

    assert identity is not None
    assert len(ran) == 1 and ran[0] != threading.get_ident()
    assert closed == [1]


def test_a_failing_identity_check_still_closes_its_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing identity check still closes its database connection.

    Args:
        monkeypatch: Patches the code under test for this test.
    """
    from todo import realtime_auth

    closed = []

    def broken(session_key: str | None) -> Never:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(realtime_auth, "fresh_identity", broken)
    monkeypatch.setattr(
        realtime_auth, "close_old_connections", lambda: closed.append(1)
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        async_to_sync(realtime_auth.fresh_identity_async)("any-session-key")

    assert closed == [1]


def test_open_streams_share_the_default_executor_for_their_identity_checks(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Open streams share the default executor for their identity checks.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        monkeypatch: Patches the code under test for this test.
    """
    from todo import realtime_auth

    key = authenticated[0].session.session_key
    threads = set()
    real = SessionStore._get_session_from_db

    def spy(self: SessionStore) -> dict[str, object]:
        threads.add(threading.get_ident())
        return real(self)

    monkeypatch.setattr(SessionStore, "_get_session_from_db", spy)

    async def one_stream() -> None:
        # ASGIHandler gives every request a thread-sensitive context of its own, and
        # thread-sensitive work then runs on a thread that context keeps for good.
        async with ThreadSensitiveContext():
            for _ in range(2):
                assert await realtime_auth.fresh_identity_async(key) is not None

    async def run() -> None:
        await asyncio.gather(*(one_stream() for _ in range(40)))

    # No async_to_sync here: a sync caller above would run everything on its own thread
    # and hide the per-request executors a real ASGI server creates.
    asyncio.run(run())

    # The default executor never grows past 32 threads, and 40 streams were open.
    assert len(threads) < 40


@pytest.mark.parametrize(
    "engine",
    [
        "django.contrib.sessions.backends.signed_cookies",
        "django.contrib.sessions.backends.cache",
        "django.contrib.sessions.backends.cached_db",
    ],
)
def test_enabled_realtime_requires_actual_database_session_engine(
    settings: Settings, engine: str
) -> None:
    """Enabled realtime requires the database session engine.

    Args:
        settings: Django settings overridden by this test.
        engine: Session backend that realtime does not support.
    """
    from todo.realtime_config import get_realtime_config

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG.copy()}
    settings.SESSION_ENGINE = engine
    with pytest.raises(ImproperlyConfigured, match="database sessions"):
        get_realtime_config()
    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": None}
    assert get_realtime_config() is None


@pytest.mark.parametrize(
    "case,status",
    [
        ("disabled", 404),
        ("method", 405),
        ("contract", 403),
        ("expected", 403),
        ("mismatch", 403),
        ("query", 403),
        ("origin", 403),
        ("null-origin", 403),
        ("anonymous", 401),
    ],
)
def test_route_specific_denials_before_broker(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    settings: Settings,
    case: str,
    status: int,
) -> None:
    """Route-specific denials are decided before the broker is reached.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        settings: Django settings overridden by this test.
        case: Kind of denial the request is set up to trigger.
        status: Status code the request is expected to receive.
    """
    from todo.realtime_auth import RealtimeDenied, authorize

    _, _, request, _ = authenticated
    if case == "disabled":
        settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": None}
    elif case == "method":
        request.method = "POST"
    elif case == "contract":
        request.META["HTTP_X_HYPERTODO_CLIENT_CONTRACT"] = "unknown"
    elif case == "expected":
        request.META.pop("HTTP_X_HYPERTODO_EXPECTED_SESSION")
    elif case == "mismatch":
        request.META["HTTP_X_HYPERTODO_EXPECTED_SESSION"] = "hvs1." + "a" * 43
    elif case == "query":
        request.META["QUERY_STRING"] = "topics=private"
    elif case == "origin":
        request.META["HTTP_ORIGIN"] = "http://other.example"
    elif case == "null-origin":
        request.META["HTTP_ORIGIN"] = "null"
    else:
        request.COOKIES.clear()
    with pytest.raises(RealtimeDenied) as denied:
        async_to_sync(authorize)(request)
    assert denied.value.status == status


def test_same_origin_and_native_no_origin_are_both_supported(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """A same-origin request and a native request without Origin are both admitted.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    from todo.realtime_auth import authorize

    _, _, request, binding = authenticated
    assert async_to_sync(authorize)(request).identity.binding == binding
    request.META["HTTP_ORIGIN"] = "http://testserver"
    assert async_to_sync(authorize)(request).identity.binding == binding


def test_topics_are_server_selected_from_principal_and_template_sources(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str], settings: Settings
) -> None:
    """The server selects the topics from the principal and the template sources.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        settings: Django settings overridden by this test.
    """
    from todo.realtime_auth import topics_for
    from todo.realtime_notifications import private_topic, ui_topic

    access = access_for(authenticated)
    settings.HYPERVIEW = {
        **settings.HYPERVIEW,
        "SOURCES": [
            {
                "BACKEND": "dj_hyperview.contrib.database.sources.DatabaseSource",
                "OPTIONS": {"using": "templates"},
            },
            {
                "BACKEND": "dj_hyperview.contrib.database.sources.DatabaseSource",
                "OPTIONS": {"using": "templates"},
            },
            {"BACKEND": "dj_hyperview.sources.FileSystemSource"},
        ],
    }
    assert topics_for(access.identity) == (
        private_topic("default", authenticated[1].pk),
        ui_topic("templates"),
    )


class Subscription:
    """Fake broker subscription that yields the items queued for it."""

    def __init__(self, *items: dict[str, object] | None) -> None:
        """Queue the items that the subscription yields.

        Args:
            *items: Items the subscription yields, in order.
        """
        self.items = asyncio.Queue()
        for item in items:
            self.items.put_nowait(item)
        self.closed = 0
        self.failure = None

    def __aiter__(self) -> Self:
        """Return the subscription itself as its async iterator.

        Returns:
            This subscription.
        """
        return self

    async def __anext__(self) -> dict[str, object] | None:
        """Return the next queued item, or raise the configured failure.

        Returns:
            The next item of the subscription.
        """
        if self.failure:
            raise self.failure
        return await self.items.get()

    async def aclose(self) -> None:
        """Record that the subscription was closed."""
        self.closed += 1


class Broker:
    """Fake broker that hands out one prepared subscription."""

    def __init__(self, subscription: Subscription) -> None:
        """Remember the subscription that every subscribe call returns.

        Args:
            subscription: Subscription that every subscribe call returns.
        """
        self.subscription = subscription
        self.topics = None
        self.failure = None

    async def subscribe(self, topics: Sequence[str]) -> Subscription:
        """Record the topics, then return the subscription or raise the failure.

        Args:
            topics: Topics the stream subscribes to.

        Returns:
            The prepared subscription.
        """
        self.topics = topics
        if self.failure:
            raise self.failure
        return self.subscription


class SteppedLoop(asyncio.SelectorEventLoop):
    """An event loop whose clock jumps a whole second per iteration and never waits.

    Every timer due within that second fires at the start of the next iteration, in
    the same batch as the callbacks that are already waiting. That is the
    interleaving of "a hint arrives just as the heartbeat expires", reproduced
    without racing the real clock.
    """

    def __init__(self) -> None:
        """Create the loop with a zeroed clock and a selector that never waits."""
        super().__init__()
        self._ticks = 0
        select = self._selector.select

        def step(timeout: float | None = None) -> list[tuple[object, int]]:
            self._ticks += 1
            return select(0)

        self._selector.select = step

    def time(self) -> float:
        """Return the current tick as the loop clock.

        Returns:
            The number of loop iterations so far, in seconds.
        """
        return float(self._ticks)


def run_stepped(coroutine: Coroutine[object, object, object]) -> object:
    """Run a coroutine on a stepped event loop and return its result.

    Args:
        coroutine: Coroutine to run on the stepped loop.

    Returns:
        The value the coroutine returns.
    """
    with asyncio.Runner(loop_factory=SteppedLoop) as runner:
        return runner.run(coroutine)


def standalone_access() -> Access:
    """Authority for tests that never touch Django: no config, session or database.

    Returns:
        An access with no configuration and a fixed identity.
    """
    from todo.realtime_auth import Access, Identity

    identity = Identity("default", "1", "hvs1." + "x" * 43)
    return Access(None, identity, "session-key")


def test_stream_rechecks_before_initial_resync_and_every_frame(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """The stream re-checks authentication before the resync and before every frame.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run() -> None:
        reads = []

        async def fresh(key: str | None) -> Identity | None:
            reads.append(key)
            return access.identity

        sub = Subscription(RESYNC, HINT)
        pool = Admissions()
        stream = await open_stream(access, Broker(sub), admissions=pool, fresh=fresh)
        assert len(reads) == 1  # subscribe ACK completed, before response ownership.
        assert await anext(stream) == RESYNC
        assert await anext(stream) == HINT
        assert len(reads) == 3
        await stream.aclose()
        await stream.aclose()
        assert sub.closed == 1 and pool.total == 0

    async_to_sync(run)()


def test_auth_loss_between_frames_emits_only_auth_required_then_closes(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """Losing authentication between frames emits only auth-required, then closes.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run() -> None:
        current = access.identity

        async def fresh(key: str | None) -> Identity | None:
            return current

        sub = Subscription(RESYNC, HINT)
        pool = Admissions()
        stream = await open_stream(access, Broker(sub), admissions=pool, fresh=fresh)
        assert await anext(stream) == RESYNC
        current = None
        assert await anext(stream) == {"event": "auth-required", "data": {"version": 1}}
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        assert sub.closed == 1 and pool.total == 0

    async_to_sync(run)()


def test_heartbeat_requires_fresh_auth_and_lifetime_closes(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """A heartbeat needs fresh authentication, and the lifetime limit closes the stream.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run() -> None:
        reads = 0

        async def fresh(key: str | None) -> Identity | None:
            nonlocal reads
            reads += 1
            return access.identity

        sub = Subscription(RESYNC)
        pool = Admissions()
        stream = await open_stream(
            access,
            Broker(sub),
            admissions=pool,
            fresh=fresh,
            heartbeat=0.005,
            lifetime=0.03,
        )
        assert await anext(stream) == RESYNC
        assert await anext(stream) is None
        assert reads == 3
        async for _ in stream:
            pass
        assert sub.closed == 1 and pool.total == 0

    async_to_sync(run)()


def test_a_hint_taken_as_the_heartbeat_expires_is_delivered_not_dropped() -> None:
    """A hint taken just as the heartbeat expires is delivered, not dropped."""
    from todo.realtime_stream import Admissions, open_stream

    access = standalone_access()

    async def run() -> None:
        async def fresh(key: str | None) -> Identity | None:
            return access.identity

        pool = Admissions()
        sub = Subscription(HINT)
        stream = await open_stream(
            access,
            Broker(sub),
            admissions=pool,
            fresh=fresh,
            heartbeat=0.5,
            lifetime=3600,
        )
        # The read task takes HINT on its first step, in the same loop iteration whose
        # batch also holds the heartbeat timer. Cancelling the read at that point used
        # to throw away an item it had already removed from the queue.
        assert await anext(stream) == HINT
        assert await anext(stream) is None
        await stream.aclose()
        assert sub.closed == 1 and pool.total == 0

    run_stepped(run())


class CountingSubscription(Subscription):
    """Subscription that counts its reads and the reads that were cancelled."""

    def __init__(self, *items: dict[str, object] | None) -> None:
        """Queue the items and start the read counters at zero.

        Args:
            *items: Items the subscription yields, in order.
        """
        super().__init__(*items)
        self.reads = 0
        self.cancelled = 0

    async def __anext__(self) -> dict[str, object] | None:
        """Count the read, and count it as cancelled when it is cancelled.

        Returns:
            The next item of the subscription.
        """
        self.reads += 1
        try:
            return await super().__anext__()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise


def test_one_read_stays_pending_across_heartbeats() -> None:
    """One subscription read stays pending across heartbeats."""
    from todo.realtime_stream import Admissions, open_stream

    access = standalone_access()

    async def run() -> None:
        async def fresh(key: str | None) -> Identity | None:
            return access.identity

        sub = CountingSubscription()
        stream = await open_stream(
            access,
            Broker(sub),
            admissions=Admissions(),
            fresh=fresh,
            heartbeat=0.5,
            lifetime=3600,
        )
        for _ in range(3):
            assert await anext(stream) is None
        sub.items.put_nowait(HINT)
        assert await anext(stream) == HINT
        # Three heartbeats and the hint were all served by the first read.
        assert sub.reads == 1 and sub.cancelled == 0
        await stream.aclose()

    run_stepped(run())


def test_closing_cancels_the_read_a_heartbeat_left_pending() -> None:
    """Closing the stream cancels the read that a heartbeat left pending."""
    from todo.realtime_stream import Admissions, open_stream

    access = standalone_access()

    async def run() -> None:
        async def fresh(key: str | None) -> Identity | None:
            return access.identity

        pool = Admissions()
        sub = CountingSubscription()
        stream = await open_stream(
            access, Broker(sub), admissions=pool, fresh=fresh, heartbeat=0.5
        )
        assert await anext(stream) is None
        assert sub.cancelled == 0  # still waiting for the next hint
        await stream.aclose()
        assert sub.cancelled == 1 and sub.closed == 1 and pool.total == 0

    run_stepped(run())


def test_a_read_that_failed_while_a_heartbeat_was_pending_is_not_left_unretrieved() -> (
    None
):
    """A read that failed while a heartbeat was pending is not left unretrieved."""
    from todo.realtime_stream import Admissions, open_stream

    access = standalone_access()
    unretrieved = []

    async def run() -> None:
        asyncio.get_running_loop().set_exception_handler(
            lambda loop, context: unretrieved.append(context["message"])
        )

        class Failing(Subscription):
            def __init__(self) -> None:
                super().__init__()
                self.outcome = asyncio.get_running_loop().create_future()

            async def __anext__(self) -> dict[str, object] | None:
                return await self.outcome

        async def fresh(key: str | None) -> Identity | None:
            return access.identity

        sub = Failing()
        stream = await open_stream(
            access, Broker(sub), admissions=Admissions(), fresh=fresh, heartbeat=0.5
        )
        assert await anext(stream) is None
        sub.outcome.set_exception(RuntimeError("the broker dropped the connection"))
        await asyncio.sleep(0)
        await stream.aclose()

    run_stepped(run())
    gc.collect()
    assert unretrieved == []


def test_caps_are_per_principal_across_bindings_and_release_without_iteration(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """Stream caps are per principal across bindings and are released without iterating.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run() -> None:
        async def fresh(key: str | None) -> Identity | None:
            return access.identity

        pool = Admissions()
        streams = [
            await open_stream(
                access, Broker(Subscription(RESYNC)), admissions=pool, fresh=fresh
            )
            for _ in range(4)
        ]
        with pytest.raises(Exception) as denied:
            await open_stream(
                access, Broker(Subscription(RESYNC)), admissions=pool, fresh=fresh
            )
        assert denied.value.status == 503
        assert pool.total == 4
        for stream in streams:
            await stream.aclose()  # No first __anext__; must still release.
        assert pool.total == 0

    async_to_sync(run)()


def test_subscribe_error_and_auth_recheck_failure_release_preheader(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """A subscribe error or failed re-check releases the reservation before headers.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    from todo.realtime_auth import RealtimeDenied
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run() -> None:
        pool = Admissions()
        sub = Subscription(RESYNC)
        broker = Broker(sub)
        broker.failure = RuntimeError("do-not-log-payload")
        with pytest.raises(RealtimeDenied) as error:
            await open_stream(access, broker, admissions=pool)
        assert error.value.status == 503 and pool.total == 0
        broker.failure = None

        async def fresh(key: str | None) -> None:
            return None

        with pytest.raises(RealtimeDenied) as denied:
            await open_stream(access, broker, admissions=pool, fresh=fresh)
        assert denied.value.status == 401
        assert pool.total == 0 and sub.closed == 1

    async_to_sync(run)()


@pytest.mark.parametrize(
    "bad",
    [
        {"event": "invalidate", "data": {"version": 1, "resources": ["unknown"]}},
        {"event": "invalidate", "data": {"version": 1, "resources": ["ui", "tasks"]}},
        {
            "event": "invalidate",
            "data": {"version": 1, "resources": ["tasks", "tasks"]},
        },
        {"event": "resync", "data": {"version": 1, "owner": "secret"}},
    ],
)
def test_broker_input_is_revalidated_against_app_wire_allowlist(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    bad: dict[str, object] | None,
) -> None:
    """Broker input is validated again against the application wire allowlist.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        bad: Malformed or disallowed event the broker delivers.
    """
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run() -> None:
        async def fresh(key: str | None) -> Identity | None:
            return access.identity

        sub = Subscription(RESYNC, bad)
        pool = Admissions()
        stream = await open_stream(access, Broker(sub), admissions=pool, fresh=fresh)
        assert await anext(stream) == RESYNC
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        assert sub.closed == 1 and pool.total == 0

    async_to_sync(run)()


def test_close_failure_still_releases_capability(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failure while closing still releases the stream capability.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        caplog: Captures the log records emitted by this test.
    """
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run() -> None:
        async def fresh(key: str | None) -> Identity | None:
            return access.identity

        sub = Subscription(RESYNC)

        async def bad_close() -> Never:
            raise RuntimeError("SECRET")

        sub.aclose = bad_close
        pool = Admissions()
        stream = await open_stream(access, Broker(sub), admissions=pool, fresh=fresh)
        await stream.aclose()
        assert pool.total == 0

    async_to_sync(run)()
    assert "SECRET" not in caplog.text


def test_default_limits_are_exact_and_total_capacity_enforced() -> None:
    """The default limits are exact and the total capacity is enforced."""
    from todo.realtime_auth import Identity, RealtimeDenied
    from todo.realtime_stream import Admissions

    pool = Admissions()
    owners = [Identity("default", str(i), "hvs1." + "x" * 43) for i in range(256)]
    leases = [pool.acquire(owner) for owner in owners]
    with pytest.raises(RealtimeDenied) as denied:
        pool.acquire(owners[0])
    assert denied.value.status == 503 and pool.total == 256
    for lease in leases:
        lease.release()
        lease.release()
    assert pool.total == 0


def test_closed_stream_does_not_emit_late_auth_failure(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """A closed stream does not emit a late authentication failure.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run() -> None:
        calls = 0
        waiting = asyncio.Event()
        release = asyncio.Event()

        async def fresh(key: str | None) -> Identity | None:
            nonlocal calls
            calls += 1
            if calls == 1:
                return access.identity
            waiting.set()
            await release.wait()
            return None

        sub = Subscription(RESYNC)
        pool = Admissions()
        stream = await open_stream(access, Broker(sub), admissions=pool, fresh=fresh)
        pending = asyncio.create_task(anext(stream))
        await waiting.wait()
        await stream.aclose()
        release.set()
        with pytest.raises(StopAsyncIteration):
            await pending
        assert pool.total == 0 and sub.closed == 1

    async_to_sync(run)()


def test_real_database_revocation_between_stream_frames(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """A real database revocation between frames ends the stream.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    from asgiref.sync import sync_to_async

    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run() -> None:
        pool = Admissions()
        sub = Subscription(RESYNC, HINT)
        stream = await open_stream(access, Broker(sub), admissions=pool)
        assert await anext(stream) == RESYNC
        await sync_to_async(
            Session.objects.filter(session_key=access.session_key).delete,
            thread_sensitive=True,
        )()
        assert await anext(stream) == {"event": "auth-required", "data": {"version": 1}}
        assert pool.total == 0 and sub.closed == 1

    async_to_sync(run)()


@pytest.mark.parametrize("script_name", ["", "/app"])
@pytest.mark.parametrize("status", [200, 401, 403])
def test_exact_stream_path_bypasses_presentation_only(
    user: AbstractUser,
    status: int,
    script_name: str,
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """Only the exact stream path bypasses the presentation middleware.

    Args:
        user: Signed-in user who owns the data in this test.
        status: Status code of the downstream response.
        script_name: Script prefix the site is mounted under.
        django_assert_num_queries: Asserts the exact number of queries the block runs.
    """
    from django.http import HttpResponse

    from todo.middleware import ProfileLanguageMiddleware, ThemeHeaderMiddleware
    from todo.models import Profile

    Profile.objects.create(user=user, theme="dark", language="es")
    user._state.fields_cache.pop("profile", None)
    request = RequestFactory().get("/realtime/events/", SCRIPT_NAME=script_name)
    request.user = user

    def downstream(incoming: HttpRequest) -> HttpResponse:
        assert incoming is request
        assert incoming.user is user
        return HttpResponse(status=status)

    chain = ProfileLanguageMiddleware(ThemeHeaderMiddleware(downstream))
    with django_assert_num_queries(0):
        response = chain(request)
    assert response.status_code == status
    assert "X-HyperTodo-Theme" not in response


@pytest.mark.parametrize(
    "path", ["/realtime/events/extra", "/hv/", "/app/realtime/events/"]
)
def test_other_routes_keep_presentation_middleware(
    user: AbstractUser, path: str
) -> None:
    """Other routes keep the presentation middleware.

    Args:
        user: Signed-in user who owns the data in this test.
        path: Path of the route under test.
    """
    from django.http import HttpResponse

    from todo.middleware import ProfileLanguageMiddleware, ThemeHeaderMiddleware
    from todo.models import Profile

    Profile.objects.create(user=user, theme="dark", language="es")
    request = RequestFactory().get(path)
    request.user = user
    response = ProfileLanguageMiddleware(
        ThemeHeaderMiddleware(lambda request: HttpResponse())
    )(request)
    assert response["X-HyperTodo-Theme"] == "dark"
    assert request.LANGUAGE_CODE == "es"


@pytest.mark.parametrize("script_name", ["", "/app", "/a/b"])
def test_the_stream_route_is_recognised_wherever_the_site_is_mounted(
    script_name: str,
) -> None:
    """The stream route is recognised wherever the site is mounted.

    Args:
        script_name: Script prefix the site is mounted under.
    """
    from todo.realtime_middleware import is_stream_request

    request = RequestFactory().get("/realtime/events/", SCRIPT_NAME=script_name)
    assert request.path == script_name + "/realtime/events/"
    assert is_stream_request(request)
    # The URL a handler would reverse carries the same prefix it set for the request.
    with override_script_prefix(script_name + "/"):
        assert is_stream_request(request)


@pytest.mark.parametrize(
    "path",
    [
        "/realtime/events",
        "/realtime/events/extra",
        "/hv/realtime/events/",
        "/app/realtime/events/",
        "/",
    ],
)
def test_no_other_route_is_taken_for_the_stream(path: str) -> None:
    """No other route is mistaken for the stream.

    Args:
        path: Path of the route under test.
    """
    from todo.realtime_middleware import is_stream_request

    assert not is_stream_request(RequestFactory().get(path))


@pytest.mark.parametrize("script_name", ["", "/app"])
@pytest.mark.parametrize("enabled,status", [(True, 405), (False, 404)])
def test_the_method_guard_finds_the_stream_whatever_the_script_name(
    settings: Settings, script_name: str, enabled: bool, status: int
) -> None:
    """The method guard finds the stream whatever the script name is.

    Args:
        settings: Django settings overridden by this test.
        script_name: Script prefix the site is mounted under.
        enabled: Whether realtime is enabled in the settings.
        status: Status code the request is expected to receive.
    """
    from django.http import HttpResponse

    from todo.realtime_middleware import RealtimeMethodMiddleware

    settings.HYPERVIEW = {
        **settings.HYPERVIEW,
        "REALTIME": CONFIG.copy() if enabled else None,
    }
    request = RequestFactory().post("/realtime/events/", SCRIPT_NAME=script_name)
    seen = []

    def next_handler(incoming: HttpRequest) -> HttpResponse:
        seen.append(incoming)
        return HttpResponse(status=418)

    response = RealtimeMethodMiddleware(next_handler)(request)

    assert response.status_code == status and seen == []


def test_lifetime_expiry_while_fresh_auth_waits_never_emits_frame(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """A lifetime expiry while the fresh authentication waits never emits a frame.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run() -> None:
        calls = 0
        waiting = asyncio.Event()
        release = asyncio.Event()

        async def fresh(key: str | None) -> Identity | None:
            nonlocal calls
            calls += 1
            if calls > 1:
                waiting.set()
                await release.wait()
            return access.identity

        sub = Subscription(RESYNC)
        pool = Admissions()
        stream = await open_stream(access, Broker(sub), admissions=pool, fresh=fresh)
        pending = asyncio.create_task(anext(stream))
        await waiting.wait()
        # Advance the owned deadline deterministically, not a CI sleep threshold.
        stream.deadline = asyncio.get_running_loop().time() - 1
        release.set()
        with pytest.raises(StopAsyncIteration):
            await pending
        assert pool.total == 0 and sub.closed == 1

    async_to_sync(run)()


def test_origin_explicit_port_zero_is_not_default_and_rejects_before_auth(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """An Origin with explicit port zero is not the default port and is rejected early.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        django_assert_num_queries: Asserts the exact number of queries the block runs.
    """
    from todo.realtime_auth import RealtimeDenied, authorize

    request = authenticated[2]
    request.META["HTTP_ORIGIN"] = "http://testserver:0"
    with django_assert_num_queries(0), pytest.raises(RealtimeDenied) as denied:
        async_to_sync(authorize)(request)
    assert denied.value.status == 403


def test_origin_explicit_default_port_is_equivalent(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """An explicit default port in the Origin is equivalent to omitting it.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    from todo.realtime_auth import authorize

    request = authenticated[2]
    request.META["HTTP_ORIGIN"] = "http://testserver:80"
    assert async_to_sync(authorize)(request).identity.binding == authenticated[3]


@pytest.fixture
def behind_a_tls_proxy(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str], settings: Settings
) -> tuple[Client, AbstractUser, WSGIRequest, str]:
    """A request the proxy received over HTTPS, which Django sees as plain http.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        settings: Django settings overridden by this test.

    Returns:
        The authenticated session, with the proxy's host and trusted origin configured.
    """
    settings.ALLOWED_HOSTS = ["api.example.com", "testserver"]
    settings.CSRF_TRUSTED_ORIGINS = ["https://api.example.com"]
    request = authenticated[2]
    request.META["HTTP_HOST"] = "api.example.com"
    assert request.scheme == "http"
    return authenticated


def admitted(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str], origin: str
) -> bool:
    """Report whether authorize() lets this Origin through.

    Args:
        authenticated: Signed-in session whose request is copied for each call.
        origin: Value of the Origin header to try.

    Returns:
        True when the Origin was admitted, False when it was refused with a 403.
    """
    from todo.realtime_auth import RealtimeDenied, authorize

    # A copy per call: request.headers is computed once, so a second Origin set on
    # the same request would never be seen.
    request = copy.copy(authenticated[2])
    request.META = {**request.META, "HTTP_ORIGIN": origin}
    try:
        async_to_sync(authorize)(request)
    except RealtimeDenied as denied:
        assert denied.status == 403
        return False
    return True


@pytest.mark.parametrize(
    "origin",
    [
        "https://api.example.com",
        "https://api.example.com:443",
        "https://API.example.com",
        # Still the request's own origin, whatever the proxy does to the scheme.
        "http://api.example.com",
    ],
)
def test_a_trusted_origin_is_admitted_behind_a_tls_terminating_proxy(
    behind_a_tls_proxy: tuple[Client, AbstractUser, WSGIRequest, str], origin: str
) -> None:
    """A trusted origin is admitted behind a TLS-terminating proxy.

    Args:
        behind_a_tls_proxy: Signed-in session whose request reached Django over plain
        http behind a TLS proxy.
        origin: Value of the Origin header.
    """
    # request.scheme is http here, so comparing the Origin with the request alone
    # refused the page's real origin and silently turned realtime off. The origin the
    # operator already trusts for CSRF is the one the browser will send.
    assert admitted(behind_a_tls_proxy, origin)


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "https://api.example.com:8443",
        "https://sub.api.example.com",
        "https://api.example.com.evil.example",
        "http://api.example.com:8080",
        "https://api.example.com/path",
        "https://user@api.example.com",
        "null",
        # Scheme and port are separate parts of the match: the trusted https origin is
        # neither http on its port nor https on the http port.
        "http://api.example.com:443",
        "https://api.example.com:80",
        # A serialized origin carries no query and no fragment.
        "https://api.example.com?x",
        "https://api.example.com#x",
        # Nor is a bare scheme, or anything that is not http(s) at all.
        "https://",
        "ftp://api.example.com",
        "wss://api.example.com",
    ],
)
def test_an_origin_nobody_trusts_is_still_refused_behind_a_proxy(
    behind_a_tls_proxy: tuple[Client, AbstractUser, WSGIRequest, str], origin: str
) -> None:
    """An origin that nobody trusts is still refused behind a proxy.

    Args:
        behind_a_tls_proxy: Signed-in session whose request reached Django over plain
        http behind a TLS proxy.
        origin: Value of the Origin header.
    """
    assert not admitted(behind_a_tls_proxy, origin)


@pytest.mark.parametrize("hostless", ["https://", "http://", "https://:443"])
def test_an_origin_without_a_hostname_is_never_admitted(
    behind_a_tls_proxy: tuple[Client, AbstractUser, WSGIRequest, str],
    settings: Settings,
    hostless: str,
) -> None:
    """An origin without a hostname is never admitted.

    Args:
        behind_a_tls_proxy: Signed-in session whose request reached Django over plain
        http behind a TLS proxy.
        settings: Django settings overridden by this test.
        hostless: Origin that has a scheme but no hostname.
    """
    # urlsplit() reads "https://" as scheme https with host None, so the entry and
    # the header both reduced to ("https", None, 443) and a hostless entry (a typo for
    # a real one) admitted a hostless Origin. Neither of them names an origin.
    settings.CSRF_TRUSTED_ORIGINS = [hostless]

    assert not admitted(behind_a_tls_proxy, hostless)


@pytest.mark.parametrize("scheme", ["ftp", "ws", "wss", "chrome-extension"])
def test_a_trusted_entry_that_is_not_http_or_https_is_ignored(
    behind_a_tls_proxy: tuple[Client, AbstractUser, WSGIRequest, str],
    settings: Settings,
    scheme: str,
) -> None:
    """A trusted entry that is not http or https is ignored.

    Args:
        behind_a_tls_proxy: Signed-in session whose request reached Django over plain
        http behind a TLS proxy.
        settings: Django settings overridden by this test.
        scheme: Scheme of the trusted origin entry that must be ignored.
    """
    origin = f"{scheme}://api.example.com"
    settings.CSRF_TRUSTED_ORIGINS = [origin]

    assert not admitted(behind_a_tls_proxy, origin)


def test_trusted_origins_are_matched_exactly_and_never_as_wildcards(
    behind_a_tls_proxy: tuple[Client, AbstractUser, WSGIRequest, str],
    settings: Settings,
) -> None:
    """Trusted origins are matched exactly and never as wildcards.

    Args:
        behind_a_tls_proxy: Signed-in session whose request reached Django over plain
        http behind a TLS proxy.
        settings: Django settings overridden by this test.
    """
    settings.CSRF_TRUSTED_ORIGINS = ["https://*.example.com", "https://[bad"]

    assert not admitted(behind_a_tls_proxy, "https://api.example.com")
    assert not admitted(behind_a_tls_proxy, "https://*.example.com")


def test_without_trusted_origins_only_the_requests_own_origin_is_admitted(
    behind_a_tls_proxy: tuple[Client, AbstractUser, WSGIRequest, str],
    settings: Settings,
) -> None:
    """Without trusted origins only the request's own origin is admitted.

    Args:
        behind_a_tls_proxy: Signed-in session whose request reached Django over plain
        http behind a TLS proxy.
        settings: Django settings overridden by this test.
    """
    settings.CSRF_TRUSTED_ORIGINS = []

    assert not admitted(behind_a_tls_proxy, "https://api.example.com")
    assert admitted(behind_a_tls_proxy, "http://api.example.com")


@pytest.mark.parametrize("options", [{}, {"using": None}])
def test_template_topic_uses_django_router_when_source_has_no_explicit_alias(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    options: dict[str, object],
) -> None:
    """The template topic uses the Django router when the source names no alias.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        settings: Django settings overridden by this test.
        monkeypatch: Patches the code under test for this test.
        options: Options of the database template source.
    """
    from django.db import router

    from todo.realtime_auth import topics_for
    from todo.realtime_notifications import ui_topic

    identity = access_for(authenticated).identity
    settings.HYPERVIEW = {
        **settings.HYPERVIEW,
        "SOURCES": [
            {
                "BACKEND": "dj_hyperview.contrib.database.sources.DatabaseSource",
                "OPTIONS": options,
            }
        ],
    }
    seen = []

    def route(model: type[Model], **hints: object) -> str:
        seen.append(model._meta.label_lower)
        return "routed-templates"

    monkeypatch.setattr(router, "db_for_read", route)
    assert topics_for(identity)[1:] == (ui_topic("routed-templates"),)
    assert seen == ["dj_hyperview_database.hyperviewtemplate"]


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        {"event": "resync", "data": []},
        {"event": "resync", "data": {"version": True}},
        {"event": "resync", "data": {"version": 2}},
    ],
)
def test_malformed_envelopes_close_without_data(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
    bad: dict[str, object] | None,
) -> None:
    """Malformed envelopes close the stream without emitting data.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        bad: Malformed or disallowed event the broker delivers.
    """
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run() -> None:
        async def fresh(key: str | None) -> Identity | None:
            return access.identity

        pool = Admissions()
        sub = Subscription(bad)
        stream = await open_stream(access, Broker(sub), admissions=pool, fresh=fresh)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        assert pool.total == 0 and sub.closed == 1

    async_to_sync(run)()


def test_expired_before_iteration_and_remote_auth_terminal_release(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """A stream that expires or loses authentication ends and releases its reservation.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run() -> None:
        async def fresh(key: str | None) -> Identity | None:
            return access.identity

        pool = Admissions()
        for expired in (True, False):
            sub = Subscription({"event": "auth-required", "data": {"version": 1}})
            stream = await open_stream(
                access, Broker(sub), admissions=pool, fresh=fresh
            )
            if expired:
                stream.deadline = asyncio.get_running_loop().time() - 1
                with pytest.raises(StopAsyncIteration):
                    await anext(stream)
            else:
                assert await anext(stream) == {
                    "event": "auth-required",
                    "data": {"version": 1},
                }
            assert pool.total == 0 and sub.closed == 1

    async_to_sync(run)()


def test_explicit_close_cancels_pending_cancel_safe_subscription_read(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """An explicit close cancels a pending subscription read that is safe to cancel.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run() -> None:
        async def fresh(key: str | None) -> Identity | None:
            return access.identity

        started = asyncio.Event()

        class WaitingSubscription(Subscription):
            async def __anext__(self) -> dict[str, object] | None:
                started.set()
                return await super().__anext__()

        sub = WaitingSubscription()
        pool = Admissions()
        stream = await open_stream(access, Broker(sub), admissions=pool, fresh=fresh)
        read = asyncio.create_task(anext(stream))
        await started.wait()
        await stream.aclose()
        with pytest.raises(asyncio.CancelledError):
            await read
        assert pool.total == 0 and sub.closed == 1

    async_to_sync(run)()


def test_changed_binding_after_subscribe_is_403_and_cleans_up(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """A binding that changes after subscribing is answered 403 and cleaned up.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    from dataclasses import replace

    from todo.realtime_auth import RealtimeDenied
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run() -> None:
        async def fresh(key: str | None) -> Identity | None:
            return replace(access.identity, binding="hvs1." + "x" * 43)

        sub = Subscription(RESYNC)
        pool = Admissions()
        with pytest.raises(RealtimeDenied) as denied:
            await open_stream(access, Broker(sub), admissions=pool, fresh=fresh)
        assert denied.value.status == 403 and sub.closed == 1 and pool.total == 0

    async_to_sync(run)()


def test_malformed_origin_port_is_rejected_without_auth(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str],
) -> None:
    """A malformed port in the Origin is rejected without authenticating.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
    """
    from todo.realtime_auth import RealtimeDenied, authorize

    authenticated[2].META["HTTP_ORIGIN"] = "http://testserver:invalid"
    with pytest.raises(RealtimeDenied) as denied:
        async_to_sync(authorize)(authenticated[2])
    assert denied.value.status == 403


@pytest.mark.parametrize("origin", ["http://@testserver", "http://:@testserver"])
def test_origin_userinfo_even_empty_is_not_a_serialized_origin(
    authenticated: tuple[Client, AbstractUser, WSGIRequest, str], origin: str
) -> None:
    """An Origin with user information, even an empty one, is not a serialized origin.

    Args:
        authenticated: Client, user, request and session binding of a signed-in session.
        origin: Value of the Origin header.
    """
    from todo.realtime_auth import RealtimeDenied, authorize

    authenticated[2].META["HTTP_ORIGIN"] = origin
    with pytest.raises(RealtimeDenied) as denied:
        async_to_sync(authorize)(authenticated[2])
    assert denied.value.status == 403
