"""Tests for TODO input validation."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from todo.forms import CategoryForm, LoginForm, TaskForm
from todo.models import Category, Task

pytestmark = pytest.mark.django_db


def test_login_form_accepts_expected_fields():
    form = LoginForm({"username": "ada", "password": "secret"})
    assert form.is_valid()


def test_category_form_normalizes_name_and_palette(user):
    form = CategoryForm({"name": "  Work  ", "color": Category.Color.MINT}, user=user)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["name"] == "Work"


def test_category_form_rejects_case_insensitive_duplicate(user):
    Category.objects.create(user=user, name="Work", color=Category.Color.MINT)
    form = CategoryForm({"name": " work ", "color": Category.Color.PINK}, user=user)
    assert not form.is_valid()
    assert "already exists" in form.errors["name"][0]


def test_task_form_combines_date_and_time_in_current_timezone(user):
    form = TaskForm(
        {
            "title": "Plan",
            "notes": "Details",
            "due_date": "2026-09-06",
            "due_time": "14:30",
            "category": "",
        },
        user=user,
    )
    assert form.is_valid(), form.errors
    due_at = form.cleaned_data["due_at"]
    assert timezone.is_aware(due_at)
    assert timezone.localtime(due_at).replace(tzinfo=None) == datetime(
        2026, 9, 6, 14, 30
    )


def test_task_form_requires_date_when_time_is_present(user):
    form = TaskForm(
        {"title": "Plan", "due_date": "", "due_time": "14:30", "category": ""},
        user=user,
    )
    assert not form.is_valid()
    assert "date" in form.errors["due_time"][0].lower()


def test_an_unreadable_date_is_not_also_reported_as_missing(user):
    form = TaskForm(
        {"title": "Plan", "due_date": "next friday", "due_time": "14:30"}, user=user
    )

    assert not form.is_valid()
    assert list(form.errors) == ["due_date"]


def test_task_form_limits_categories_to_current_user(user, other_user):
    own = Category.objects.create(user=user, name="Own", color=Category.Color.MINT)
    foreign = Category.objects.create(
        user=other_user, name="Foreign", color=Category.Color.PINK
    )
    form = TaskForm(user=user)
    assert list(form.fields["category"].queryset) == [own]
    bound = TaskForm({"title": "Nope", "category": foreign.pk}, user=user)
    assert not bound.is_valid()


def test_bound_existing_category_excludes_itself_from_duplicate_check(user):
    category = Category.objects.create(
        user=user, name="Work", color=Category.Color.MINT
    )
    form = CategoryForm(
        {"name": "work", "color": Category.Color.GREEN}, user=user, instance=category
    )
    assert form.is_valid(), form.errors


def test_unbound_existing_task_splits_its_deadline(user):
    task = Task.objects.create(
        user=user,
        title="Timed",
        due_at=timezone.make_aware(datetime(2026, 9, 6, 14, 30)),
    )
    form = TaskForm(user=user, instance=task)
    assert form.initial["due_date"].isoformat() == "2026-09-06"
    assert form.initial["due_time"].strftime("%H:%M") == "14:30"


def wall_clock(due_at):
    """Return the local wall-clock reading of a stored deadline."""
    return timezone.localtime(due_at).replace(tzinfo=None)


def test_a_date_without_a_time_is_due_until_the_end_of_that_day(user):
    form = TaskForm(
        {"title": "Pay rent", "due_date": "2026-09-06", "due_time": ""}, user=user
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["due_all_day"] is True
    # The last instant of the day, not midnight at its start: a deadline that is a
    # day and not a moment must not be overdue while that day is still going.
    assert wall_clock(form.cleaned_data["due_at"]) == datetime.combine(
        date(2026, 9, 6), time.max
    )


@pytest.mark.parametrize("due_time", ["14:30", "00:00", "23:59"])
def test_a_date_with_a_time_is_a_timed_deadline_even_at_midnight(user, due_time):
    form = TaskForm(
        {"title": "Call", "due_date": "2026-09-06", "due_time": due_time}, user=user
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["due_all_day"] is False
    assert wall_clock(form.cleaned_data["due_at"]) == datetime.combine(
        date(2026, 9, 6), time.fromisoformat(due_time)
    )


def test_no_date_means_no_deadline_at_all(user):
    form = TaskForm({"title": "Someday", "due_date": "", "due_time": ""}, user=user)

    assert form.is_valid(), form.errors
    assert form.cleaned_data["due_at"] is None
    assert form.cleaned_data["due_all_day"] is False


def test_an_all_day_task_is_edited_with_an_empty_time(user):
    task = Task.objects.create(
        user=user,
        title="Pay rent",
        due_at=timezone.make_aware(datetime.combine(date(2026, 9, 6), time.max)),
        due_all_day=True,
    )

    form = TaskForm(user=user, instance=task)

    assert form.initial["due_date"].isoformat() == "2026-09-06"
    assert form.initial.get("due_time") is None


# --- editing a deadline from another zone ---------------------------------------

NEW_YORK = ZoneInfo("America/New_York")
MADRID = ZoneInfo("Europe/Madrid")
SANTIAGO = ZoneInfo("America/Santiago")


def posted_back(task, user, **changes):
    """Return what a client posts after the edit form showed this task, changed."""
    shown = TaskForm(instance=task, user=user).initial
    due_time = shown.get("due_time")
    return {
        "title": task.title,
        "due_date": shown["due_date"].isoformat(),
        "due_time": "" if due_time is None else due_time.strftime("%H:%M"),
        **changes,
    }


def edited_in(zone, task, user, **changes):
    """Edit the task as it is shown in another zone and return the valid form."""
    with timezone.override(zone):
        form = TaskForm(posted_back(task, user, **changes), instance=task, user=user)
        assert form.is_valid(), form.errors
    return form


# Stored while someone in New York, or Santiago, chose it; edited from elsewhere.
NY_ALL_DAY = datetime(2026, 6, 11, 3, 59, 59, 999999, tzinfo=UTC)
SANTIAGO_SECOND_2330 = datetime(2026, 4, 5, 3, 30, tzinfo=UTC)
SANTIAGO_SECOND_END = datetime(2026, 4, 5, 3, 59, 59, 999999, tzinfo=UTC)
MADRID_WITH_SECONDS = datetime(2026, 9, 6, 7, 30, 45, tzinfo=UTC)


@pytest.mark.parametrize(
    ("stored", "all_day", "zone"),
    [
        (NY_ALL_DAY, True, MADRID),
        (NY_ALL_DAY, True, NEW_YORK),
        (SANTIAGO_SECOND_END, True, SANTIAGO),
        (SANTIAGO_SECOND_END, True, MADRID),
        # 23:30 happens twice in Santiago that night; the second one is stored.
        (SANTIAGO_SECOND_2330, False, SANTIAGO),
        (datetime(2026, 9, 6, 13, 30, tzinfo=UTC), False, MADRID),
        # A time with seconds is shown to the minute and must not lose them.
        (MADRID_WITH_SECONDS, False, MADRID),
    ],
    ids=[
        "all-day-new-york-seen-from-madrid",
        "all-day-new-york-at-home",
        "all-day-santiago-at-home",
        "all-day-santiago-seen-from-madrid",
        "timed-in-the-repeated-hour",
        "timed-seen-from-madrid",
        "timed-with-seconds",
    ],
)
def test_a_title_only_edit_keeps_the_stored_deadline_exactly(
    user, stored, all_day, zone
):
    task = Task.objects.create(
        user=user, title="Pay rent", due_at=stored, due_all_day=all_day
    )

    form = edited_in(zone, task, user, title="Pay rent now")

    assert form.cleaned_data["due_at"] == stored
    assert form.cleaned_data["due_all_day"] is all_day


def test_a_new_date_on_an_all_day_task_ends_that_day_in_the_active_zone(user):
    task = Task.objects.create(
        user=user, title="Pay rent", due_at=NY_ALL_DAY, due_all_day=True
    )

    # Madrid shows the 11th for this deadline; picking the 12th must move it.
    form = edited_in(MADRID, task, user, due_date="2026-06-12")

    assert form.cleaned_data["due_all_day"] is True
    assert form.cleaned_data["due_at"] == datetime(
        2026, 6, 12, 21, 59, 59, 999999, tzinfo=UTC
    )


def test_a_time_added_to_an_all_day_task_makes_it_a_timed_one(user):
    task = Task.objects.create(
        user=user, title="Pay rent", due_at=NY_ALL_DAY, due_all_day=True
    )

    form = edited_in(MADRID, task, user, due_time="09:00")

    assert form.cleaned_data["due_all_day"] is False
    assert form.cleaned_data["due_at"] == datetime(2026, 6, 11, 7, 0, tzinfo=UTC)


def test_only_the_time_changed_moves_a_timed_deadline(user):
    task = Task.objects.create(
        user=user,
        title="Call",
        due_at=datetime(2026, 9, 6, 13, 30, tzinfo=UTC),
        due_all_day=False,
    )

    form = edited_in(MADRID, task, user, due_time="16:45")

    assert form.cleaned_data["due_all_day"] is False
    assert form.cleaned_data["due_at"] == datetime(2026, 9, 6, 14, 45, tzinfo=UTC)


def test_clearing_the_time_of_a_timed_task_makes_it_an_all_day_one(user):
    task = Task.objects.create(
        user=user,
        title="Call",
        due_at=datetime(2026, 9, 6, 13, 30, tzinfo=UTC),
        due_all_day=False,
    )

    form = edited_in(MADRID, task, user, due_time="")

    assert form.cleaned_data["due_all_day"] is True
    assert form.cleaned_data["due_at"] == datetime(
        2026, 9, 6, 21, 59, 59, 999999, tzinfo=UTC
    )


def test_clearing_the_date_removes_the_deadline(user):
    task = Task.objects.create(
        user=user, title="Pay rent", due_at=NY_ALL_DAY, due_all_day=True
    )

    form = edited_in(MADRID, task, user, due_date="")

    assert form.cleaned_data["due_at"] is None
    assert form.cleaned_data["due_all_day"] is False


def test_a_new_task_keeps_its_deadline_whatever_the_posted_shown_values_say(user):
    # An unsaved task already has a primary key (the id has a default), so a guard on
    # "has a key" would take the deadline for an unchanged one and drop it.
    form = TaskForm(
        {
            "title": "Plan",
            "due_date": "2026-09-06",
            "due_time": "14:30",
            "due_date_shown": "2026-09-06",
            "due_time_shown": "14:30",
        },
        user=user,
    )

    assert form.is_valid(), form.errors
    assert wall_clock(form.cleaned_data["due_at"]) == datetime(2026, 9, 6, 14, 30)


# --- the last instant of a day when the clocks change ---------------------------

# Nights when 23:xx happens twice, and one night when it never happens at all.
CLOCK_CHANGE_DAYS = [
    pytest.param("America/Santiago", date(2026, 4, 4), id="santiago-repeats-23h"),
    pytest.param("Africa/Cairo", date(2026, 10, 29), id="cairo-repeats-23h"),
    pytest.param("Asia/Beirut", date(2026, 10, 24), id="beirut-repeats-23h"),
    pytest.param("America/Nuuk", date(2026, 10, 24), id="nuuk-repeats-23h"),
    pytest.param("America/Nuuk", date(2026, 3, 28), id="nuuk-skips-23h"),
    pytest.param("America/New_York", date(2026, 11, 1), id="new-york-ordinary"),
]


def end_of_day_for(zone, day, user):
    """Return, in UTC, the deadline the form stores for a date posted with no time.

    In UTC because Python refuses to call an instant in a repeated hour equal to the
    same instant read in another zone.
    """
    with timezone.override(ZoneInfo(zone)):
        form = TaskForm(
            {"title": "Pay rent", "due_date": day.isoformat(), "due_time": ""},
            user=user,
        )
        assert form.is_valid(), form.errors
    return form.cleaned_data["due_at"].astimezone(UTC)


@pytest.mark.parametrize(("zone", "day"), CLOCK_CHANGE_DAYS)
def test_a_date_only_deadline_is_the_very_last_instant_of_its_day(user, zone, day):
    instant = end_of_day_for(zone, day, user)

    # On that day, and the next microsecond is already on the following one: not an
    # hour early (the first of two 23:59:59), not an hour late (the next day).
    assert instant.astimezone(ZoneInfo(zone)).date() == day
    after = (instant + timedelta(microseconds=1)).astimezone(ZoneInfo(zone))
    assert after.date() == day + timedelta(days=1)


def test_the_last_instant_of_a_repeated_hour_night_is_the_second_midnight_side(user):
    # Santiago turns its clocks back at midnight, so 23:xx on the 4th happens twice and
    # the day ends with the second one, at 03:59:59 UTC.
    assert end_of_day_for("America/Santiago", date(2026, 4, 4), user) == datetime(
        2026, 4, 5, 3, 59, 59, 999999, tzinfo=UTC
    )


def test_a_day_that_skips_its_last_hour_ends_where_the_clocks_jump(user):
    # Nuuk goes from 22:59:59 straight to 00:00 on the 29th: the 28th ends at 22:59:59.
    assert end_of_day_for("America/Nuuk", date(2026, 3, 28), user) == datetime(
        2026, 3, 29, 0, 59, 59, 999999, tzinfo=UTC
    )


def test_an_all_day_task_keeps_its_day_through_the_edit_form_when_an_hour_is_skipped(
    user,
):
    task = Task.objects.create(
        user=user,
        title="Pay rent",
        due_at=end_of_day_for("America/Nuuk", date(2026, 3, 28), user),
        due_all_day=True,
    )
    task.refresh_from_db()

    form = edited_in(ZoneInfo("America/Nuuk"), task, user, title="Pay rent now")

    # The form shows the day the deadline was set for, and saves it back unchanged.
    with timezone.override(ZoneInfo("America/Nuuk")):
        assert TaskForm(instance=task, user=user).initial["due_date"] == date(
            2026, 3, 28
        )
    assert form.cleaned_data["due_at"] == task.due_at
