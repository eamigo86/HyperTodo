"""Tests for TODO persistence rules."""

import importlib
from datetime import date, datetime, time
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
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


def test_a_new_task_has_a_timed_deadline_unless_told_otherwise(user):
    assert Task.objects.create(user=user, title="Call").due_all_day is False


# --- all-day data migration ---------------------------------------------------


def local(day, at):
    """Return an aware datetime on a local calendar day."""
    return timezone.make_aware(datetime.combine(day, at))


def wall_clock(value):
    """Return the local wall-clock reading of a stored deadline."""
    return timezone.localtime(value).replace(tzinfo=None)


def migration():
    return importlib.import_module("todo.migrations.0007_mark_all_day_deadlines")


def run_forwards():
    migration().mark_midnight_deadlines_all_day(
        apps, SimpleNamespace(connection=connection)
    )


def run_backwards():
    migration().restore_midnight_deadlines(apps, SimpleNamespace(connection=connection))


def test_the_migration_turns_deadlines_at_local_midnight_into_all_day_ones(
    user, other_user
):
    midnight = Task.objects.create(
        user=user, title="Rent", due_at=local(date(2026, 9, 6), time.min)
    )
    foreign = Task.objects.create(
        user=other_user, title="Rent", due_at=local(date(2026, 9, 7), time.min)
    )
    timed = Task.objects.create(
        user=user, title="Call", due_at=local(date(2026, 9, 6), time(9, 30))
    )
    one_minute = Task.objects.create(
        user=user, title="Almost", due_at=local(date(2026, 9, 6), time(0, 1))
    )
    undated = Task.objects.create(user=user, title="Someday")

    run_forwards()

    for task in (midnight, foreign, timed, one_minute, undated):
        task.refresh_from_db()
    assert (midnight.due_all_day, foreign.due_all_day) == (True, True)
    assert wall_clock(midnight.due_at) == datetime.combine(date(2026, 9, 6), time.max)
    assert wall_clock(foreign.due_at) == datetime.combine(date(2026, 9, 7), time.max)
    assert [timed.due_all_day, one_minute.due_all_day, undated.due_all_day] == [
        False
    ] * 3
    assert wall_clock(timed.due_at) == datetime(2026, 9, 6, 9, 30)
    assert wall_clock(one_minute.due_at) == datetime(2026, 9, 6, 0, 1)
    assert undated.due_at is None


def test_the_migration_keeps_the_day_when_the_clocks_change(user):
    # New York springs forward on 2026-03-08, so that local day is 23 hours long. A
    # deadline moved by a fixed 24 hours would land an hour into the NEXT day.
    spring = Task.objects.create(
        user=user, title="Spring", due_at=local(date(2026, 3, 8), time.min)
    )
    autumn = Task.objects.create(
        user=user, title="Autumn", due_at=local(date(2026, 11, 1), time.min)
    )

    run_forwards()

    spring.refresh_from_db()
    autumn.refresh_from_db()
    assert wall_clock(spring.due_at) == datetime.combine(date(2026, 3, 8), time.max)
    assert wall_clock(autumn.due_at) == datetime.combine(date(2026, 11, 1), time.max)


def test_the_migration_can_run_twice(user):
    task = Task.objects.create(
        user=user, title="Rent", due_at=local(date(2026, 9, 6), time.min)
    )

    run_forwards()
    first = Task.objects.get(pk=task.pk).due_at
    run_forwards()

    assert Task.objects.get(pk=task.pk).due_at == first


def test_the_migration_reads_tasks_in_primary_key_chunks(user, monkeypatch):
    monkeypatch.setattr(migration(), "CHUNK", 2)
    tasks = [
        Task.objects.create(
            user=user, title=f"Task {n}", due_at=local(date(2026, 9, 1 + n), time.min)
        )
        for n in range(5)
    ]

    with CaptureQueriesContext(connection) as captured:
        run_forwards()

    # Rows on both sides of every chunk boundary are converted...
    assert all(Task.objects.get(pk=task.pk).due_all_day for task in tasks)
    # ...and no read ever asks for more than one chunk of them.
    reads = [
        query["sql"]
        for query in captured
        if query["sql"].startswith("SELECT") and 'FROM "todo_task"' in query["sql"]
    ]
    assert len(reads) > 1
    assert all("LIMIT 2" in sql for sql in reads)


def test_reversing_the_migration_restores_the_start_of_the_day(user):
    task = Task.objects.create(
        user=user,
        title="Rent",
        due_at=local(date(2026, 9, 6), time.max),
        due_all_day=True,
    )
    timed = Task.objects.create(
        user=user, title="Call", due_at=local(date(2026, 9, 6), time(9, 30))
    )
    no_deadline = Task.objects.create(user=user, title="Someday", due_all_day=True)

    run_backwards()

    task.refresh_from_db()
    timed.refresh_from_db()
    no_deadline.refresh_from_db()
    assert wall_clock(task.due_at) == datetime.combine(date(2026, 9, 6), time.min)
    assert wall_clock(timed.due_at) == datetime(2026, 9, 6, 9, 30)
    assert no_deadline.due_at is None
