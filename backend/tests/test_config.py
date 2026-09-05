"""Tests for environment-backed Django configuration helpers."""

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
