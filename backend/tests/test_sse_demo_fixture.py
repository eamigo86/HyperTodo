"""Disposable normal-App fixture controls; no native or LAN acceptance claim."""

import asyncio
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from test_support.native_app_fixture import create_fixture, settings_overrides
from tests.test_native_app_fixture import subprocess_environment


def test_ordinary_fixture_forces_realtime_disabled(tmp_path):
    fixture = create_fixture(tmp_path)
    assert settings_overrides(fixture)["HYPERVIEW"]["REALTIME"] is None


def test_settings_module_rejects_arbitrary_import_before_resources(tmp_path):
    from test_support.native_app import initialize

    fixture = create_fixture(tmp_path)
    with pytest.raises(ValueError, match="settings module"):
        initialize(fixture, settings_module="config.settings")
    assert not fixture.database.exists()


def test_demo_checks_real_new_db_without_redis_or_credentials_output(tmp_path):
    report = tmp_path / "demo-check.json"
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "from unittest.mock import patch; "
            "from test_support.sse_demo import main; "
            "guard=patch('socket.socket.connect', side_effect=AssertionError); "
            "connection=guard.start(); main(); "
            "assert connection.call_count == 0; guard.stop()",
            "--check-only",
            "--parent",
            str(tmp_path),
            "--report",
            str(report),
        ],
        env=subprocess_environment(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(report.read_text())
    assert data["owners"] == 2 and data["admins"] == 1 and data["tasks"] == 4
    assert data["namespace"] == "hypertodo-demo-" + data["run"]
    assert data["redis_url"] == "redis://127.0.0.1:6379/14"
    assert data["settings_module"] == "test_support.sse_demo_settings"
    assert data["credential_mode"] == "0600" and data["database_mode"] == "0600"
    assert data["cleaned"] is True and not Path(data["root"]).exists()
    assert data["fixture_checks_passed"] is True
    assert data["native_accepted"] is False
    assert not any(
        secret in result.stdout + result.stderr + report.read_text()
        for secret in ('"password"', '"secret"', '"username"', "hvs1.")
    )


@pytest.mark.parametrize("seconds", ["0", "601", "nan", "inf"])
def test_demo_invalid_lifetime_never_allocates(tmp_path, seconds):
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "test_support.sse_demo",
            "--seconds",
            seconds,
            "--parent",
            str(tmp_path),
        ],
        env=subprocess_environment(),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert "seconds" in result.stderr
    assert not list(tmp_path.glob("native-app-*"))


@pytest.mark.parametrize(
    "case",
    [
        "sse",
        "ordinary",
        "prefix",
        "query",
        "post",
        "unauthorized",
        "non_sse",
        "default",
    ],
)
def test_only_successful_exact_sse_get_changes_ordinary_deadline(
    tmp_path, monkeypatch, case
):
    """Control only the fixture deadline, not Django authorization or an SDK."""
    from test_support import native_app_boundary as boundary

    fixture = create_fixture(tmp_path)
    clocks = []

    class Deadline:
        def __init__(self, duration):
            self.duration = duration
            clocks.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def reschedule(self, when):
            self.duration = round(when - asyncio.get_running_loop().time())

    monkeypatch.setattr(boundary.asyncio, "timeout", Deadline)
    path = "/realtime/events/" if case != "ordinary" else "/hv/"
    if case == "prefix":
        path += "extra"
    status = 401 if case == "unauthorized" else 200
    content_type = b"application/json" if case == "non_sse" else b"text/event-stream"

    async def app(scope, receive, send):
        await receive()
        assert clocks[-1].duration == 15  # Before headers is never extended.
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", content_type)],
            }
        )
        assert clocks[-1].duration == (70 if case == "sse" else 15)
        await send({"type": "http.response.body", "body": b""})

    async def run():
        queue = asyncio.Queue()
        queue.put_nowait({"type": "http.request", "body": b""})
        sent = []

        async def send(event):
            sent.append(event)

        kwargs = {} if case == "default" else {"sse_response_timeout": 70}
        await boundary.NativeAppBoundary(app, fixture, **kwargs)(
            {
                "type": "http",
                "method": "POST" if case == "post" else "GET",
                "path": path,
                "query_string": b"x=1" if case == "query" else b"",
                "server": ("127.0.0.1", 8788),
                "headers": [(b"host", fixture.host.encode())],
            },
            queue.get,
            send,
        )
        assert sent[0]["status"] == status

    asyncio.run(run())


def test_demo_factory_and_launcher_defaults_are_closed(tmp_path):
    demo = importlib.import_module("test_support.sse_demo")
    fixture = create_fixture(tmp_path)
    assert demo.public_details(fixture, 8788) == {
        "run": fixture.run_id,
        "apiOrigin": f"http://{fixture.host}:8788",
    }
    assert demo.SETTINGS_MODULE == "test_support.sse_demo_settings"


def test_demo_cleanup_runs_even_if_serving_fails(tmp_path, monkeypatch, settings):
    demo = importlib.import_module("test_support.sse_demo")
    monkeypatch.setattr(demo, "verify_source", lambda: {})
    monkeypatch.setattr(demo, "load_runner", lambda: None)

    def initialized(fixture, **kwargs):
        fixture.database.touch(mode=0o600)
        (fixture.root / "credentials.json").touch(mode=0o600)
        settings.HYPERVIEW = {
            **settings.HYPERVIEW,
            "REALTIME": {
                "REDIS_URL": "redis://127.0.0.1:6379/14",
                "NAMESPACE": "hypertodo-demo-" + fixture.run_id,
            },
        }
        return {}

    monkeypatch.setattr(demo, "initialize", initialized)
    monkeypatch.setattr(demo, "check_fixture", lambda *a, **k: {})
    monkeypatch.setattr(demo, "build_application", lambda *a, **k: object())

    async def fail(*args, **kwargs):
        raise RuntimeError("controlled serving failure")

    monkeypatch.setattr(demo, "serve_fixture", fail)
    report = tmp_path / "failed.json"
    with pytest.raises(RuntimeError, match="controlled"):
        demo.main(["--parent", str(tmp_path), "--report", str(report)])
    assert not list(tmp_path.glob("native-app-*"))
    data = json.loads(report.read_text())
    assert data["cleaned"] is True and data["fixture_checks_passed"] is False


def test_real_demo_factory_requires_matching_private_settings(tmp_path):
    program = """
from pathlib import Path
from django.conf import settings
from django.db import connections
from test_support.sse_demo import build_application, SETTINGS_MODULE
from test_support.native_app import initialize
from test_support.native_app_fixture import (
    create_fixture, cleanup_fixture, verify_source,
)
verify_source()
f = create_fixture(Path(__import__('sys').argv[1]))
try:
    initialize(f, settings_module=SETTINGS_MODULE)
    app = build_application(f)
    assert app.response_timeout == 15 and app.sse_response_timeout == 70
    assert app.evidence is None
    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": None}
    try:
        build_application(f)
    except ValueError:
        pass
    else:
        raise AssertionError('disabled/mismatched fixture was admitted')
finally:
    connections.close_all()
    cleanup_fixture(f.root)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", program, str(tmp_path)],
        env=subprocess_environment(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.glob("native-app-*"))
