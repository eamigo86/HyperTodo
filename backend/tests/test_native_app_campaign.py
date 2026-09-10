"""Finite native-App campaign fixture; Python controls are not native proof."""

import importlib
import json
import subprocess
import sys

import pytest

from tests.test_native_app_fixture import subprocess_environment


def launcher():
    return importlib.import_module("test_support.native_app")


@pytest.mark.parametrize(
    "address,port",
    [
        ("0.0.0.0", 8788),
        ("::", 8788),
        ("::1", 8788),
        ("8.8.8.8", 8788),
        ("169.254.1.1", 8788),
        ("localhost", 8788),
        ("192.168.04.43", 8788),
        ("192.168.4.43 ", 8788),
        ("192.168.4.43", 0),
        ("192.168.4.43", 80),
        ("127.0.0.1", -1),
        ("127.0.0.1", 65536),
        ("127.0.0.1", True),
    ],
)
def test_listener_rejects_nonexplicit_or_unsafe_scope(address, port):
    with pytest.raises(ValueError):
        launcher().validate_listener(address, port)


@pytest.mark.parametrize(
    "address,port",
    [
        ("127.0.0.1", 0),
        ("127.0.0.1", 8788),
        ("192.168.4.43", 8788),
        ("10.2.3.4", 8080),
        ("172.16.0.1", 65535),
    ],
)
def test_listener_allows_only_explicit_loopback_or_rfc1918(address, port):
    assert launcher().validate_listener(address, port) == (address, port)


def test_failed_interface_bind_closes_socket_without_fallback(monkeypatch):
    calls = []

    class UnavailableInterface:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls.append("closed")

        def bind(self, address):
            calls.append(address)
            raise OSError("synthetic unassigned interface")

    monkeypatch.setattr(launcher().socket, "socket", UnavailableInterface)
    with pytest.raises(OSError, match="unassigned"):
        with launcher().listener_socket("192.168.4.43", 8788):
            pytest.fail("must never continue or fall back to another interface")
    assert calls == [("192.168.4.43", 8788), "closed"]


def test_explicit_paginated_dataset_uses_actual_two_page_filtered_owner_routes(
    tmp_path,
):
    report = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "test_support.native_app",
            "--check-only",
            "--paginated",
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
    assert data["tasks"] == 24
    assert data["owner_tasks"] == [22, 2]
    assert data["page_items"] == [20, 2]
    assert data["filtered_owner_only"] is True
    assert data["foreign_task"] == 404 and data["csrf_rejected"] == 403
    assert data["cleaned"] is True
    assert not __import__("pathlib").Path(data["root"]).exists()
    assert all(
        secret not in result.stdout for secret in ("hvs1.", "Set-Cookie", "password=")
    )


def test_host_control_refuses_nonfixture_database_before_business_work(tmp_path):
    from tests.test_native_app_fixture import fixture_module

    fixture = fixture_module().create_fixture(tmp_path)
    with pytest.raises(ValueError, match="fixture database"):
        launcher().apply_control(fixture, "rename-task")


def test_host_controls_only_mutate_synthetic_owner_and_sessions(tmp_path):
    script = """
import json,sys
from pathlib import Path
from test_support.native_app import initialize,apply_control
from test_support.native_app_fixture import create_fixture,cleanup_fixture,verify_source
verify_source();fixture=create_fixture(Path(sys.argv[1]))
try:
 credentials=initialize(fixture,paginated=True)
 from django.contrib.auth import get_user_model
 from django.contrib.sessions.models import Session
 from django.test import Client
 from django.db import connections
 from todo.models import Task
 User=get_user_model();a=User.objects.get(username=credentials['owner_a']['username']);b=User.objects.get(username=credentials['owner_b']['username'])
 ca,cb=Client(),Client();ca.force_login(a);cb.force_login(b)
 akey,bkey=ca.session.session_key,cb.session.session_key
 before=list(Task.objects.filter(user=b).values_list('title',flat=True))
 renamed=apply_control(fixture,'rename-task');revoked=apply_control(fixture,'revoke-session')
 result={
  'renamed':renamed,'revoked':revoked,
  'only_a':Task.objects.filter(
   user=a,title='Fictional owner_a updated task').count()==1,
  'b_tasks_unchanged':before==list(
   Task.objects.filter(user=b).values_list('title',flat=True)),
  'a_revoked':not Session.objects.filter(session_key=akey).exists(),
  'b_retained':Session.objects.filter(session_key=bkey).exists(),
 }
 assert all(result[k] for k in ('only_a','b_tasks_unchanged','a_revoked','b_retained'))
 print(json.dumps(result))
finally:
 from django.db import connections
 connections.close_all();cleanup_fixture(fixture.root)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(tmp_path)],
        env=subprocess_environment(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["renamed"] == {"control": "rename-task", "affected": 1}
    assert value["revoked"] == {"control": "revoke-session", "affected": 1}
    assert list(tmp_path.iterdir()) == []
