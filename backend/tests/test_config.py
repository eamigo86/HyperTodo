"""Tests for environment-backed Django configuration helpers."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from dj_hyperview.schema import get_hyperview_catalog
from django.conf import settings
from django.core.cache import cache
from pytest_django.fixtures import Settings

from config.environment import csv_setting


def test_csv_setting_normalizes_nonempty_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Csv setting normalizes nonempty values.

    Args:
        monkeypatch: Patches the code under test for this test.
    """
    monkeypatch.setenv(
        "TEST_HOSTS",
        "127.0.0.1, 192.168.1.20 ,,localhost ",
    )

    assert csv_setting("TEST_HOSTS", "fallback") == [
        "127.0.0.1",
        "192.168.1.20",
        "localhost",
    ]


def test_csv_setting_uses_default_when_environment_value_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Csv setting uses default when environment value is absent.

    Args:
        monkeypatch: Patches the code under test for this test.
    """
    monkeypatch.delenv("TEST_HOSTS", raising=False)

    assert csv_setting("TEST_HOSTS", "127.0.0.1,localhost") == [
        "127.0.0.1",
        "localhost",
    ]


def test_hxml_admin_editor_and_project_catalog_are_enabled() -> None:
    """Hxml admin editor and project catalog are enabled."""
    assert "django_ace" in settings.INSTALLED_APPS
    assert settings.HYPERVIEW["ADMIN"] == {"EDITOR": True}
    from config.schema import schema_extensions

    assert "SCHEMA_PROFILE" not in settings.HYPERVIEW
    assert "VALIDATION" not in settings.HYPERVIEW
    assert settings.HYPERVIEW["SCHEMA_EXTENSIONS"] == schema_extensions()
    schemas = settings.HYPERVIEW["EXTRA_SCHEMAS"]
    assert schemas == [settings.BASE_DIR / "schema" / "hypertodo.xsd"]
    assert all(isinstance(path, Path) and path.is_file() for path in schemas)


def test_project_schema_extends_the_admin_completion_catalog() -> None:
    """Project schema extends the admin completion catalog."""
    elements = get_hyperview_catalog()["elements"]
    namespace = "https://hypertodo.app/components"

    for name in (
        "side-menu",
        "swipe-row",
        "swipe-action",
        "edge-menu-opener",
        "time-picker",
    ):
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
    "'source_probe': s.HYPERTODO_SOURCE_PROBE, "
    "'namespace': s.HYPERVIEW['REALTIME']['NAMESPACE']}))"
)
# Whether the real URLconf routes the acceptance fixture, which only a started
# project can answer: the routes are built once, when todo.urls is first imported.
ROUTING = (
    "import json, django; django.setup()\n"
    "from django.urls import Resolver404, resolve\n"
    "try:\n"
    "    resolve('/hv/source-probe/')\n"
    "    routed = True\n"
    "except Resolver404:\n"
    "    routed = False\n"
    "print(json.dumps({'routed': routed}))"
)
STRONG_KEY = "abcdefghij" * 6
PRODUCTION = {"DJANGO_DEBUG": "0", "DJANGO_SECRET_KEY": STRONG_KEY}


def load_settings(script: str = PROBE, **env: str) -> subprocess.CompletedProcess[str]:
    """Run a script in a clean interpreter, like a real process start.

    Args:
        script: Python source the interpreter runs.
        **env: Environment variables set for the interpreter.

    Returns:
        The finished process with its captured output.
    """
    inherited = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("DJANGO_", "HYPERTODO_"))
    }
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND,
        env={**inherited, **env},
        capture_output=True,
        text=True,
        timeout=30,
    )


def resolved(**env: str) -> dict[str, object]:
    """Load the settings in a clean interpreter and return what it printed as JSON.

    Args:
        **env: Environment variables set for the interpreter.

    Returns:
        The settings the probe script reported.
    """
    result = load_settings(**env)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_development_defaults_keep_debug_on_without_secure_cookies() -> None:
    """Development defaults keep debug on without secure cookies."""
    state = resolved()

    assert state["debug"] is True
    assert (state["session_secure"], state["csrf_secure"]) == (False, False)
    assert state["proxy"] is None


def test_leaving_debug_requires_a_private_secret_key() -> None:
    """Leaving debug requires a private secret key."""
    result = load_settings(DJANGO_DEBUG="0")

    assert result.returncode != 0
    assert "Set DJANGO_SECRET_KEY when DJANGO_DEBUG=0" in result.stderr
    assert "ImproperlyConfigured" in result.stderr


def test_an_empty_secret_key_counts_as_unset() -> None:
    """An empty secret key counts as unset."""
    # DJANGO_SECRET_KEY= in an env file used to slip past the guard below and fail
    # later inside Django with a less helpful message.
    result = load_settings(DJANGO_DEBUG="0", DJANGO_SECRET_KEY="")

    assert result.returncode != 0
    assert "Set DJANGO_SECRET_KEY when DJANGO_DEBUG=0" in result.stderr
    assert resolved(DJANGO_SECRET_KEY="")["debug"] is True


@pytest.mark.parametrize("blank", [" ", "   ", "\t", " \n "])
def test_a_whitespace_only_secret_key_counts_as_unset(blank: str) -> None:
    """A whitespace only secret key counts as unset.

    Args:
        blank: Whitespace-only value of the secret key.
    """
    # "DJANGO_SECRET_KEY=   " is set and not empty, so it used to become the key itself
    # and walk past the guard.
    result = load_settings(DJANGO_DEBUG="0", DJANGO_SECRET_KEY=blank)

    assert result.returncode != 0
    assert "Set DJANGO_SECRET_KEY when DJANGO_DEBUG=0" in result.stderr
    assert resolved(DJANGO_SECRET_KEY=blank)["debug"] is True


def test_the_public_key_is_still_refused_when_whitespace_pads_it() -> None:
    """The public key is still refused when whitespace pads it."""
    result = load_settings(
        DJANGO_DEBUG="0", DJANGO_SECRET_KEY=" development-only-secret-key\n"
    )

    assert result.returncode != 0
    assert "Set DJANGO_SECRET_KEY when DJANGO_DEBUG=0" in result.stderr


def test_whitespace_around_a_secret_key_is_not_part_of_it() -> None:
    """Whitespace around a secret key is not part of it."""
    result = load_settings(
        "import config.settings as s; print(repr(s.SECRET_KEY))",
        DJANGO_DEBUG="0",
        DJANGO_SECRET_KEY=f" {STRONG_KEY}\n",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == repr(STRONG_KEY)


def test_any_debug_value_other_than_one_turns_debug_off() -> None:
    """Any debug value other than one turns debug off."""
    for value in ("0", "false", "", "yes"):
        assert (
            resolved(DJANGO_DEBUG=value, DJANGO_SECRET_KEY=STRONG_KEY)["debug"] is False
        )


def test_the_public_key_stays_acceptable_in_debug_only() -> None:
    """The public key stays acceptable in debug only."""
    assert resolved(DJANGO_SECRET_KEY="development-only-secret-key")["debug"] is True
    result = load_settings(
        DJANGO_DEBUG="0", DJANGO_SECRET_KEY="development-only-secret-key"
    )

    assert result.returncode != 0


def test_leaving_debug_turns_on_secure_cookies() -> None:
    """Leaving debug turns on secure cookies."""
    state = resolved(DJANGO_DEBUG="0", DJANGO_SECRET_KEY=STRONG_KEY)

    assert state["debug"] is False
    assert (state["session_secure"], state["csrf_secure"]) == (True, True)


def test_the_four_standard_password_validators_are_active() -> None:
    """The four standard password validators are active."""
    assert resolved()["validators"] == [
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    ]


def test_the_proxy_ssl_header_is_opt_in() -> None:
    """The proxy ssl header is opt in."""
    state = resolved(DJANGO_SECURE_PROXY_SSL_HEADER="HTTP_X_FORWARDED_PROTO")

    assert state["proxy"] == ["HTTP_X_FORWARDED_PROTO", "https"]


@pytest.mark.parametrize(
    "written",
    [
        "X-Forwarded-Proto",
        "x-forwarded-proto",
        " X-Forwarded-Proto ",
        "http_x_forwarded_proto",
    ],
)
def test_the_proxy_ssl_header_may_be_written_as_the_http_header_name(
    written: str,
) -> None:
    """The proxy ssl header may be written as the http header name.

    Args:
        written: Spelling of the proxy SSL header name.
    """
    # Django reads the META key, so "X-Forwarded-Proto" on its own matched nothing and
    # left the setting silently inert.
    state = resolved(DJANGO_SECURE_PROXY_SSL_HEADER=written)

    assert state["proxy"] == ["HTTP_X_FORWARDED_PROTO", "https"]


def test_a_blank_proxy_ssl_header_stays_unset() -> None:
    """A blank proxy ssl header stays unset."""
    assert resolved(DJANGO_SECURE_PROXY_SSL_HEADER=" ")["proxy"] is None


def test_the_source_probe_follows_debug_unless_the_environment_says_otherwise() -> None:
    """The source probe follows debug unless the environment says otherwise."""
    assert resolved()["source_probe"] is True
    assert resolved(**PRODUCTION)["source_probe"] is False
    assert resolved(**PRODUCTION, HYPERTODO_SOURCE_PROBE="1")["source_probe"] is True
    assert resolved(HYPERTODO_SOURCE_PROBE="0")["source_probe"] is False


@pytest.mark.parametrize("value", ["true", "yes", ""])
def test_only_the_exact_value_one_turns_the_source_probe_on(value: str) -> None:
    """Only the exact value one turns the source probe on.

    Args:
        value: Value of the source probe switch.
    """
    # docs/installed-adoption.md states this. Unset, development routes the probe, so
    # an operator who writes "true" and loses the route is the surprise worth pinning.
    assert resolved(HYPERTODO_SOURCE_PROBE=value)["source_probe"] is False


def routed(**env: str) -> object:
    """Report whether the source probe route resolves under a given environment.

    Args:
        **env: Environment variables set for the interpreter.

    Returns:
        True when the route resolves.
    """
    result = load_settings(ROUTING, DJANGO_SETTINGS_MODULE="config.settings", **env)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["routed"]


def test_the_source_probe_is_only_routed_when_it_is_enabled() -> None:
    """The source probe is only routed when it is enabled."""
    # The fixture answers anonymous callers, so a production URLconf must not carry
    # it unless an operator asked. Not a 404 from the view: the route is absent.
    assert routed(**PRODUCTION) is False
    assert routed(**PRODUCTION, HYPERTODO_SOURCE_PROBE="1") is True
    assert routed() is True


def test_the_test_settings_enable_the_source_probe_their_consumers_need() -> None:
    """The test settings enable the source probe their consumers need."""
    assert settings.HYPERTODO_SOURCE_PROBE is True


CACHES_PROBE = "import json, config.settings as s; print(json.dumps(s.CACHES))"


def test_the_default_cache_holds_a_counter_through_a_flood_of_distinct_keys(
    settings: Settings,
) -> None:
    """The default cache holds a counter through a flood of distinct keys.

    Args:
        settings: Django settings overridden by this test.
    """
    # LocMemCache keeps 300 entries unless told otherwise and then culls the least
    # recently used ones, so a few hundred junk keys used to evict a running sign-in
    # counter and hand its owner a fresh budget.
    result = load_settings(CACHES_PROBE, ENABLE_REDIS_CACHE="0")
    assert result.returncode == 0, result.stderr
    app_cache = json.loads(result.stdout)["default"]
    settings.CACHES = {"default": {**app_cache, "LOCATION": "eviction-probe"}}

    cache.set("counter", 1, timeout=60)
    for index in range(5_000):
        cache.set(f"junk-{index}", 1, timeout=60)

    assert cache.get("counter") == 1
    cache.clear()


def test_the_realtime_namespace_defaults_and_follows_the_environment() -> None:
    """The realtime namespace defaults and follows the environment."""
    assert resolved()["namespace"] == "hypertodo-development"
    assert resolved(HYPERTODO_REALTIME_NAMESPACE="hypertodo-staging")["namespace"] == (
        "hypertodo-staging"
    )


def test_a_strong_key_without_debug_clears_the_deploy_checks_this_change_owns() -> None:
    """A strong key without debug clears the deploy checks this change owns."""
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
