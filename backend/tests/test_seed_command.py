"""Tests for the idempotent local demo-data command."""

import pytest
from dj_hyperview.contrib.database.models import HyperviewTemplate
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings

from todo.models import Category, Task

pytestmark = pytest.mark.django_db


@override_settings(DEBUG=True)
def test_seed_demo_creates_isolated_admin_and_user_data_with_local_defaults(
    monkeypatch,
):
    monkeypatch.delenv("HYPERTODO_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("HYPERTODO_DEMO_PASSWORD", raising=False)

    call_command("seed_demo")
    call_command("seed_demo")

    admin = get_user_model().objects.get(username="admin")
    demo = get_user_model().objects.get(username="demo")
    assert admin.check_password("admin123")
    assert admin.is_staff is True
    assert admin.is_superuser is True
    assert demo.check_password("demo123")
    assert demo.is_staff is False
    assert demo.is_superuser is False
    assert Category.objects.filter(user=admin).count() == 3
    assert Task.objects.filter(user=admin).count() == 4
    assert Category.objects.filter(user=demo).count() == 4
    assert Task.objects.filter(user=demo).count() == 5
    assert not Task.objects.filter(user=admin, category__user=demo).exists()
    assert not Task.objects.filter(user=demo, category__user=admin).exists()
    expected_templates = {
        "screens/about.xml",
        "screens/categories.xml",
        "fragments/category_list.xml",
    }
    assert set(HyperviewTemplate.objects.values_list("name", flat=True)) == (
        expected_templates
    )
    assert not HyperviewTemplate.objects.exclude(revision=1).exists()
    for template in HyperviewTemplate.objects.all():
        source = settings.BASE_DIR / "hyperview" / template.name
        assert template.active is True
        assert template.content == source.read_text(encoding="utf-8")


def test_seed_demo_allows_credentials_and_usernames_to_be_overridden(monkeypatch):
    monkeypatch.setenv("HYPERTODO_ADMIN_PASSWORD", "private-admin-password")
    monkeypatch.setenv("HYPERTODO_DEMO_PASSWORD", "private-demo-password")

    call_command("seed_demo", admin_username="owner", username="reader")

    admin = get_user_model().objects.get(username="owner")
    demo = get_user_model().objects.get(username="reader")
    assert admin.check_password("private-admin-password")
    assert demo.check_password("private-demo-password")


@override_settings(DEBUG=False)
def test_seed_demo_requires_explicit_passwords_outside_debug(monkeypatch):
    monkeypatch.delenv("HYPERTODO_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("HYPERTODO_DEMO_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="password environment variables"):
        call_command("seed_demo")
