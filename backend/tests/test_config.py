"""Tests for environment-backed Django configuration helpers."""

import json
import os
import subprocess
import sys
from pathlib import Path

from dj_hyperview.schema import get_hyperview_catalog
from django.conf import settings

from config.environment import csv_setting


def test_csv_setting_normalizes_nonempty_values(monkeypatch):
    monkeypatch.setenv(
        "TEST_HOSTS",
        "127.0.0.1, 192.168.1.20 ,,localhost ",
    )

    assert csv_setting("TEST_HOSTS", "fallback") == [
        "127.0.0.1",
        "192.168.1.20",
        "localhost",
    ]


def test_csv_setting_uses_default_when_environment_value_is_absent(monkeypatch):
    monkeypatch.delenv("TEST_HOSTS", raising=False)

    assert csv_setting("TEST_HOSTS", "127.0.0.1,localhost") == [
        "127.0.0.1",
        "localhost",
    ]


def test_hxml_admin_editor_and_project_catalog_are_enabled():
    assert "django_ace" in settings.INSTALLED_APPS
    assert settings.HYPERVIEW["ADMIN"] == {"EDITOR": True}
    from config.schema import schema_extensions

    assert "SCHEMA_PROFILE" not in settings.HYPERVIEW
    assert "VALIDATION" not in settings.HYPERVIEW
    assert settings.HYPERVIEW["SCHEMA_EXTENSIONS"] == schema_extensions()
    schemas = settings.HYPERVIEW["EXTRA_SCHEMAS"]
    assert schemas == [settings.BASE_DIR / "schema" / "hypertodo.xsd"]
    assert all(isinstance(path, Path) and path.is_file() for path in schemas)


def test_project_schema_extends_the_admin_completion_catalog():
    elements = get_hyperview_catalog()["elements"]
    namespace = "https://hypertodo.app/components"

    for name in ("side-menu", "swipe-row", "swipe-action", "edge-menu-opener"):
        assert f"{{{namespace}}}{name}" in elements
    categories = (
        settings.BASE_DIR / "hyperview" / "screens" / "categories.xml"
    ).read_text(encoding="utf-8")
    assert f'xmlns:app="{namespace}"' in categories


BACKEND = Path(__file__).resolve().parents[1]
PROBE = (
    "import json, config.settings as s; print(json.dumps({"
    "'debug': s.DEBUG, "
    "'session_secure': getattr(s, 'SESSION_COOKIE_SECURE', False), "
    "'csrf_secure': getattr(s, 'CSRF_COOKIE_SECURE', False), "
    "'proxy': getattr(s, 'SECURE_PROXY_SSL_HEADER', None), "
    "'validators': [v['NAME'].rsplit('.', 1)[1] for v in s.AUTH_PASSWORD_VALIDATORS], "
    "'namespace': s.HYPERVIEW['REALTIME']['NAMESPACE']}))"
)
STRONG_KEY = "abcdefghij" * 6


def load_settings(**env):
    """Import config.settings in a clean interpreter, like a real process start."""
    inherited = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("DJANGO_", "HYPERTODO_"))
    }
    return subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=BACKEND,
        env={**inherited, **env},
        capture_output=True,
        text=True,
        timeout=30,
    )


def resolved(**env):
    result = load_settings(**env)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_development_defaults_keep_debug_on_without_secure_cookies():
    state = resolved()

    assert state["debug"] is True
    assert (state["session_secure"], state["csrf_secure"]) == (False, False)
    assert state["proxy"] is None


def test_leaving_debug_requires_a_private_secret_key():
    result = load_settings(DJANGO_DEBUG="0")

    assert result.returncode != 0
    assert "Set DJANGO_SECRET_KEY when DJANGO_DEBUG=0" in result.stderr
    assert "ImproperlyConfigured" in result.stderr


def test_the_public_key_stays_acceptable_in_debug_only():
    assert resolved(DJANGO_SECRET_KEY="development-only-secret-key")["debug"] is True
    result = load_settings(
        DJANGO_DEBUG="0", DJANGO_SECRET_KEY="development-only-secret-key"
    )

    assert result.returncode != 0


def test_leaving_debug_turns_on_secure_cookies():
    state = resolved(DJANGO_DEBUG="0", DJANGO_SECRET_KEY=STRONG_KEY)

    assert state["debug"] is False
    assert (state["session_secure"], state["csrf_secure"]) == (True, True)


def test_the_four_standard_password_validators_are_active():
    assert resolved()["validators"] == [
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    ]


def test_the_proxy_ssl_header_is_opt_in():
    state = resolved(DJANGO_SECURE_PROXY_SSL_HEADER="HTTP_X_FORWARDED_PROTO")

    assert state["proxy"] == ["HTTP_X_FORWARDED_PROTO", "https"]


def test_the_realtime_namespace_defaults_and_follows_the_environment():
    assert resolved()["namespace"] == "hypertodo-development"
    assert resolved(HYPERTODO_REALTIME_NAMESPACE="hypertodo-staging")["namespace"] == (
        "hypertodo-staging"
    )


def test_a_strong_key_without_debug_clears_the_deploy_checks_this_change_owns():
    result = subprocess.run(
        [sys.executable, "manage.py", "check", "--deploy"],
        cwd=BACKEND,
        env={
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings",
            "DJANGO_DEBUG": "0",
            "DJANGO_SECRET_KEY": STRONG_KEY,
        },
        capture_output=True,
        text=True,
        timeout=60,
    )

    for check in ("W009", "W012", "W016", "W018"):
        assert f"security.{check}" not in result.stderr + result.stdout
