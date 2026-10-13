"""Tests for TODO input validation."""

from datetime import date, datetime, time

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
