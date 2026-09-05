"""Tests for TODO mutation services."""

from datetime import timedelta

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
