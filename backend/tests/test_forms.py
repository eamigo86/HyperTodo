"""Tests for TODO input validation."""

from datetime import datetime

import pytest
from django.utils import timezone

from todo.forms import CategoryForm, LoginForm, TaskForm
from todo.models import Category

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
    from todo.models import Task

    task = Task.objects.create(
        user=user,
        title="Timed",
        due_at=timezone.make_aware(datetime(2026, 9, 6, 14, 30)),
    )
    form = TaskForm(user=user, instance=task)
    assert form.initial["due_date"].isoformat() == "2026-09-06"
    assert form.initial["due_time"].strftime("%H:%M") == "14:30"
