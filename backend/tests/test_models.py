"""Tests for TODO persistence rules."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from todo.models import Category, Task

pytestmark = pytest.mark.django_db


def test_category_has_uuid_palette_and_user_scoped_case_insensitive_name(
    user, other_user
):
    category = Category.objects.create(
        user=user, name="Work", color=Category.Color.LAVENDER
    )
    assert str(category) == "Work"
    assert category.pk.version == 4
    Category.objects.create(user=other_user, name="work", color=Category.Color.MINT)
    with pytest.raises(IntegrityError), transaction.atomic():
        Category.objects.create(user=user, name="work", color=Category.Color.PINK)


def test_task_defaults_to_active_and_category_deletion_keeps_task(user):
    category = Category.objects.create(
        user=user, name="Home", color=Category.Color.YELLOW
    )
    task = Task.objects.create(user=user, category=category, title="Buy milk")
    assert str(task) == "Buy milk"
    assert task.is_completed is False
    category.delete()
    task.refresh_from_db()
    assert task.category is None


def test_task_completion_property(user):
    task = Task.objects.create(
        user=user, title="Ship release", completed_at=timezone.now()
    )
    assert task.is_completed is True


def test_task_rejects_category_owned_by_another_user(user, other_user):
    category = Category.objects.create(
        user=other_user, name="Private", color=Category.Color.GREEN
    )
    task = Task(user=user, category=category, title="Invalid")
    with pytest.raises(ValidationError, match="same user"):
        task.clean()


def test_a_user_without_a_profile_row_resolves_to_none(user):
    # The whole preference stack leans on this: RelatedObjectDoesNotExist inherits
    # from AttributeError, so getattr swallows it and every pre-migration account
    # falls through to the defaults instead of raising on the dashboard.
    assert getattr(user, "profile", None) is None

    from django.contrib.auth.models import AnonymousUser

    assert getattr(AnonymousUser(), "profile", None) is None


def test_a_new_profile_states_no_preference_at_all(user):
    # Three preferences share ONE row, so a non-empty default on any field would be
    # written the moment a sibling field is set. A Spanish phone that switches to
    # dark mode must not silently acquire language="en".
    from todo.models import Profile

    profile = Profile.objects.create(user=user)

    assert (profile.theme, profile.language) == ("", "")
    assert profile.avatar.name in ("", None)


def test_one_user_cannot_hold_two_profiles(user):
    from todo.models import Profile

    Profile.objects.create(user=user)
    with pytest.raises(IntegrityError), transaction.atomic():
        Profile.objects.create(user=user)


def test_a_profile_names_the_user_it_belongs_to(user):
    from todo.models import Profile

    assert str(Profile.objects.create(user=user)) == f"Preferences for {user}"
