"""Profile presentation changes are owner-private; auth-only writes stay silent."""

import json

import pytest
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from tests.test_realtime_changes import module, request
from tests.test_realtime_notifications import intents
from tests.test_realtime_notifications import published as published
from todo.models import Profile
from todo.services import update_profile

pytestmark = pytest.mark.django_db


def test_profile_edit_captures_origin_and_only_owner_topic(
    user, published, django_capture_on_commit_callbacks
):
    from todo.realtime_notifications import private_topic

    with django_capture_on_commit_callbacks(execute=True):
        with module().mutation_context(request()):
            update_profile(
                user=user,
                first_name="Edited",
                last_name="Fixture",
                email="fixture@example.invalid",
            )
        assert not published
    event = intents(published)[0]
    assert event.topics == (private_topic("default", user.pk),)
    assert event.resources == ("ui",)
    assert event.payload["mutation_id"] == "a" * 32 + "00000001"
    assert (
        event.payload["entities"]
        == module().capture_entities("default", [("ui", user.pk)]).payload
    )
    assert "Edited" not in repr(event) and "example.invalid" not in repr(event)


@pytest.mark.parametrize(
    "field,value",
    [("theme", "dark"), ("language", "es"), ("avatar", "avatars/fixture.png")],
)
def test_new_and_changed_preferences_emit_scoped_ui(
    user, published, django_capture_on_commit_callbacks, field, value
):
    with django_capture_on_commit_callbacks(execute=True):
        profile = Profile.objects.create(user=user, **{field: value})
    assert len(published) == 1 and intents(published)[0].resources == ("ui",)
    with django_capture_on_commit_callbacks(execute=True):
        setattr(profile, field, "")
        profile.save(update_fields=[field])
    assert len(published) == 2


def test_auth_only_and_noop_user_writes_never_emit_ui(
    user, published, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])
        user.set_password("new-fixture-password")
        user.save(update_fields=["password"])
        user.email = "not-written@example.invalid"
        user.save(update_fields=["last_login"])
        user.refresh_from_db()
        user.save()
    assert not published


def test_admin_style_user_save_observed_without_request_origin(
    user, published, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        user.first_name = "Admin edit"
        user.save()
    assert len(published) == 1 and intents(published)[0].payload["mutation_id"] is None


def test_real_user_admin_save_matches_the_current_settings_dependency(
    user, client, admin_client, published, django_capture_on_commit_callbacks
):
    from tests.test_realtime_change_templates import NS, get
    from todo.realtime_notifications import private_topic

    client.force_login(user)
    _, screen = get(client, "/hv/settings/")
    boundary = screen.find(".//app:realtime", NS)
    assert boundary.attrib["mode"] == "form"
    assert boundary.attrib["resources"] == "ui"
    published.clear()
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            reverse("admin:auth_user_change", args=[user.pk]),
            {
                "username": user.username,
                "first_name": "Admin first",
                "last_name": "Admin last",
                "email": user.email,
                "is_active": "on",
                "date_joined_0": user.date_joined.strftime("%Y-%m-%d"),
                "date_joined_1": user.date_joined.strftime("%H:%M:%S"),
                "_save": "Save",
            },
        )
        assert response.status_code == 302
        assert published == []
    user.refresh_from_db()
    assert (user.first_name, user.last_name) == ("Admin first", "Admin last")
    assert len(published) == 1
    event = intents(published)[0]
    assert event.topics == (private_topic("default", user.pk),)
    assert event.payload["mutation_id"] is None
    assert event.resources == ("ui",)
    assert event.payload["entities"] == json.loads(boundary.attrib["entities"])


def test_blank_profile_noop_is_silent_but_deletion_of_preferences_notifies(
    user, published, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        profile = Profile.objects.create(user=user)
        profile.save()
    assert not published
    profile.theme = "dark"
    profile.save()
    with django_capture_on_commit_callbacks(execute=True):
        profile.delete()
    assert len(published) == 1


def test_profile_transfer_targets_both_owners_without_shared_ui_topic(
    user, other_user, published, django_capture_on_commit_callbacks
):
    from todo.realtime_notifications import private_topic

    profile = Profile.objects.create(user=user, theme="dark")
    with django_capture_on_commit_callbacks(execute=True):
        profile.user = other_user
        profile.save(update_fields=["user"])
    assert {intent.topics for intent in intents(published)} == {
        (private_topic("default", user.pk),),
        (private_topic("default", other_user.pk),),
    }
    for event in intents(published):
        assert len(event.payload["entities"]["items"]) == 1


def test_profile_rollback_drops_hint_and_bulk_update_stays_explicit(
    user, published, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            user.first_name = "Rolled back"
            user.save(update_fields=["first_name"])
            transaction.set_rollback(True)
        type(user).objects.filter(pk=user.pk).update(first_name="Bulk unobserved")
    assert not published
