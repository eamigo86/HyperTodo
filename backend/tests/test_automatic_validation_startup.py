"""Fail-closed consumer startup for the automatic validation contract."""

import importlib
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import dj_hyperview
import pytest
from django.core.cache import CacheHandler
from django.core.exceptions import ImproperlyConfigured
from django.db.backends.base.base import BaseDatabaseWrapper

from todo.apps import TodoConfig


@pytest.mark.parametrize("contract", (None, "optional-xsd-v1", True))
def test_ready_rejects_missing_or_incompatible_contract(monkeypatch, contract):
    if contract is None:
        monkeypatch.delattr(
            dj_hyperview, "HYPERVIEW_VALIDATION_CONTRACT", raising=False
        )
    else:
        monkeypatch.setattr(
            dj_hyperview, "HYPERVIEW_VALIDATION_CONTRACT", contract, raising=False
        )
    app = TodoConfig("todo", importlib.import_module("todo"))
    with pytest.raises(ImproperlyConfigured, match="automatic-xsd-v1"):
        app.ready()


def test_ready_accepts_contract_without_database_or_cache_work(monkeypatch):
    monkeypatch.setattr(
        dj_hyperview, "HYPERVIEW_VALIDATION_CONTRACT", "automatic-xsd-v1", raising=False
    )
    app = TodoConfig("todo", importlib.import_module("todo"))
    with (
        patch.object(
            BaseDatabaseWrapper,
            "ensure_connection",
            side_effect=AssertionError("startup SQL"),
        ),
        patch.object(
            CacheHandler, "__getitem__", side_effect=AssertionError("startup cache")
        ),
    ):
        app.ready()


@pytest.mark.parametrize("contract", (None, "automatic-xsd-v1"))
def test_django_setup_checks_contract_without_system_check_command(contract):
    code = """
import sys
import dj_hyperview
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.backends.base.base import BaseDatabaseWrapper
from unittest.mock import patch
import django
contract = sys.argv[1]
if contract == 'missing':
    if hasattr(dj_hyperview, 'HYPERVIEW_VALIDATION_CONTRACT'):
        del dj_hyperview.HYPERVIEW_VALIDATION_CONTRACT
else:
    dj_hyperview.HYPERVIEW_VALIDATION_CONTRACT = contract
settings.configure(
    SECRET_KEY='isolated-startup-test',
    INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes', 'todo'],
    DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
with patch.object(
    BaseDatabaseWrapper, 'ensure_connection',
    side_effect=AssertionError('startup SQL'),
):
    try:
        django.setup()
    except ImproperlyConfigured as error:
        print(str(error))
        sys.exit(4)
print('startup accepted')
"""
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    environment.pop("DJANGO_SETTINGS_MODULE", None)
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, contract or "missing"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == (0 if contract else 4), result.stdout + result.stderr
    assert ("startup accepted" if contract else "automatic-xsd-v1") in result.stdout
