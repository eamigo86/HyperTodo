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
