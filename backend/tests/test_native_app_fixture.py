"""Test-only fixture isolation and real Django/ASGI entry contracts."""

import asyncio
import importlib
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def fixture_module():
    return importlib.import_module("test_support.native_app_fixture")


def boundary_module():
    return importlib.import_module("test_support.native_app_boundary")


def test_conventional_asgi_entry_uses_real_django_handler():
    from django.core.handlers.asgi import ASGIHandler
    from django.core.signals import request_started

    senders = []

    def started(sender, **kwargs):
        senders.append(sender)

    request_started.connect(started, weak=False)

    async def run():
        queue = asyncio.Queue()
        queue.put_nowait({"type": "http.request", "body": b"", "more_body": False})
        sent = []

        async def send(event):
            sent.append(event)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/__fixture_missing__/",
            "raw_path": b"/__fixture_missing__/",
            "query_string": b"",
            "root_path": "",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 41000),
            "headers": [(b"host", b"testserver")],
        }
        await asyncio.wait_for(
            importlib.import_module("config.asgi").application(scope, queue.get, send),
            2,
        )
        assert sent[0]["type"] == "http.response.start"
        assert sent[0]["status"] == 404

    try:
        asyncio.run(run())
    finally:
        request_started.disconnect(started)
    assert senders == [ASGIHandler]


def test_create_fixture_only_uses_new_private_resources(tmp_path):
    module = fixture_module()
    first = module.create_fixture(tmp_path)
    second = module.create_fixture(tmp_path)
    assert first.root != second.root
    assert first.host != second.host
    assert first.root.parent == tmp_path
    assert first.root.stat().st_mode & 0o777 == 0o700
    assert first.config_file.stat().st_mode & 0o777 == 0o600
    assert not first.database.exists()
    assert len(first.secret) >= 48
    assert first.secret != second.secret
    assert first.host == f"hvt-{first.run_id}.local"
    assert len(first.run_id) == 32
    assert all(first.run_id in name for name in first.cookie_names)
    assert not set(first.cookie_names) & {
        "sessionid",
        "csrftoken",
        "django_language",
        "theme",
    }


def test_settings_override_all_real_resources_and_keep_security(tmp_path, monkeypatch):
    module = fixture_module()
    fixture = module.create_fixture(tmp_path)
    monkeypatch.setenv("ENABLE_REDIS_CACHE", "1")
    overrides = module.settings_overrides(fixture)
    assert overrides["DATABASES"]["default"]["NAME"] == fixture.database
    assert overrides["CACHES"]["default"]["BACKEND"].endswith("LocMemCache")
    assert overrides["ALLOWED_HOSTS"] == [fixture.host]
    assert overrides["SECRET_KEY"] == fixture.secret
    assert overrides["MEDIA_ROOT"].is_relative_to(fixture.root)
    assert overrides["FILE_UPLOAD_TEMP_DIR"].is_relative_to(fixture.root)
    assert overrides["SESSION_ENGINE"] == "django.contrib.sessions.backends.db"
    assert overrides["SESSION_COOKIE_HTTPONLY"] is True
    assert overrides["DEBUG"] is False
    for prefix in ("SESSION", "CSRF", "LANGUAGE"):
        assert overrides[f"{prefix}_COOKIE_DOMAIN"] is None
        assert overrides[f"{prefix}_COOKIE_NAME"] in fixture.cookie_names
        assert overrides[f"{prefix}_COOKIE_PATH"] == "/"


def test_load_requires_explicit_private_configuration(tmp_path, monkeypatch):
    module = fixture_module()
    monkeypatch.delenv(module.ROOT_ENV, raising=False)
    with pytest.raises(ValueError, match="explicit"):
        module.load_fixture()
    fixture = module.create_fixture(tmp_path)
    monkeypatch.setenv(module.ROOT_ENV, str(fixture.root))
    assert module.load_fixture() == fixture
    fixture.config_file.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        module.load_fixture()


def test_symlink_root_and_tampered_database_are_rejected(tmp_path, monkeypatch):
    module = fixture_module()
    fixture = module.create_fixture(tmp_path)
    link = tmp_path / "alias"
    link.symlink_to(fixture.root, target_is_directory=True)
    monkeypatch.setenv(module.ROOT_ENV, str(link))
    with pytest.raises(ValueError, match="symlink"):
        module.load_fixture()
    document = json.loads(fixture.config_file.read_text())
    document["database"] = "/some/original/db.sqlite3"
    fixture.config_file.write_text(json.dumps(document))
    monkeypatch.setenv(module.ROOT_ENV, str(fixture.root))
    with pytest.raises(ValueError, match="configuration"):
        module.load_fixture()


def test_cleanup_refuses_unowned_directories(tmp_path):
    module = fixture_module()
    sentinel = tmp_path / "keep"
    sentinel.write_text("untouched")
    with pytest.raises(ValueError):
        module.cleanup_fixture(tmp_path)
    assert sentinel.read_text() == "untouched"
    fixture = module.create_fixture(tmp_path)
    module.cleanup_fixture(fixture.root)
    assert not fixture.root.exists()


async def exercise(app, fixture, *, headers=None, events=None, path="/hv/", timeout=1):
    sent = []
    queue = asyncio.Queue()
    for event in events or [{"type": "http.request", "body": b"", "more_body": False}]:
        queue.put_nowait(event)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "server": ("127.0.0.1", 8788),
        "client": ("127.0.0.1", 40000),
        "headers": headers
        if headers is not None
        else [(b"host", f"{fixture.host}:8788".encode())],
    }
    boundary = boundary_module().NativeAppBoundary(
        app, fixture, body_timeout=timeout, response_timeout=timeout
    )

    async def send(event):
        sent.append(event)

    await boundary(scope, queue.get, send)
    return sent


async def ok_app(scope, receive, send):
    await receive()
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def test_cookie_whitelist_filters_before_app_and_never_emits_theme(tmp_path):
    fixture = fixture_module().create_fixture(tmp_path)
    own = fixture.cookie_names[0].encode()

    async def app(scope, receive, send):
        assert [v for k, v in scope["headers"] if k == b"cookie"] == [
            own + b"=synthetic"
        ]
        await receive()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"set-cookie", b"theme=dark; Path=/"),
                    (b"set-cookie", own + b"=new; Path=/; HttpOnly"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    sent = asyncio.run(
        exercise(
            app,
            fixture,
            headers=[
                (b"host", fixture.host.encode()),
                (
                    b"cookie",
                    b"theme=must-not-be-input; sessionid=real-sentinel; "
                    + own
                    + b"=synthetic",
                ),
            ],
        )
    )
    assert sent[0]["headers"] == [(b"set-cookie", own + b"=new; Path=/; HttpOnly")]


@pytest.mark.parametrize(
    "host", [b"127.0.0.1:8788", b"localhost", b"original.local", b"evil.example"]
)
def test_wrong_host_rejected_before_application(tmp_path, host):
    fixture = fixture_module().create_fixture(tmp_path)

    async def forbidden(*args):
        pytest.fail("wrong host reached app")

    sent = asyncio.run(exercise(forbidden, fixture, headers=[(b"host", host)]))
    assert sent[0]["status"] == 400


def test_duplicate_owned_cookie_rejected_before_application(tmp_path):
    fixture = fixture_module().create_fixture(tmp_path)
    own = fixture.cookie_names[0].encode()

    async def forbidden(*args):
        pytest.fail("ambiguous cookie reached app")

    sent = asyncio.run(
        exercise(
            forbidden,
            fixture,
            headers=[
                (b"host", fixture.host.encode()),
                (b"cookie", own + b"=a; " + own + b"=b"),
            ],
        )
    )
    assert sent[0]["status"] == 400


@pytest.mark.parametrize("declared", [False, True])
def test_request_cap_rejects_fixed_and_chunked_without_invoking_app(tmp_path, declared):
    fixture = fixture_module().create_fixture(tmp_path)

    async def forbidden(*args):
        pytest.fail("oversized body reached app")

    headers = [(b"host", fixture.host.encode())]
    if declared:
        headers.append((b"content-length", b"65537"))
    sent = asyncio.run(
        exercise(
            forbidden,
            fixture,
            headers=headers,
            events=[
                {"type": "http.request", "body": b"x" * 32768, "more_body": True},
                {"type": "http.request", "body": b"x" * 32769, "more_body": False},
            ],
        )
    )
    assert sent[0]["status"] == 413


def test_boundary_accepts_exact_limit_and_preserves_body(tmp_path):
    fixture = fixture_module().create_fixture(tmp_path)

    async def app(scope, receive, send):
        assert (await receive())["body"] == b"x" * 65536
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    sent = asyncio.run(
        exercise(app, fixture, events=[{"type": "http.request", "body": b"x" * 65536}])
    )
    assert sent[0]["status"] == 200


def test_disconnect_and_body_deadline_do_not_reach_app(tmp_path):
    fixture = fixture_module().create_fixture(tmp_path)

    async def forbidden(*args):
        pytest.fail("incomplete body reached app")

    assert (
        asyncio.run(exercise(forbidden, fixture, events=[{"type": "http.disconnect"}]))
        == []
    )
    sent = asyncio.run(
        exercise(
            forbidden,
            fixture,
            events=[{"type": "http.request", "body": b"", "more_body": True}],
            timeout=0.01,
        )
    )
    assert sent[0]["status"] == 408


def test_response_deadline_cancels_app_and_is_not_success(tmp_path):
    fixture = fixture_module().create_fixture(tmp_path)
    closed = []

    async def app(scope, receive, send):
        try:
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    sent = asyncio.run(exercise(app, fixture, timeout=0.01))
    assert sent[0]["status"] == 504
    assert closed == [True]


@pytest.mark.parametrize(
    "target", [b"http://127.0.0.1:8000/hv/", b"//original.local/hv/"]
)
def test_external_redirects_rejected(tmp_path, target):
    fixture = fixture_module().create_fixture(tmp_path)

    async def app(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 302,
                "headers": [(b"location", target)],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    sent = asyncio.run(exercise(app, fixture))
    assert sent[0]["status"] == 502


def test_relative_redirect_and_client_disconnect_remain_real(tmp_path):
    fixture = fixture_module().create_fixture(tmp_path)

    async def app(scope, receive, send):
        assert (await receive())["type"] == "http.request"
        assert (await receive())["type"] == "http.disconnect"
        await send(
            {
                "type": "http.response.start",
                "status": 302,
                "headers": [(b"location", b"/hv/")],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    sent = asyncio.run(
        exercise(
            app,
            fixture,
            events=[{"type": "http.request", "body": b""}, {"type": "http.disconnect"}],
        )
    )
    assert sent[0]["status"] == 302


def subprocess_environment():
    env = dict(os.environ)
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env.pop("HYPERTODO_NATIVE_APP_ROOT", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def test_real_subprocess_initializes_only_its_new_db_then_cleans(tmp_path):
    report = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "test_support.native_app",
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
    assert data["anonymous_state"] == 200
    assert data["password_login"] == 200 and data["authenticated_state"] is True
    assert data["foreign_task"] == 404 and data["csrf_rejected"] == 403
    assert data["cleaned"] is True
    assert not Path(data["root"]).exists()
    assert not any(
        secret in result.stdout + result.stderr
        for secret in ["password=", "Set-Cookie", "hvs1."]
    )
    assert data["source_version"] == importlib.metadata.version("dj-hyperview")
    assert data["provenance"] == "installed"


def test_missing_source_metadata_fails_before_creating_fixture(tmp_path):
    from tests.test_runtime_provenance import BACKEND, source_layout

    source, metadata = source_layout(tmp_path)
    env = subprocess_environment()
    env["PYTHONPATH"] = os.pathsep.join([str(source / "src"), str(BACKEND)])
    env["HYPERTODO_FIXTURE_SOURCE"] = str(source)
    env["HYPERTODO_FIXTURE_METADATA"] = str(metadata)
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "test_support.native_app",
            "--check-only",
            "--parent",
            str(tmp_path),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "source metadata" in result.stderr
    assert not list(tmp_path.glob("native-app-*"))


def test_allocation_failure_removes_new_private_directory(tmp_path, monkeypatch):
    module = fixture_module()
    import builtins

    original = builtins.open

    def fail_config(file, *args, **kwargs):
        if Path(file).name == "fixture.json":
            raise OSError("synthetic allocation failure")
        return original(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fail_config)
    with pytest.raises(OSError, match="synthetic"):
        module.create_fixture(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_launcher_failure_cleans_and_reports_failure(tmp_path, monkeypatch):
    module = importlib.import_module("test_support.native_app")
    report = tmp_path / "failure.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["fixture", "--check-only", "--parent", str(tmp_path), "--report", str(report)],
    )

    def fail_initialize(fixture, *, paginated=False):
        assert paginated is False
        raise RuntimeError("synthetic setup failure")

    monkeypatch.setattr(module, "initialize", fail_initialize)
    with pytest.raises(RuntimeError, match="synthetic"):
        module.main()
    assert json.loads(report.read_text())["passed"] is False
    assert list(tmp_path.iterdir()) == [report]


def test_body_length_mismatch_rejects_before_app(tmp_path):
    fixture = fixture_module().create_fixture(tmp_path)

    async def forbidden(*args):
        pytest.fail("incorrect content length reached app")

    sent = asyncio.run(
        exercise(
            forbidden,
            fixture,
            headers=[(b"host", fixture.host.encode()), (b"content-length", b"2")],
        )
    )
    assert sent[0]["status"] == 400


@pytest.mark.parametrize("explicit_bind", (False, True))
def test_real_loopback_asgi_http_and_deadline_cleanup(tmp_path, explicit_bind):
    import http.client
    import selectors

    report = tmp_path / "socket-report.json"
    requested_port = None
    bind_args = []
    if explicit_bind:
        import socket

        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            requested_port = reserved.getsockname()[1]
        bind_args = [
            "--bind",
            "127.0.0.1",
            "--port",
            str(requested_port),
            "--events-report",
            str(tmp_path / "events.jsonl"),
        ]
    process = subprocess.Popen(
        [
            sys.executable,
            "-B",
            "-m",
            "test_support.native_app",
            "--seconds",
            "2",
            *bind_args,
            "--parent",
            str(tmp_path),
            "--report",
            str(report),
        ],
        env=subprocess_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    connection = None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=15), "fixture did not announce a listener"
            line = process.stdout.readline()
        if not line:
            _, error = process.communicate(timeout=10)
            pytest.fail(f"fixture startup failed: {error}")
        listener = json.loads(line)
        if explicit_bind:
            assert listener["port"] == requested_port
        connection = http.client.HTTPConnection(
            "127.0.0.1", listener["port"], timeout=3
        )
        connection.request(
            "GET",
            "/hv/session-state/",
            headers={
                "Host": f"{listener['host']}:{listener['port']}",
                "X-HyperTodo-Client-Contract": "realtime-v1",
                "Cookie": (
                    "theme=synthetic-parent-sentinel; sessionid=synthetic-sentinel"
                ),
            },
        )
        response = connection.getresponse()
        status, document = response.status, json.loads(response.read(1024))
        assert status == 200 and document.get("authenticated") is False
        if explicit_bind:
            run = listener["host"].removeprefix("hvt-").removesuffix(".local")
            for sequence, kind in ((1, "ready"), (2, "complete")):
                event = {
                    "v": 1,
                    "run": run,
                    "sequence": sequence,
                    "platform": "ios",
                    "case": "startup",
                    "kind": kind,
                    "operation": None,
                    "route": 1 if kind == "ready" else None,
                    "outcome": None,
                    "reason": None,
                }
                connection.request(
                    "POST",
                    "/__native__/report/",
                    json.dumps(event),
                    headers={
                        "Host": f"{listener['host']}:{listener['port']}",
                        "Content-Type": "application/json",
                    },
                )
                upload = connection.getresponse()
                assert upload.status == 204
                upload.read()
        connection.close()
        _, error = process.communicate(timeout=10)
        assert process.returncode == 0, error
        data = json.loads(report.read_text())
        assert data["cleaned"] is True
        if explicit_bind:
            assert "passed" not in data and data["fixture_checks_passed"] is True
            assert data["events"] == {"state": "recorded", "records": 2, "reason": None}
            assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 2
        else:
            assert data["passed"] is True
        assert not Path(data["root"]).exists()
        connection = http.client.HTTPConnection(
            "127.0.0.1", listener["port"], timeout=1
        )
        with pytest.raises(ConnectionRefusedError):
            connection.connect()
    finally:
        if connection:
            connection.close()
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=10)


def test_report_outside_evidence_rejected_before_allocating(tmp_path, monkeypatch):
    module = importlib.import_module("test_support.native_app")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fixture",
            "--check-only",
            "--parent",
            str(tmp_path),
            "--report",
            "/outside-fixture/report.json",
        ],
    )

    def forbidden(*args):
        pytest.fail("report boundary not checked before allocating")

    monkeypatch.setattr(module, "create_fixture", forbidden)
    with pytest.raises(ValueError, match="report"):
        module.main()


def test_runner_provenance_is_checked_before_database_setup(tmp_path, monkeypatch):
    module = importlib.import_module("test_support.native_app")
    calls = []
    monkeypatch.setattr(sys, "argv", ["fixture", "--parent", str(tmp_path)])
    monkeypatch.setattr(
        module, "load_runner", lambda: calls.append("runner"), raising=False
    )

    def stop(fixture, *, paginated=False):
        assert paginated is False
        calls.append("setup")
        raise RuntimeError("end preflight test")

    monkeypatch.setattr(module, "initialize", stop)
    with pytest.raises(RuntimeError, match="preflight"):
        module.main()
    assert calls == ["runner", "setup"]
