"""Scoped real Redis/ORM/Admin/SSE acceptance, never a shared-key flush."""

import asyncio
import json
import os
from uuid import uuid4

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from dj_hyperview.realtime import RedisBroker
from django.core.asgi import get_asgi_application
from django.db import transaction
from django.urls import reverse

from tests.test_session_contract import _confirm
from todo.models import Task
from todo.realtime_changes import capture_entities, supports_changes
from todo.realtime_notifications import private_topic

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.redis]
RESYNC = {"event": "resync", "data": {"version": 1}}
INVALIDATE = {"event": "invalidate", "data": {"version": 1, "resources": ["tasks"]}}


@pytest.fixture
def realtime_redis(settings):
    if os.environ.get("HYPERTODO_REDIS_INTEGRATION") != "1":
        pytest.skip("Real Redis acceptance is explicitly opt-in")
    url = os.environ.get("HYPERTODO_REDIS_TEST_URL")
    assert url == "redis://127.0.0.1:6379/14", (
        "Only the authorized loopback test Redis is permitted"
    )
    namespace = "hypertodo-test-" + uuid4().hex
    settings.HYPERVIEW = {
        **settings.HYPERVIEW,
        "REALTIME": {"REDIS_URL": url, "NAMESPACE": namespace},
    }
    return url, namespace


def admin_rename(client, task, title):
    return client.post(
        reverse("admin:todo_task_change", args=[task.pk]),
        {
            "user": str(task.user_id),
            "title": title,
            "notes": "",
            "category": "",
            "due_at_0": "",
            "due_at_1": "",
            "completed_at_0": "",
            "completed_at_1": "",
            "_save": "Save",
        },
    )


def test_admin_commit_targets_a_not_b_or_other_namespace(
    user, other_user, admin_client, client, settings, realtime_redis
):
    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": None}
    task = Task.objects.create(user=user, title="Before")
    client.force_login(user)
    url, namespace = realtime_redis
    settings.HYPERVIEW = {
        **settings.HYPERVIEW,
        "REALTIME": {"REDIS_URL": url, "NAMESPACE": namespace},
    }

    async def run():
        broker = RedisBroker(url, namespace)
        foreign = RedisBroker(url, "hypertodo-other-" + uuid4().hex)
        owned = []
        try:
            a = await broker.subscribe([private_topic("default", user.pk)])
            owned.append(a)
            b = await broker.subscribe([private_topic("default", other_user.pk)])
            owned.append(b)
            other = await foreign.subscribe([private_topic("default", user.pk)])
            owned.append(other)
            for sub in owned:
                assert await asyncio.wait_for(anext(sub), 2) == RESYNC

            def rolled_back_change():
                with pytest.raises(RuntimeError):
                    with transaction.atomic():
                        task.title = "Rolled back"
                        task.save(update_fields=["title"])
                        raise RuntimeError
                task.refresh_from_db()
                assert task.title == "Before"

            await sync_to_async(rolled_back_change, thread_sensitive=True)()
            # Protocol barrier proves no rollback hint preceded this marker.
            await sync_to_async(broker.publish_after_commit, thread_sensitive=True)(
                RESYNC, [private_topic("default", user.pk)], using="default"
            )
            assert await asyncio.wait_for(anext(a), 2) == RESYNC
            response = await sync_to_async(admin_rename, thread_sensitive=True)(
                admin_client, task, "SSE committed title"
            )
            assert response.status_code == 302
            expected = INVALIDATE
            if supports_changes():
                expected = {
                    "event": "invalidate",
                    "data": {
                        "version": 2,
                        "resources": ["tasks"],
                        "mutation_id": None,
                        "entities": capture_entities(
                            "default", [("tasks", task.pk)]
                        ).payload,
                    },
                }
            assert await asyncio.wait_for(anext(a), 2) == expected
            # Same publisher order, not a sleep-based absence assertion.
            await sync_to_async(broker.publish_after_commit, thread_sensitive=True)(
                RESYNC, [private_topic("default", other_user.pk)], using="default"
            )
            await sync_to_async(foreign.publish_after_commit, thread_sensitive=True)(
                RESYNC, [private_topic("default", user.pk)], using="default"
            )
            assert await asyncio.wait_for(anext(b), 2) == RESYNC
            assert await asyncio.wait_for(anext(other), 2) == RESYNC
            page = await sync_to_async(client.get, thread_sensitive=True)("/hv/tasks/")
            assert page.status_code == 200
            assert b"SSE committed title" in page.content
            assert b"<screen" in page.content
        finally:
            for sub in owned:
                await sub.aclose()

    async_to_sync(run)()


@pytest.mark.parametrize("changes_v2", [False, True])
def test_real_asgi_stream_receives_admin_change_and_releases(
    user, admin_client, client, settings, realtime_redis, changes_v2
):
    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": None}
    task = Task.objects.create(user=user, title="Before")
    client.force_login(user)
    binding, _ = _confirm(client, True)
    url, namespace = realtime_redis
    settings.HYPERVIEW = {
        **settings.HYPERVIEW,
        "REALTIME": {"REDIS_URL": url, "NAMESPACE": namespace},
    }
    session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    cookie = f"{settings.SESSION_COOKIE_NAME}={session_cookie}"

    async def run():
        from dj_hyperview.realtime import realtime_asgi

        from todo.realtime_stream import admissions

        queue = asyncio.Queue()
        queue.put_nowait({"type": "http.request", "body": b"", "more_body": False})
        sent = []
        frames = []

        async def send(event):
            sent.append(event)
            body = event.get("body", b"")
            if body:
                frames.append(body)
                if len(frames) == 1:
                    assert body == b'event: resync\ndata: {"version":1}\n\n'
                    response = await sync_to_async(admin_rename, thread_sensitive=True)(
                        admin_client, task, "SSE live title"
                    )
                    assert response.status_code == 302
                else:
                    queue.put_nowait({"type": "http.disconnect"})

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/realtime/events/",
            "raw_path": b"/realtime/events/",
            "query_string": b"",
            "root_path": "",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 41000),
            "headers": [
                (b"host", b"testserver"),
                (b"cookie", cookie.encode()),
                (b"x-hypertodo-client-contract", b"realtime-v1"),
                (b"x-hypertodo-expected-session", binding.encode()),
            ],
        }
        if changes_v2:
            scope["headers"].append((b"x-hypertodo-realtime-features", b"changes-v2"))
        await asyncio.wait_for(
            realtime_asgi(get_asgi_application())(scope, queue.get, send), 6
        )
        assert sent[0]["status"] == 200
        if changes_v2 and supports_changes():
            assert (
                len(frames) == 2
                and frames[0] == b'event: resync\ndata: {"version":1}\n\n'
            )
            assert json.loads(frames[1].split(b"data: ", 1)[1]) == {
                "version": 2,
                "resources": ["tasks"],
                "mutation_id": None,
                "entities": capture_entities("default", [("tasks", task.pk)]).payload,
            }
            headers = {key.lower(): value for key, value in sent[0]["headers"]}
            assert len(headers[b"x-hypertodo-mutation-seed"]) == 32
        else:
            assert frames == [
                b'event: resync\ndata: {"version":1}\n\n',
                b'event: invalidate\ndata: {"version":1,"resources":["tasks"]}\n\n',
            ]
        assert admissions.total == 0

    async_to_sync(run)()


def test_template_admin_commit_reaches_live_ui_stream_and_fresh_http(
    user, admin_client, client, settings, realtime_redis
):
    """Real Redis/ASGI acceptance; no broker, signal or commit callback mocks."""
    from dj_hyperview.contrib.database.models import HyperviewTemplate
    from dj_hyperview.realtime import realtime_asgi

    from todo.realtime_notifications import ui_topic
    from todo.realtime_stream import admissions

    # Never let suite cache.clear() reach Redis; only the broker uses db14.
    assert settings.CACHES["default"]["BACKEND"].endswith("LocMemCache")
    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": None}
    source = (
        (settings.BASE_DIR / "hyperview/screens/about.xml").read_text().rstrip("\n")
    )
    before = source.replace("</body>", "<text>Before template edit</text></body>")
    after = source.replace("</body>", "<text>Committed template edit</text></body>")
    template = HyperviewTemplate.objects.create(
        name="screens/about.xml", content=before
    )
    client.force_login(user)
    binding, _ = _confirm(client, True)
    url, namespace = realtime_redis
    settings.HYPERVIEW = {
        **settings.HYPERVIEW,
        "REALTIME": {"REDIS_URL": url, "NAMESPACE": namespace},
        "CACHE": {
            "ALIAS": "default",
            "NAMESPACE": namespace,
            "TTL": 30,
            "NEGATIVE_TTL": 2,
            "FAILURE_MODE": "raise",
        },
    }
    assert b"Before template edit" in client.get("/hv/about/").content
    admin_url = reverse(
        "admin:dj_hyperview_database_hyperviewtemplate_change", args=[template.pk]
    )

    def edit(rollback):
        with transaction.atomic():
            response = admin_client.post(
                admin_url,
                {
                    "name": template.name,
                    "content": after,
                    "active": "on",
                    "expected_revision": "1",
                    "_save": "Save",
                },
            )
            assert response.status_code == 302
            if rollback:
                transaction.set_rollback(True)
        template.refresh_from_db()
        assert template.content == (before if rollback else after)
        assert template.revision == (1 if rollback else 2)

    async def run():
        queue = asyncio.Queue()
        queue.put_nowait({"type": "http.request", "body": b"", "more_body": False})
        sent, frames = [], []
        broker = RedisBroker(url, namespace)

        async def send(event):
            sent.append(event)
            if body := event.get("body", b""):
                frames.append(body)
                if len(frames) == 1:
                    assert body == b'event: resync\ndata: {"version":1}\n\n'
                    await sync_to_async(edit, thread_sensitive=True)(True)
                    # FIFO barrier: any premature rollback hint would precede it.
                    await sync_to_async(
                        broker.publish_after_commit, thread_sensitive=True
                    )(RESYNC, [ui_topic("default")], using="default")
                elif len(frames) == 2:
                    assert body == b'event: resync\ndata: {"version":1}\n\n'
                    await sync_to_async(edit, thread_sensitive=True)(False)
                else:
                    assert body == (
                        b'event: invalidate\ndata: {"version":1,"resources":["ui"]}\n\n'
                    )
                    queue.put_nowait({"type": "http.disconnect"})

        cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/realtime/events/",
            "raw_path": b"/realtime/events/",
            "query_string": b"",
            "root_path": "",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 41000),
            "headers": [
                (b"host", b"testserver"),
                (b"cookie", f"{settings.SESSION_COOKIE_NAME}={cookie}".encode()),
                (b"x-hypertodo-client-contract", b"realtime-v1"),
                (b"x-hypertodo-expected-session", binding.encode()),
            ],
        }
        await asyncio.wait_for(
            realtime_asgi(get_asgi_application())(scope, queue.get, send), 8
        )
        assert sent[0]["status"] == 200 and len(frames) == 3
        assert admissions.total == 0
        page = await sync_to_async(client.get, thread_sensitive=True)("/hv/about/")
        assert page.status_code == 200
        assert b"Committed template edit" in page.content
        assert b"Before template edit" not in page.content
        assert b"about-screen" in page.content

    async_to_sync(run)()
