"""Fresh Django authentication and bounded app-owned streaming resources."""

import asyncio
from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest
from asgiref.sync import async_to_sync
from django.contrib.sessions.models import Session
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory
from django.utils import timezone

from tests.test_session_contract import _confirm
from todo.session_contract import (
    CLIENT_CONTRACT_HEADER,
    EXPECTED_SESSION_HEADER,
)

pytestmark = pytest.mark.django_db(transaction=True)
CONFIG = {"REDIS_URL": "redis://127.0.0.1:6379/14", "NAMESPACE": "stream-tests"}
RESYNC = {"event": "resync", "data": {"version": 1}}
HINT = {"event": "invalidate", "data": {"version": 1, "resources": ["tasks"]}}


@pytest.fixture
def authenticated(client, user, settings):
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


def access_for(authenticated):
    from todo.realtime_auth import authorize

    return async_to_sync(authorize)(authenticated[2])


def test_fresh_auth_uses_database_session_not_cached_request_user(authenticated):
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
def test_real_django_session_revocation(authenticated, revocation):
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


@pytest.mark.parametrize(
    "engine",
    [
        "django.contrib.sessions.backends.signed_cookies",
        "django.contrib.sessions.backends.cache",
        "django.contrib.sessions.backends.cached_db",
    ],
)
def test_enabled_realtime_requires_actual_database_session_engine(settings, engine):
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
def test_route_specific_denials_before_broker(authenticated, settings, case, status):
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


def test_same_origin_and_native_no_origin_are_both_supported(authenticated):
    from todo.realtime_auth import authorize

    _, _, request, binding = authenticated
    assert async_to_sync(authorize)(request).identity.binding == binding
    request.META["HTTP_ORIGIN"] = "http://testserver"
    assert async_to_sync(authorize)(request).identity.binding == binding


def test_topics_are_server_selected_from_principal_and_template_sources(
    authenticated, settings
):
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
    def __init__(self, *items):
        self.items = asyncio.Queue()
        for item in items:
            self.items.put_nowait(item)
        self.closed = 0
        self.failure = None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.failure:
            raise self.failure
        return await self.items.get()

    async def aclose(self):
        self.closed += 1


class Broker:
    def __init__(self, subscription):
        self.subscription = subscription
        self.topics = None
        self.failure = None

    async def subscribe(self, topics):
        self.topics = topics
        if self.failure:
            raise self.failure
        return self.subscription


def test_stream_rechecks_before_initial_resync_and_every_frame(authenticated):
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run():
        reads = []

        async def fresh(key):
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


def test_auth_loss_between_frames_emits_only_auth_required_then_closes(authenticated):
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run():
        current = access.identity

        async def fresh(key):
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


def test_heartbeat_requires_fresh_auth_and_lifetime_closes(authenticated):
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run():
        reads = 0

        async def fresh(key):
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


def test_caps_are_per_principal_across_bindings_and_release_without_iteration(
    authenticated,
):
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run():
        async def fresh(key):
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


def test_subscribe_error_and_auth_recheck_failure_release_preheader(authenticated):
    from todo.realtime_auth import RealtimeDenied
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run():
        pool = Admissions()
        sub = Subscription(RESYNC)
        broker = Broker(sub)
        broker.failure = RuntimeError("do-not-log-payload")
        with pytest.raises(RealtimeDenied) as error:
            await open_stream(access, broker, admissions=pool)
        assert error.value.status == 503 and pool.total == 0
        broker.failure = None

        async def fresh(key):
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
def test_broker_input_is_revalidated_against_app_wire_allowlist(authenticated, bad):
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run():
        async def fresh(key):
            return access.identity

        sub = Subscription(RESYNC, bad)
        pool = Admissions()
        stream = await open_stream(access, Broker(sub), admissions=pool, fresh=fresh)
        assert await anext(stream) == RESYNC
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        assert sub.closed == 1 and pool.total == 0

    async_to_sync(run)()


def test_close_failure_still_releases_capability(authenticated, caplog):
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run():
        async def fresh(key):
            return access.identity

        sub = Subscription(RESYNC)

        async def bad_close():
            raise RuntimeError("SECRET")

        sub.aclose = bad_close
        pool = Admissions()
        stream = await open_stream(access, Broker(sub), admissions=pool, fresh=fresh)
        await stream.aclose()
        assert pool.total == 0

    async_to_sync(run)()
    assert "SECRET" not in caplog.text


def test_default_limits_are_exact_and_total_capacity_enforced():
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


def test_closed_stream_does_not_emit_late_auth_failure(authenticated):
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run():
        calls = 0
        waiting = asyncio.Event()
        release = asyncio.Event()

        async def fresh(key):
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


def test_real_database_revocation_between_stream_frames(authenticated):
    from asgiref.sync import sync_to_async

    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run():
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


@pytest.mark.parametrize("status", [200, 401, 403])
def test_exact_stream_path_bypasses_presentation_only(
    user, status, django_assert_num_queries
):
    from django.http import HttpResponse

    from todo.middleware import ProfileLanguageMiddleware, ThemeHeaderMiddleware
    from todo.models import Profile

    Profile.objects.create(user=user, theme="dark", language="es")
    user._state.fields_cache.pop("profile", None)
    request = RequestFactory().get("/realtime/events/")
    request.user = user

    def downstream(incoming):
        assert incoming is request
        assert incoming.user is user
        return HttpResponse(status=status)

    chain = ProfileLanguageMiddleware(ThemeHeaderMiddleware(downstream))
    with django_assert_num_queries(0):
        response = chain(request)
    assert response.status_code == status
    assert "X-HyperTodo-Theme" not in response


@pytest.mark.parametrize("path", ["/realtime/events/extra", "/hv/"])
def test_other_routes_keep_presentation_middleware(user, path):
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


def test_lifetime_expiry_while_fresh_auth_waits_never_emits_frame(authenticated):
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run():
        calls = 0
        waiting = asyncio.Event()
        release = asyncio.Event()

        async def fresh(key):
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
    authenticated, django_assert_num_queries
):
    from todo.realtime_auth import RealtimeDenied, authorize

    request = authenticated[2]
    request.META["HTTP_ORIGIN"] = "http://testserver:0"
    with django_assert_num_queries(0), pytest.raises(RealtimeDenied) as denied:
        async_to_sync(authorize)(request)
    assert denied.value.status == 403


def test_origin_explicit_default_port_is_equivalent(authenticated):
    from todo.realtime_auth import authorize

    request = authenticated[2]
    request.META["HTTP_ORIGIN"] = "http://testserver:80"
    assert async_to_sync(authorize)(request).identity.binding == authenticated[3]


@pytest.mark.parametrize("options", [{}, {"using": None}])
def test_template_topic_uses_django_router_when_source_has_no_explicit_alias(
    authenticated, settings, monkeypatch, options
):
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

    def route(model, **hints):
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
def test_malformed_envelopes_close_without_data(authenticated, bad):
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run():
        async def fresh(key):
            return access.identity

        pool = Admissions()
        sub = Subscription(bad)
        stream = await open_stream(access, Broker(sub), admissions=pool, fresh=fresh)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        assert pool.total == 0 and sub.closed == 1

    async_to_sync(run)()


def test_expired_before_iteration_and_remote_auth_terminal_release(authenticated):
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run():
        async def fresh(key):
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


def test_explicit_close_cancels_pending_cancel_safe_subscription_read(authenticated):
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run():
        async def fresh(key):
            return access.identity

        started = asyncio.Event()

        class WaitingSubscription(Subscription):
            async def __anext__(self):
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


def test_changed_binding_after_subscribe_is_403_and_cleans_up(authenticated):
    from dataclasses import replace

    from todo.realtime_auth import RealtimeDenied
    from todo.realtime_stream import Admissions, open_stream

    access = access_for(authenticated)

    async def run():
        async def fresh(key):
            return replace(access.identity, binding="hvs1." + "x" * 43)

        sub = Subscription(RESYNC)
        pool = Admissions()
        with pytest.raises(RealtimeDenied) as denied:
            await open_stream(access, Broker(sub), admissions=pool, fresh=fresh)
        assert denied.value.status == 403 and sub.closed == 1 and pool.total == 0

    async_to_sync(run)()


def test_malformed_origin_port_is_rejected_without_auth(authenticated):
    from todo.realtime_auth import RealtimeDenied, authorize

    authenticated[2].META["HTTP_ORIGIN"] = "http://testserver:invalid"
    with pytest.raises(RealtimeDenied) as denied:
        async_to_sync(authorize)(authenticated[2])
    assert denied.value.status == 403


@pytest.mark.parametrize("origin", ["http://@testserver", "http://:@testserver"])
def test_origin_userinfo_even_empty_is_not_a_serialized_origin(authenticated, origin):
    from todo.realtime_auth import RealtimeDenied, authorize

    authenticated[2].META["HTTP_ORIGIN"] = origin
    with pytest.raises(RealtimeDenied) as denied:
        async_to_sync(authorize)(authenticated[2])
    assert denied.value.status == 403
