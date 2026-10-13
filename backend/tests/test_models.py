"""Tests for TODO persistence rules."""

import importlib
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from todo.forms import TaskForm
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
    # The flag goes with the end of the day. Left on, the forward migration, which only
    # reads unflagged rows, would skip this one and keep a flagged deadline at 00:00.
    assert task.due_all_day is False
    assert wall_clock(timed.due_at) == datetime(2026, 9, 6, 9, 30)
    assert no_deadline.due_at is None
    # A flag with no deadline behind it is not a row the migration ever moved.
    assert no_deadline.due_all_day is True


def test_reversing_keeps_the_flag_where_a_clock_change_swallows_midnight(
    user, settings
):
    # Cairo goes from 00:00 straight to 01:00 on 2026-04-24, so that day has no start.
    # Rebuilt at 00:00 the deadline reads 01:00, the forward migration (which only
    # moves rows at midnight) never picks it up again, and the flag was lost for good.
    settings.TIME_ZONE = "Africa/Cairo"
    gap = Task.objects.create(
        user=user,
        title="Gap",
        due_at=local(date(2026, 4, 24), time.max),
        due_all_day=True,
    )
    ordinary = Task.objects.create(
        user=user,
        title="Ordinary",
        due_at=local(date(2026, 4, 25), time.max),
        due_all_day=True,
    )

    run_backwards()

    gap.refresh_from_db()
    ordinary.refresh_from_db()
    assert (gap.due_all_day, wall_clock(gap.due_at)) == (
        True,
        datetime.combine(date(2026, 4, 24), time.max),
    )
    assert (ordinary.due_all_day, wall_clock(ordinary.due_at)) == (
        False,
        datetime.combine(date(2026, 4, 25), time.min),
    )
    run_forwards()
    gap.refresh_from_db()
    assert wall_clock(gap.due_at) == datetime.combine(date(2026, 4, 24), time.max)


def test_running_forwards_again_after_reversing_gives_back_the_same_rows(user):
    # 0007 -> 0006 -> 0007 has to be exact, for the rows the migration moved and for
    # those the task form stored itself (the last instant of the day, already flagged).
    Task.objects.create(
        user=user, title="Rent", due_at=local(date(2026, 9, 6), time.min)
    )
    Task.objects.create(
        user=user,
        title="Form",
        due_at=local(date(2026, 9, 8), time.max),
        due_all_day=True,
    )
    Task.objects.create(
        user=user, title="Spring", due_at=local(date(2026, 3, 8), time.min)
    )
    Task.objects.create(
        user=user, title="Call", due_at=local(date(2026, 9, 6), time(9, 30))
    )
    Task.objects.create(user=user, title="Someday")

    def rows():
        return list(
            Task.objects.order_by("pk").values_list("pk", "due_at", "due_all_day")
        )

    run_forwards()
    migrated = rows()
    run_backwards()
    assert rows() != migrated
    run_forwards()

    assert rows() == migrated


# --- deadlines at the ends of the calendar ---------------------------------------


def test_a_deadline_too_close_to_year_9999_stays_timed_instead_of_aborting(user):
    # 9999-12-31 00:00 in New York is a legal stored value, but the last instant of
    # that day is in year 10000 once converted to UTC. The update raised OverflowError,
    # so the whole migration rolled back and `migrate` stayed at 0006.
    forever = Task.objects.create(
        user=user, title="Forever", due_at=local(date(9999, 12, 31), time.min)
    )
    ordinary = Task.objects.create(
        user=user, title="Rent", due_at=local(date(2026, 9, 6), time.min)
    )
    before = forever.due_at

    run_forwards()

    forever.refresh_from_db()
    ordinary.refresh_from_db()
    assert (forever.due_all_day, forever.due_at) == (False, before)
    assert ordinary.due_all_day is True


def test_a_deadline_at_the_first_instant_of_year_1_stays_timed_instead_of_aborting(
    user,
):
    # SQLite converts every row to local time to test its time of day, and the first
    # instant of year 1 has no reading west of Greenwich: that query failed with a
    # DataError before a single row was moved.
    first = datetime(1, 1, 1, tzinfo=UTC)
    task = Task.objects.create(user=user, title="Epoch", due_at=first)

    run_forwards()

    task.refresh_from_db()
    assert (task.due_all_day, task.due_at) == (False, first)


def test_the_year_9999_bound_is_exact(user):
    # Midnight on the last day of 9998 still has a UTC end of day; midnight on the
    # first day of 9999 is where the migration stops converting.
    inside = Task.objects.create(
        user=user, title="Inside", due_at=local(date(9998, 12, 31), time.min)
    )
    outside = Task.objects.create(
        user=user, title="Outside", due_at=local(date(9999, 1, 1), time.min)
    )

    run_forwards()

    inside.refresh_from_db()
    outside.refresh_from_db()
    assert inside.due_all_day is True
    assert wall_clock(inside.due_at) == datetime.combine(date(9998, 12, 31), time.max)
    assert outside.due_all_day is False


def test_reversing_skips_a_row_it_cannot_read_in_local_time_as_well(user):
    # An all-day flag set by hand on a row at the very start of the calendar, through
    # the Admin, must not abort the way back: it has no local reading west of Greenwich.
    first = datetime(1, 1, 1, tzinfo=UTC)
    task = Task.objects.create(user=user, title="Epoch", due_at=first, due_all_day=True)

    run_backwards()

    task.refresh_from_db()
    assert task.due_at == first


def test_the_migration_reverses_with_the_real_restore_function():
    operation = migration().Migration.operations[0]

    assert operation.code is migration().mark_midnight_deadlines_all_day
    # RunPython.noop here would let a rollback keep every end-of-day deadline.
    assert operation.reverse_code is migration().restore_midnight_deadlines


@pytest.mark.django_db(transaction=True)
def test_migrate_converts_forwards_and_restores_backwards_the_way_it_really_runs(user):
    before = ("todo", "0006_task_due_all_day")
    after = ("todo", "0007_mark_all_day_deadlines")
    legacy = Task.objects.create(
        user=user, title="Rent", due_at=local(date(2026, 9, 6), time.min)
    )
    from_form = Task.objects.create(
        user=user,
        title="Form",
        due_at=local(date(2026, 9, 8), time.max),
        due_all_day=True,
    )
    forever = Task.objects.create(
        user=user, title="Forever", due_at=local(date(9999, 12, 31), time.min)
    )
    untouched = forever.due_at

    def migrate_to(target):
        MigrationExecutor(connection).migrate([target])
        legacy.refresh_from_db()
        from_form.refresh_from_db()
        forever.refresh_from_db()

    def state():
        return [
            (task.due_all_day, task.due_at) for task in (legacy, from_form, forever)
        ]

    try:
        migrate_to(before)
        # `migrate todo 0007` itself, over a table holding a row it cannot convert.
        migrate_to(after)
        assert legacy.due_all_day is True
        assert wall_clock(legacy.due_at) == datetime.combine(date(2026, 9, 6), time.max)
        assert (forever.due_all_day, forever.due_at) == (False, untouched)
        migrated = state()

        # And `migrate todo 0006`: the end of the day goes back to its start, unflagged.
        migrate_to(before)
        assert wall_clock(legacy.due_at) == datetime.combine(date(2026, 9, 6), time.min)
        assert wall_clock(from_form.due_at) == datetime.combine(
            date(2026, 9, 8), time.min
        )
        assert (legacy.due_all_day, from_form.due_all_day) == (False, False)
        assert forever.due_at == untouched

        # Forwards again lands on exactly the rows it produced the first time.
        migrate_to(after)
        assert state() == migrated
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())


def test_reversing_keeps_the_flag_where_the_start_would_fall_below_year_1(
    user, settings
):
    # The end of 0001-01-01 in New York is 0001-01-02 04:56 UTC, so the row is read,
    # but its day starts at 0001-01-01 04:56 UTC: below what the forward migration
    # reads. Unflagged there, the row would never be flagged again.
    settings.TIME_ZONE = "America/New_York"
    end = local(date(1, 1, 1), time.max)
    task = Task.objects.create(user=user, title="Epoch", due_at=end, due_all_day=True)

    run_backwards()

    task.refresh_from_db()
    assert (task.due_all_day, task.due_at) == (True, end)
    run_forwards()
    task.refresh_from_db()
    assert (task.due_all_day, task.due_at) == (True, end)


# --- the end of a day when the clocks change -------------------------------------


@pytest.mark.parametrize(
    ("zone", "day"),
    [
        ("America/Santiago", date(2026, 4, 4)),
        ("Africa/Cairo", date(2026, 10, 29)),
        ("Asia/Beirut", date(2026, 10, 24)),
        ("America/Nuuk", date(2026, 10, 24)),
        ("America/Nuuk", date(2026, 3, 28)),
        ("America/Havana", date(2026, 11, 1)),
        ("America/New_York", date(2026, 11, 1)),
    ],
    ids=[
        "santiago",
        "cairo",
        "beirut",
        "nuuk-repeats-23h",
        "nuuk-skips-23h",
        "havana",
        "new-york",
    ],
)
def test_the_migration_ends_a_clock_change_day_where_the_task_form_does(
    user, settings, zone, day
):
    # Night of a repeated 23:xx hour (or a skipped one in Nuuk): the first reading of
    # 23:59:59 is an hour early, and the one a skipped hour leaves is an hour late.
    settings.TIME_ZONE = zone
    task = Task.objects.create(user=user, title="Rent", due_at=local(day, time.min))
    form = TaskForm(
        {"title": "Rent", "due_date": day.isoformat(), "due_time": ""}, user=user
    )
    assert form.is_valid(), form.errors
    # In UTC: Python will not call an instant in a repeated hour equal to the same
    # instant read in another zone.
    from_form = form.cleaned_data["due_at"].astimezone(UTC)
    zone_info = ZoneInfo(zone)

    run_forwards()
    task.refresh_from_db()

    assert task.due_all_day is True
    assert task.due_at == from_form
    # The last instant of the day: on it, and the next microsecond is on the next one.
    assert task.due_at.astimezone(zone_info).date() == day
    after = (task.due_at + timedelta(microseconds=1)).astimezone(zone_info)
    assert after.date() == day + timedelta(days=1)
    # Reversing and running forwards again gives the same instant.
    run_backwards()
    run_forwards()
    task.refresh_from_db()
    assert (task.due_all_day, task.due_at) == (True, from_form)
