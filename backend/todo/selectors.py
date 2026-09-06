"""Read-only queries for TODO screens."""

from datetime import date, datetime, timedelta
from typing import Any

from django.contrib.auth.models import AbstractBaseUser
from django.db.models import Count, Min, Q, QuerySet
from django.db.models.expressions import OrderBy
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import Category, Task

WEEK_DAYS = 7
BAR_MAX_HEIGHT = 48
BAR_MIN_HEIGHT = 6
WEEKDAY_INITIALS = "MTWTFSS"
# A weekday name only identifies one day inside the coming week.
WEEKDAY_LABEL_DAYS = 6
NEXT_TASK_LIMIT = 5
# One bounded window feeds both the week bars and the streak, so the
# streak saturates at STREAK_WINDOW_DAYS. Widen the constant if longer runs matter.
STREAK_WINDOW_DAYS = 30

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
    now = timezone.now()
    totals = _dashboard_aggregates(user, now=now, today=timezone.localdate(now))
    return _dashboard_counts_from(totals)


def _dashboard_aggregates(
    user: AbstractBaseUser, *, now: datetime, today: date
) -> dict[str, Any]:
    """Collect the dashboard counters and schedule facts in one query.

    Args:
        user: Authenticated task owner.
        now: Current timestamp.
        today: Current local date.

    Returns:
        Aggregate values shared by dashboard counters and progress details.
    """
    return Task.objects.filter(user=user).aggregate(
        count_today=Count(
            "pk", filter=Q(completed_at__isnull=True, due_at__date=today)
        ),
        count_scheduled=Count(
            "pk", filter=Q(completed_at__isnull=True, due_at__date__gt=today)
        ),
        count_all=Count("pk"),
        count_overdue=Count("pk", filter=Q(completed_at__isnull=True, due_at__lt=now)),
        done_today=Count("pk", filter=Q(completed_at__date=today)),
        due_today=Count("pk", filter=Q(due_at__date=today)),
        total_today=Count(
            "pk", filter=Q(due_at__date=today) | Q(completed_at__date=today)
        ),
        next_scheduled=Min(
            "due_at",
            filter=Q(completed_at__isnull=True, due_at__date__gt=today),
        ),
    )


def _dashboard_counts_from(totals: dict[str, Any]) -> dict[str, int]:
    """Extract the public counter shape from dashboard aggregates.

    Args:
        totals: Aggregate values produced for one dashboard.

    Returns:
        Counts for today, scheduled, all, and overdue tasks.
    """
    return {
        "today": totals["count_today"],
        "scheduled": totals["count_scheduled"],
        "all": totals["count_all"],
        "overdue": totals["count_overdue"],
    }


def _completions_by_local_day(
    user: AbstractBaseUser, *, since: date
) -> dict[date, int]:
    """Count a user's completions per local calendar day.

    Args:
        user: Authenticated task owner.
        since: Oldest local day to include.

    Returns:
        Completion count keyed by local date, skipping days without work.
    """
    rows = (
        Task.objects.filter(user=user, completed_at__date__gte=since)
        .annotate(day=TruncDate("completed_at", tzinfo=timezone.get_current_timezone()))
        .values("day")
        .annotate(completed=Count("pk"))
    )
    return {row["day"]: row["completed"] for row in rows}


def _week_bars(completions: dict[date, int], today: date) -> list[dict[str, Any]]:
    """Build the seven local days ending today as scaled bar descriptors.

    Args:
        completions: Completion count keyed by local date.
        today: Current local date.

    Returns:
        One dict per day with label, date, completion count, and bar height.
    """
    days = [today - timedelta(days=offset) for offset in reversed(range(WEEK_DAYS))]
    counts = [completions.get(day, 0) for day in days]
    peak = max(counts)
    return [
        {
            "label": WEEKDAY_INITIALS[day.weekday()],
            "date": day,
            "completed": completed,
            "height": (
                max(BAR_MIN_HEIGHT, round(BAR_MAX_HEIGHT * completed / peak))
                if completed
                else BAR_MIN_HEIGHT
            ),
            "is_today": day == today,
        }
        for day, completed in zip(days, counts, strict=True)
    ]


def _streak_days(completions: dict[date, int], today: date) -> int:
    """Count consecutive local days with completions ending today.

    Today only extends the run when it already has a completion; otherwise the
    run ending yesterday is reported so an unfinished day does not reset it.

    Args:
        completions: Completion count keyed by local date.
        today: Current local date.

    Returns:
        Length of the trailing run, capped at STREAK_WINDOW_DAYS.
    """
    cursor = today if today in completions else today - timedelta(days=1)
    streak = 0
    while cursor in completions and streak < STREAK_WINDOW_DAYS:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _next_scheduled_label(next_scheduled: datetime | None, today: date) -> str:
    """Label the next scheduled deadline for the dashboard stat card.

    Args:
        next_scheduled: Earliest open future deadline, or None when nothing is due.
        today: Current local date.

    Returns:
        Weekday name within the coming week, a short date beyond it, or "".
    """
    if next_scheduled is None:
        return ""
    local = timezone.localtime(next_scheduled)
    if (local.date() - today).days <= WEEKDAY_LABEL_DAYS:
        return local.strftime("%a")
    return f"{local:%b} {local.strftime('%d').lstrip('0')}"


def dashboard_summary(user: AbstractBaseUser) -> dict[str, Any]:
    """Summarize one user's day, week, and upcoming work for the dashboard.

    Args:
        user: Authenticated task owner.

    Returns:
        Template-friendly summary of today's progress and the trailing week.
    """
    now = timezone.now()
    today = timezone.localdate(now)
    completions = _completions_by_local_day(
        user, since=today - timedelta(days=STREAK_WINDOW_DAYS)
    )
    week = _week_bars(completions, today)
    totals = _dashboard_aggregates(user, now=now, today=today)
    total_today = totals["total_today"]
    next_scheduled = totals["next_scheduled"]
    return {
        "today": today,
        "done_today": totals["done_today"],
        "due_today": totals["due_today"],
        "total_today": total_today,
        "progress_percent": (
            round(100 * totals["done_today"] / total_today) if total_today else 0
        ),
        "counts": _dashboard_counts_from(totals),
        "week": week,
        "week_completed_total": sum(day["completed"] for day in week),
        "streak_days": _streak_days(completions, today),
        "category_counts": [
            {"category": category, "active": category.active_count}
            for category in Category.objects.filter(user=user)
            .annotate(
                active_count=Count(
                    "tasks",
                    filter=Q(tasks__completed_at__isnull=True, tasks__user=user),
                )
            )
            .order_by("name")
        ],
        "next_tasks": list(tasks_for_user(user, status="active")[:NEXT_TASK_LIMIT]),
        "next_scheduled_label": _next_scheduled_label(next_scheduled, today),
    }
