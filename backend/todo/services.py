"""Transactional mutation boundary for private TODO data."""

from datetime import datetime
from uuid import UUID

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import Category, Task


@transaction.atomic
def create_category(*, user: AbstractBaseUser, name: str, color: str) -> Category:
    """Create a validated category for one user.

    Args:
        user: Category owner.
        name: Display name.
        color: Supported color value.

    Returns:
        Persisted category.

    Raises:
        ValidationError: If category data is invalid.
    """
    category = Category(user=user, name=name, color=color)
    category.full_clean()
    category.save()
    return category


@transaction.atomic
def update_category(
    *, user: AbstractBaseUser, category_id: UUID, name: str, color: str
) -> Category:
    """Update an owned category.

    Args:
        user: Category owner.
        category_id: Category identifier.
        name: Replacement display name.
        color: Replacement supported color.

    Returns:
        Updated category.

    Raises:
        Http404: If the category is not owned by the user.
        ValidationError: If category data is invalid.
    """
    category = get_object_or_404(Category, pk=category_id, user=user)
    category.name = name
    category.color = color
    category.full_clean()
    category.save(update_fields=("name", "color", "updated_at"))
    return category


@transaction.atomic
def delete_category(*, user: AbstractBaseUser, category_id: UUID) -> None:
    """Delete an owned category while preserving its tasks.

    Args:
        user: Category owner.
        category_id: Category identifier.

    Raises:
        Http404: If the category is not owned by the user.
    """
    get_object_or_404(Category, pk=category_id, user=user).delete()


@transaction.atomic
def create_task(
    *,
    user: AbstractBaseUser,
    title: str,
    notes: str,
    category: Category | None,
    due_at: datetime | None,
) -> Task:
    """Create a validated task for one user.

    Args:
        user: Task owner.
        title: Task title.
        notes: Optional details.
        category: Optional category owned by the user.
        due_at: Optional timezone-aware deadline.

    Returns:
        Persisted task.

    Raises:
        ValidationError: If task data is invalid.
    """
    task = Task(user=user, title=title, notes=notes, category=category, due_at=due_at)
    task.full_clean()
    task.save()
    return task


@transaction.atomic
def update_task(
    *,
    user: AbstractBaseUser,
    task_id: UUID,
    title: str,
    notes: str,
    category: Category | None,
    due_at: datetime | None,
) -> Task:
    """Update an owned task.

    Args:
        user: Task owner.
        task_id: Task identifier.
        title: Replacement title.
        notes: Replacement details.
        category: Replacement optional category.
        due_at: Replacement optional deadline.

    Returns:
        Updated task.

    Raises:
        Http404: If the task is not owned by the user.
        ValidationError: If task data is invalid.
    """
    task = get_object_or_404(Task, pk=task_id, user=user)
    task.title = title
    task.notes = notes
    task.category = category
    task.due_at = due_at
    task.full_clean()
    task.save(update_fields=("title", "notes", "category", "due_at", "updated_at"))
    return task


@transaction.atomic
def toggle_task(*, user: AbstractBaseUser, task_id: UUID) -> Task:
    """Toggle completion for an owned task.

    Args:
        user: Task owner.
        task_id: Task identifier.

    Returns:
        Updated task.

    Raises:
        Http404: If the task is not owned by the user.
    """
    task = get_object_or_404(Task, pk=task_id, user=user)
    task.completed_at = None if task.completed_at else timezone.now()
    task.save(update_fields=("completed_at", "updated_at"))
    return task


@transaction.atomic
def delete_task(*, user: AbstractBaseUser, task_id: UUID) -> None:
    """Delete an owned task.

    Args:
        user: Task owner.
        task_id: Task identifier.

    Raises:
        Http404: If the task is not owned by the user.
    """
    get_object_or_404(Task, pk=task_id, user=user).delete()
