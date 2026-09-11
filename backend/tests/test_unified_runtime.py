"""Ordinary commands share DB-first templates and after-commit realtime."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from dj_hyperview.contrib.database.services import publish_template
from django.db import transaction
from django.urls import reverse

from config import settings as base
from tests.test_session_contract import _confirm, _headers
from todo.realtime_auth import Identity, topics_for
from todo.realtime_notifications import private_topic, ui_topic

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    {
        "BACKEND": "dj_hyperview.contrib.database.sources.DatabaseSource",
        "OPTIONS": {"using": "default"},
    },
    {"BACKEND": "dj_hyperview.sources.FileSystemSource"},
]


@pytest.mark.parametrize(
    ("target", "cache", "host", "lan_ip"),
    [
        ("backend-run", False, "0.0.0.0", ""),
        ("backend-run-redis", True, "0.0.0.0", ""),
        ("backend-run-device", True, "0.0.0.0", "192.168.1.20"),
        ("backend-run-sse", False, "192.168.1.20", "192.168.1.20"),
        ("backend-run-sse", False, "127.0.0.1", ""),
    ],
)
def test_launchers_execute_one_settings_and_asgi_contract(
    tmp_path, target, cache, host, lan_ip
):
    # Execute Make, replacing only uv: inspect actual argv/settings without a server,
    # network connection, migration, or opening the application database.
    uv = tmp_path / "uv"
    probe = (
        "import importlib, json, os, sys\n"
        "sys.path.insert(0, os.getcwd())\n"
        "name = os.environ.get('DJANGO_SETTINGS_MODULE')\n"
        "settings = importlib.import_module(name or 'config.settings')\n"
        "print(json.dumps({'module': name, 'argv': sys.argv[1:], "
        "'sources': settings.HYPERVIEW['SOURCES'], "
        "'realtime': settings.HYPERVIEW['REALTIME'], "
        "'cache': settings.ENABLE_REDIS_CACHE, "
        "'hosts': settings.ALLOWED_HOSTS, "
        "'csrf': settings.CSRF_TRUSTED_ORIGINS}))\n"
    )
    uv.write_text(
        "#!/bin/bash\nexec "
        + shlex.quote(sys.executable)
        + " -c "
        + shlex.quote(probe)
        + ' "$@"\n'
    )
    uv.chmod(0o700)
    env = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "DJANGO_SETTINGS_MODULE": "tests.settings_schema",
        "ENABLE_REDIS_CACHE": "0",
        "REDIS_URL": "redis://127.0.0.1:6379/14",
        "LAN_IP": lan_ip,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    env.pop("DJANGO_ALLOWED_HOSTS", None)
    env.pop("CSRF_TRUSTED_ORIGINS", None)
    result = subprocess.run(
        ["make", "--no-print-directory", target],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    state = json.loads(result.stdout.splitlines()[-1])
    assert state["module"] == "config.settings"
    assert state["argv"] == [
        "run",
        "python",
        "-m",
        "uvicorn",
        "config.asgi:application",
        "--host",
        host,
        "--port",
        "8000",
        "--loop",
        "asyncio",
        "--http",
        "h11",
        "--ws",
        "none",
        "--no-proxy-headers",
    ]
    assert state["sources"] == SOURCES
    assert state["realtime"] == {
        "REDIS_URL": env["REDIS_URL"],
        "NAMESPACE": "hypertodo-development",
    }
    assert state["cache"] is cache
    if lan_ip:
        assert "192.168.1.20" in state["hosts"]
        assert "http://192.168.1.20:8000" in state["csrf"]
    elif target == "backend-run-sse":
        assert "127.0.0.1" in state["hosts"]
        assert "http://127.0.0.1:8000" in state["csrf"]
    else:
        assert "10.0.2.2" in state["hosts"]
        assert "http://10.0.2.2:8000" in state["csrf"]


def test_device_launcher_requires_lan_ip_before_starting_backend():
    result = subprocess.run(
        ["make", "--no-print-directory", "backend-run-device", "LAN_IP="],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "LAN_IP is required" in result.stdout
    assert "uvicorn" not in result.stdout


def test_no_alternate_application_settings_remain():
    assert not (ROOT / "backend/config/settings_sse.py").exists()


@pytest.mark.django_db
def test_normal_db_about_commit_hint_and_rollback_refresh(
    settings,
    client,
    user,
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    from todo import realtime_notifications

    # Use production sources and realtime, but KEEP the isolated pytest DB/cache.
    settings.HYPERVIEW = dict(base.HYPERVIEW)
    assert settings.HYPERVIEW["SOURCES"] == SOURCES
    settings.HYPERVIEW.pop("CACHE", None)
    seen = []
    monkeypatch.setattr(
        realtime_notifications,
        "_publish",
        lambda config, intent: seen.append((config, intent)),
    )
    client.force_login(user)
    binding, _ = _confirm(client, True)
    headers = _headers(binding)
    name = "screens/about.xml"
    original = (base.BASE_DIR / "hyperview" / name).read_text()
    first = original.replace(
        '<body style="screen">', '<body style="screen"><text>DB About initial</text>'
    )
    updated = first.replace("DB About initial", "DB About committed")
    rolled_back = updated.replace("DB About committed", "DB About rollback")
    route = reverse("todo:about")
    assert b'id="about-screen"' in client.get(route, headers=headers).content
    with django_capture_on_commit_callbacks(execute=True):
        publish_template(name, first, using="default")
        assert seen == []
    assert len(seen) == 1
    assert b"DB About initial" in client.get(route, headers=headers).content
    seen.clear()
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            publish_template(name, updated, using="default", expected_revision=1)
            assert seen == []
    assert len(seen) == 1
    config, intent = seen[0]
    assert config.redis_url == base.REDIS_URL
    assert config.namespace == "hypertodo-development"
    assert intent.topics == (ui_topic("default"),)
    assert intent.payload == {"version": 1, "resources": ["ui"]}
    assert topics_for(Identity("default", str(user.pk), "binding")) == (
        private_topic("default", user.pk),
        ui_topic("default"),
    )
    response = client.get(route, headers=headers)
    assert response.status_code == 200
    assert b"DB About committed" in response.content
    assert b'id="about-screen"' in response.content
    assert b"app:realtime" in response.content
    seen.clear()
    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                publish_template(
                    name, rolled_back, using="default", expected_revision=2
                )
                raise RuntimeError("rollback")
    assert seen == []
    response = client.get(route, headers=headers)
    assert b"DB About committed" in response.content
    assert b"DB About rollback" not in response.content
