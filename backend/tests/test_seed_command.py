"""Tests for the idempotent local demo-data command."""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from todo.models import Category, Task

pytestmark = pytest.mark.django_db


def test_seed_demo_is_idempotent_and_reads_password_from_environment(monkeypatch):
    monkeypatch.setenv("HYPERTODO_DEMO_PASSWORD", "local-only-password")
    call_command("seed_demo", username="demo")
    call_command("seed_demo", username="demo")
    user = get_user_model().objects.get(username="demo")
    assert user.check_password("local-only-password")
    assert Category.objects.filter(user=user).count() == 4
    assert Task.objects.filter(user=user).count() == 5


def test_seed_demo_requires_an_uncommitted_password(monkeypatch):
    monkeypatch.delenv("HYPERTODO_DEMO_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="HYPERTODO_DEMO_PASSWORD"):
        call_command("seed_demo")
