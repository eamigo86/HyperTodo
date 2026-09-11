"""Installed-release adoption and ordinary ASGI development contracts."""

import asyncio
import importlib
import sys
import tomllib
from pathlib import Path

import pytest
from asgiref.sync import async_to_sync
from django.conf import settings as django_settings
from django.test import override_settings

from tests.test_realtime_stream import RESYNC, Broker, Subscription
from tests.test_realtime_stream import authenticated as authenticated

BACKEND = Path(__file__).resolve().parents[1]


def test_release_declares_required_extras_and_asgi_server():
    dependencies = tomllib.loads((BACKEND / "pyproject.toml").read_text())["project"][
        "dependencies"
    ]
    assert "dj-hyperview[editor,realtime]==0.1.0b1" in dependencies
    assert any(value.split("=")[0].split(">")[0] == "uvicorn" for value in dependencies)


def test_installed_release_supports_both_invalidation_wire_versions():
    import dj_hyperview.realtime as realtime

    assert realtime.INVALIDATION_VERSIONS == (1, 2)


def test_runner_uses_selected_environment_without_import_path_mutation():
    from test_support.native_app import load_runner

    before = tuple(sys.path)
    runner = load_runner()
    assert tuple(sys.path) == before
    assert Path(runner.__file__).is_relative_to(Path(sys.prefix))


async def asgi_get(application, path, *, headers=None, disconnect_on_body=False):
    queue = asyncio.Queue()
    queue.put_nowait({"type": "http.request", "body": b"", "more_body": False})
    sent = []

    async def send(message):
        sent.append(message)
        if disconnect_on_body and message["type"] == "http.response.body":
            queue.put_nowait({"type": "http.disconnect"})

    await asyncio.wait_for(
        application(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": "",
                "server": ("testserver", 80),
                "client": ("127.0.0.1", 40000),
                "headers": headers or [(b"host", b"testserver")],
            },
            queue.get,
            send,
        ),
        3,
    )
    return sent


@pytest.mark.parametrize(
    "path,content",
    [
        ("/static/admin/css/base.css", b"body"),
        ("/static/dj_hyperview/admin/hxml_editor.js", b"Hyperview"),
    ],
)
def test_debug_asgi_serves_actual_admin_assets(path, content):
    module = importlib.import_module("config.asgi")
    try:
        with override_settings(DEBUG=True, STATIC_URL="/static/"):
            messages = asyncio.run(asgi_get(importlib.reload(module).application, path))
        assert messages[0]["status"] == 200
        body = b"".join(m.get("body", b"") for m in messages)
        assert content in body
    finally:
        importlib.reload(module)


def test_production_asgi_does_not_serve_development_static():
    module = importlib.import_module("config.asgi")
    try:
        with override_settings(DEBUG=False, STATIC_URL="/static/"):
            messages = asyncio.run(
                asgi_get(
                    importlib.reload(module).application, "/static/admin/css/base.css"
                )
            )
        assert messages[0]["status"] == 404
    finally:
        importlib.reload(module)


def test_sse_development_profile_is_explicit_and_preserves_normal_configuration():
    from config import settings as normal

    before = dict(normal.HYPERVIEW)
    development = importlib.import_module("config.settings_sse")
    assert development.HYPERVIEW["SOURCES"] == [
        {"BACKEND": "dj_hyperview.sources.FileSystemSource"}
    ]
    assert development.HYPERVIEW["REALTIME"] == {
        "REDIS_URL": "redis://127.0.0.1:6379/15",
        "NAMESPACE": "hypertodo-development",
    }
    for key in ("SCHEMA_EXTENSIONS", "EXTRA_SCHEMAS", "TEMPLATE_DIRS", "ADMIN"):
        assert development.HYPERVIEW[key] == normal.HYPERVIEW[key]
    assert development.DATABASES == normal.DATABASES
    assert development.CACHES == normal.CACHES
    assert development.MIDDLEWARE == normal.MIDDLEWARE
    assert normal.HYPERVIEW == before
    assert "DatabaseSource" in normal.HYPERVIEW["SOURCES"][0]["BACKEND"]


def test_development_commands_do_not_migrate_seed_or_weaken_go_guard():
    text = (BACKEND.parent / "Makefile").read_text()
    target = text.split("\nbackend-run-sse:", 1)[1].split("\n\n", 1)[0]
    assert "config.settings_sse" in target
    assert "uvicorn config.asgi:application" in target
    assert "127.0.0.1" in target and "0.0.0.0" not in target
    assert all(
        command not in target for command in ("runserver", "migrate", "seed_demo")
    )
    go = text.split("\nmobile-start-go:", 1)[1].split("\n\n", 1)[0]
    assert "EXPO_PUBLIC_ALLOW_LOCAL_API=1" in go
    assert "start:go" in go


@pytest.mark.django_db(transaction=True)
def test_debug_static_wrapper_preserves_real_sse_auth_and_disconnect(
    authenticated, monkeypatch
):
    from todo import realtime_views
    from todo.realtime_stream import admissions

    module = importlib.import_module("config.asgi")
    request = authenticated[2]
    cookie_name = django_settings.SESSION_COOKIE_NAME
    headers = [
        (b"host", b"testserver"),
        (b"cookie", f"{cookie_name}={request.COOKIES[cookie_name]}".encode()),
    ]
    headers.extend(
        (key.lower().encode(), value.encode())
        for key, value in request.headers.items()
        if key.lower().startswith("x-hypertodo") or key.lower() == "origin"
    )

    async def run():
        subscription = Subscription(RESYNC)
        monkeypatch.setattr(
            realtime_views, "_broker", lambda config: Broker(subscription)
        )
        messages = await asgi_get(
            module.application,
            "/realtime/events/",
            headers=headers,
            disconnect_on_body=True,
        )
        assert messages[0]["status"] == 200
        response_headers = {key.lower(): value for key, value in messages[0]["headers"]}
        assert (
            response_headers[b"x-hypertodo-session-binding"].decode()
            == authenticated[3]
        )
        assert (
            b"".join(m.get("body", b"") for m in messages)
            == b'event: resync\ndata: {"version":1}\n\n'
        )
        assert subscription.closed == 1 and admissions.total == 0

    try:
        with override_settings(DEBUG=True, STATIC_URL="/static/"):
            importlib.reload(module)
            async_to_sync(run)()
    finally:
        importlib.reload(module)
