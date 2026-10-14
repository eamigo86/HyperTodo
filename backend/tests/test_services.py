"""Tests for TODO mutation services."""

from datetime import datetime, timedelta

import pytest
from django.http import Http404
from django.utils import timezone

from todo.models import Category, Task
from todo.services import (
    create_category,
    create_task,
    delete_category,
    delete_task,
    toggle_task,
    update_category,
    update_task,
)

pytestmark = pytest.mark.django_db


def test_category_lifecycle_is_owned(user, other_user):
    category = create_category(user=user, name="Work", color=Category.Color.LAVENDER)
    category = update_category(
        user=user, category_id=category.pk, name="Deep work", color=Category.Color.GREEN
    )
    assert (category.name, category.color) == ("Deep work", Category.Color.GREEN)
    with pytest.raises(Http404):
        update_category(
            user=other_user,
            category_id=category.pk,
            name="Stolen",
            color=Category.Color.PINK,
        )
    delete_category(user=user, category_id=category.pk)
    assert not Category.objects.filter(pk=category.pk).exists()


def test_task_lifecycle_and_toggle_are_owned(user, other_user):
    due_at = timezone.now() + timedelta(days=1)
    task = create_task(
        user=user, title="Write tests", notes="First", category=None, due_at=due_at
    )
    task = update_task(
        user=user,
        task_id=task.pk,
        title="Ship tests",
        notes="Done",
        category=None,
        due_at=None,
    )
    assert (task.title, task.notes, task.due_at) == ("Ship tests", "Done", None)
    task = toggle_task(user=user, task_id=task.pk)
    assert task.completed_at is not None
    task = toggle_task(user=user, task_id=task.pk)
    assert task.completed_at is None
    with pytest.raises(Http404):
        delete_task(user=other_user, task_id=task.pk)
    delete_task(user=user, task_id=task.pk)
    assert not Task.objects.filter(pk=task.pk).exists()


def test_the_all_day_flag_is_stored_and_replaced_with_the_deadline(user):
    due_at = timezone.make_aware(datetime(2026, 9, 6, 23, 59, 59, 999999))
    task = create_task(
        user=user,
        title="Pay rent",
        notes="",
        category=None,
        due_at=due_at,
        due_all_day=True,
    )
    task.refresh_from_db()
    assert task.due_all_day is True

    task = update_task(
        user=user,
        task_id=task.pk,
        title="Pay rent",
        notes="",
        category=None,
        due_at=timezone.make_aware(datetime(2026, 9, 7, 9, 0)),
    )
    task.refresh_from_db()
    # A replacement deadline that does not say it is all-day is a timed one.
    assert task.due_all_day is False


def test_a_save_that_leaves_the_schedule_alone_keeps_the_stored_deadline(user):
    task = create_task(
        user=user,
        title="Call",
        notes="",
        category=None,
        due_at=timezone.make_aware(datetime(2026, 9, 6, 9, 0)),
    )
    newer = timezone.make_aware(datetime(2026, 9, 20, 23, 59, 59, 999999))
    # Another request moves the deadline after the caller read the task.
    Task.objects.filter(pk=task.pk).update(due_at=newer, due_all_day=True)

    update_task(
        user=user,
        task_id=task.pk,
        title="Renamed",
        notes="",
        category=None,
        due_at=timezone.make_aware(datetime(2026, 9, 6, 9, 0)),
        schedule_changed=False,
    )

    task.refresh_from_db()
    assert (task.title, task.due_at, task.due_all_day) == ("Renamed", newer, True)


def test_a_task_is_timed_unless_the_caller_says_otherwise(user):
    task = create_task(
        user=user,
        title="Call",
        notes="",
        category=None,
        due_at=timezone.make_aware(datetime(2026, 9, 6, 9, 0)),
    )

    assert task.due_all_day is False
