"""Persistence models for private TODO data."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower


class Category(models.Model):
    """A user-owned task category with a controlled display color."""

    class Color(models.TextChoices):
        """Supported category colors from the HyperTodo visual system."""

        LAVENDER = "lavender", "Lavender"
        YELLOW = "yellow", "Yellow"
        MINT = "mint", "Mint"
        PINK = "pink", "Pink"
        GREEN = "green", "Green"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="todo_categories",
    )
    name = models.CharField(max_length=80)
    color = models.CharField(max_length=16, choices=Color, default=Color.LAVENDER)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "user", name="todo_category_user_name_ci_unique"
            )
        ]

    def __str__(self) -> str:
        """Return the category name.

        Returns:
            Human-readable category name.
        """
        return self.name


class Task(models.Model):
    """A user-owned task with an optional deadline and category."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="todo_tasks"
    )
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
    )
    title = models.CharField(max_length=160)
    notes = models.TextField(blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("completed_at", "due_at", "-created_at")
        indexes = [
            models.Index(
                fields=("user", "completed_at", "due_at"),
                name="todo_task_user_state_due",
            ),
            models.Index(fields=("user", "category"), name="todo_task_user_category"),
        ]

    def __str__(self) -> str:
        """Return the task title.

        Returns:
            Human-readable task title.
        """
        return self.title

    @property
    def is_completed(self) -> bool:
        """Report whether the task has a completion timestamp.

        Returns:
            True when the task is complete.
        """
        return self.completed_at is not None

    def clean(self) -> None:
        """Validate ownership relationships.

        Raises:
            ValidationError: If the category belongs to another user.
        """
        super().clean()
        if self.category_id and self.category.user_id != self.user_id:
            raise ValidationError(
                {"category": "Category must belong to the same user."}
            )
