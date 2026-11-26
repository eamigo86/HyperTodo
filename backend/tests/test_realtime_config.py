"""Central package configuration with app-owned migration and session policy."""

import copy
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from pytest_django.fixtures import Settings

from todo.realtime_config import get_realtime_config

CONFIG = {"REDIS_URL": "redis://127.0.0.1:6379/14", "NAMESPACE": "central-test"}


@pytest.fixture(autouse=True)
def remove_legacy_setting(settings: Settings) -> None:
    """Remove the legacy realtime setting so each test starts from the central one.

    Args:
        settings: Django settings overridden by this test.
    """
    if hasattr(settings, "HYPERTODO_REALTIME"):
        del settings.HYPERTODO_REALTIME


def test_normal_application_enables_central_realtime() -> None:
    """The normal application enables the central realtime configuration."""
    from config import settings

    assert not hasattr(settings, "HYPERTODO_REALTIME")
    assert settings.HYPERVIEW["REALTIME"] == {
        "REDIS_URL": settings.REDIS_URL,
        "NAMESPACE": "hypertodo-development",
    }


def test_nested_config_preserves_schema_sources_and_immutable_snapshot(
    settings: Settings,
) -> None:
    """The nested configuration keeps its sources and is an immutable snapshot.

    Args:
        settings: Django settings overridden by this test.
    """
    from dj_hyperview import validate_hyperview_schema
    from dj_hyperview.conf import get_settings

    previous = copy.deepcopy(settings.HYPERVIEW)
    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG.copy()}
    with patch("socket.socket.connect", side_effect=AssertionError("network")):
        configured = get_realtime_config()
        assert configured is not None
        assert configured == get_settings().realtime
        assert configured.redis_url == CONFIG["REDIS_URL"]
        assert configured.namespace == CONFIG["NAMESPACE"]
        assert "redis://" not in repr(configured)
        with pytest.raises(FrozenInstanceError):
            configured.namespace = "changed"
        validate_hyperview_schema(
            '<doc xmlns="https://hyperview.org/hyperview" '
            'xmlns:app="https://hypertodo.app/components"><screen><body>'
            '<app:realtime resources="tasks" refresh-href="/hv/tasks/" '
            'target="tasks" mode="notice"><app:realtime-page '
            'request-id="untracked" page="1"/><behavior trigger="load" '
            'action="notify-resources" resources="tasks"/>'
            "</app:realtime></body></screen></doc>"
        )
    assert settings.HYPERVIEW["SOURCES"] == previous["SOURCES"]
    assert settings.HYPERVIEW["EXTRA_SCHEMAS"] == previous["EXTRA_SCHEMAS"]
    assert settings.HYPERVIEW["SCHEMA_EXTENSIONS"] == previous["SCHEMA_EXTENSIONS"]
    settings.HYPERVIEW["REALTIME"]["NAMESPACE"] = "later"
    assert configured.namespace == CONFIG["NAMESPACE"]


@pytest.mark.parametrize("present", [False, True])
def test_omitted_or_none_disables_without_database_session_policy(
    settings: Settings, present: bool
) -> None:
    """An omitted or None configuration disables realtime with no session policy.

    Args:
        settings: Django settings overridden by this test.
        present: Whether the realtime key stays in the settings with a None value
        instead of being omitted.
    """
    nested = {k: v for k, v in settings.HYPERVIEW.items() if k != "REALTIME"}
    if present:
        nested["REALTIME"] = None
    settings.HYPERVIEW = nested
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
    with patch("socket.socket.connect", side_effect=AssertionError("network")):
        assert get_realtime_config() is None


@pytest.mark.parametrize("value", [None, CONFIG, {}])
def test_legacy_setting_is_rejected_even_when_central_config_exists(
    settings: Settings, value: dict[str, str] | None
) -> None:
    """The legacy setting is rejected even when the central configuration exists.

    Args:
        settings: Django settings overridden by this test.
        value: Value given to the legacy setting.
    """
    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG.copy()}
    settings.HYPERTODO_REALTIME = value
    with pytest.raises(ImproperlyConfigured, match="HYPERTODO_REALTIME.*HYPERVIEW"):
        get_realtime_config()


def test_active_central_config_retains_database_session_policy(
    settings: Settings,
) -> None:
    """An active central configuration retains the database session policy.

    Args:
        settings: Django settings overridden by this test.
    """
    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG.copy()}
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
    with pytest.raises(ImproperlyConfigured, match="database sessions"):
        get_realtime_config()


@pytest.mark.parametrize("value", ["None", repr(CONFIG)])
def test_real_startup_rejects_legacy_without_database_or_network(
    tmp_path: Path, value: str
) -> None:
    """A real startup rejects the legacy setting before any database or network use.

    Args:
        tmp_path: Temporary directory for the files this test writes.
        value: Source text of the legacy setting that the settings module defines.
    """
    module = tmp_path / "realtime_legacy_startup.py"
    module.write_text(
        f"from tests.settings_schema import *\nHYPERTODO_REALTIME = {value}\n"
    )
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join(
            filter(
                None,
                [
                    str(tmp_path),
                    str(Path(__file__).resolve().parents[1]),
                    os.environ.get("PYTHONPATH", ""),
                ],
            )
        ),
        "DJANGO_SETTINGS_MODULE": module.stem,
    }
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "from unittest.mock import patch\n"
            "import django\n"
            "from django.db.backends.base.base import BaseDatabaseWrapper\n"
            "with patch('socket.socket.connect', "
            "side_effect=AssertionError) as network, "
            "patch.object(BaseDatabaseWrapper, 'ensure_connection', "
            "side_effect=AssertionError) as sql:\n"
            "    try:\n"
            "        django.setup()\n"
            "    finally:\n"
            "        assert network.call_count == sql.call_count == 0\n",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "HYPERTODO_REALTIME" in result.stderr and "HYPERVIEW" in result.stderr
    assert result.stderr.splitlines()[-1].startswith(
        "django.core.exceptions.ImproperlyConfigured:"
    )
