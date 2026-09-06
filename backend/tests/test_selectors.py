"""Tests for task selection and dashboard counts."""

from datetime import timedelta

import pytest
from django.utils import timezone

from todo.models import Category, Task
from todo.selectors import dashboard_counts, tasks_for_user

pytestmark = pytest.mark.django_db


def test_task_filters_are_composable_and_user_isolated(user, other_user):
    now = timezone.now()
    today_due = timezone.localtime(now).replace(
        hour=23, minute=59, second=59, microsecond=0
    )
    category = Category.objects.create(
        user=user, name="Work", color=Category.Color.LAVENDER
    )
    active = Task.objects.create(user=user, category=category, title="Active")
    completed = Task.objects.create(
        user=user, category=category, title="Done", completed_at=now
    )
    today = Task.objects.create(
        user=user, title="Today", due_at=today_due
    )
    scheduled = Task.objects.create(
        user=user, title="Later", due_at=now + timedelta(days=3)
    )
    overdue = Task.objects.create(
        user=user, title="Late", due_at=now - timedelta(days=1)
    )
    Task.objects.create(user=other_user, title="Hidden")

    assert set(tasks_for_user(user, status="active")) == {
        active,
        today,
        scheduled,
        overdue,
    }
    assert list(tasks_for_user(user, status="completed")) == [completed]
    assert list(tasks_for_user(user, status="today")) == [today]
    assert list(tasks_for_user(user, status="scheduled")) == [scheduled]
    assert list(tasks_for_user(user, status="overdue")) == [overdue]
    assert set(tasks_for_user(user, category=category)) == {active, completed}


def test_dashboard_counts_describe_private_work(user, other_user):
    now = timezone.now()
    today_due = timezone.localtime(now).replace(
        hour=23, minute=59, second=59, microsecond=0
    )
    Task.objects.create(user=user, title="Today", due_at=today_due)
    Task.objects.create(user=user, title="Later", due_at=now + timedelta(days=2))
    Task.objects.create(user=user, title="Late", due_at=now - timedelta(hours=1))
    Task.objects.create(user=user, title="Done", completed_at=now)
    Task.objects.create(user=other_user, title="Hidden")

    assert dashboard_counts(user) == {
        "today": 2,
        "scheduled": 1,
        "all": 4,
        "overdue": 1,
    }


def test_selector_rejects_invalid_status_and_foreign_category(user, other_user):
    foreign = Category.objects.create(
        user=other_user, name="Foreign", color=Category.Color.PINK
    )
    with pytest.raises(ValueError, match="Unsupported"):
        tasks_for_user(user, status="missing")
    with pytest.raises(ValueError, match="belong"):
        tasks_for_user(user, category=foreign)
