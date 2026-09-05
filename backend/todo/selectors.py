"""Read-only queries for TODO screens."""

from django.contrib.auth.models import AbstractBaseUser
from django.db.models import QuerySet
from django.db.models.expressions import OrderBy
from django.utils import timezone

from .models import Category, Task

VALID_STATUSES = frozenset(
    {"all", "active", "completed", "today", "scheduled", "overdue"}
)


def tasks_for_user(
    user: AbstractBaseUser, *, status: str = "all", category: Category | None = None
) -> QuerySet[Task]:
    """Return ordered tasks owned by a user with composable filters.

    Args:
        user: Authenticated task owner.
        status: One of all, active, completed, today, scheduled, or overdue.
        category: Optional user-owned category filter.

    Returns:
        Lazily evaluated task queryset.

    Raises:
        ValueError: If status is unsupported or category belongs to another user.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Unsupported task status: {status}")
    if category is not None and category.user_id != user.pk:
        raise ValueError("Category must belong to the requested user.")
    tasks = Task.objects.filter(user=user).select_related("category")
    now = timezone.now()
    today = timezone.localdate(now)
    if status == "active":
        tasks = tasks.filter(completed_at__isnull=True)
    elif status == "completed":
        tasks = tasks.filter(completed_at__isnull=False)
    elif status == "today":
        tasks = tasks.filter(completed_at__isnull=True, due_at__date=today)
    elif status == "scheduled":
        tasks = tasks.filter(completed_at__isnull=True, due_at__date__gt=today)
    elif status == "overdue":
        tasks = tasks.filter(completed_at__isnull=True, due_at__lt=now)
    if category is not None:
        tasks = tasks.filter(category=category)
    return tasks.order_by("completed_at", models_nulls_last("due_at"), "-created_at")


def models_nulls_last(field: str) -> OrderBy:
    """Build an ascending order expression with null values last.

    Args:
        field: Model field name.

    Returns:
        Django ordering expression.
    """
    from django.db.models import F

    return F(field).asc(nulls_last=True)


def dashboard_counts(user: AbstractBaseUser) -> dict[str, int]:
    """Calculate dashboard counters for one user.

    Args:
        user: Authenticated task owner.

    Returns:
        Counts for today, scheduled, all, and overdue tasks.
    """
    return {
        "today": tasks_for_user(user, status="today").count(),
        "scheduled": tasks_for_user(user, status="scheduled").count(),
        "all": tasks_for_user(user).count(),
        "overdue": tasks_for_user(user, status="overdue").count(),
    }
