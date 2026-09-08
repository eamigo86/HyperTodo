"""Tests for environment-backed Django configuration helpers."""

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
