"""Tests for task selection and dashboard counts."""

from datetime import timedelta

import pytest
from django.utils import timezone

from todo.models import Category, Task
from todo.selectors import dashboard_counts, dashboard_summary, tasks_for_user

pytestmark = pytest.mark.django_db


def freeze_local_noon(monkeypatch):
    """Freeze timezone.now on the local noon of the current day.

    Patching the shared django.utils.timezone.now freezes auto_now_add too.
    """
    now = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0)
    monkeypatch.setattr("django.utils.timezone.now", lambda: now)
    return now


def test_task_filters_are_composable_and_user_isolated(user, other_user, monkeypatch):
    now = freeze_local_noon(monkeypatch)
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
    today = Task.objects.create(user=user, title="Today", due_at=today_due)
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


def test_dashboard_counts_describe_private_work(
    user, other_user, monkeypatch, django_assert_num_queries
):
    now = freeze_local_noon(monkeypatch)
    today_due = timezone.localtime(now).replace(
        hour=23, minute=59, second=59, microsecond=0
    )
    Task.objects.create(user=user, title="Today", due_at=today_due)
    Task.objects.create(user=user, title="Later", due_at=now + timedelta(days=2))
    Task.objects.create(user=user, title="Late", due_at=now - timedelta(hours=1))
    Task.objects.create(user=user, title="Done", completed_at=now)
    Task.objects.create(user=other_user, title="Hidden")

    with django_assert_num_queries(1):
        counts = dashboard_counts(user)

    assert counts == {
        "today": 2,
        "scheduled": 1,
        "all": 4,
        "overdue": 1,
    }


def test_dashboard_summary_measures_today_progress(user, monkeypatch):
    now = freeze_local_noon(monkeypatch)
    today_due = now.replace(hour=23, minute=59)
    Task.objects.create(user=user, title="Due today", due_at=today_due)
    Task.objects.create(
        user=user, title="Due and done", due_at=today_due, completed_at=now
    )
    Task.objects.create(user=user, title="Done, no deadline", completed_at=now)
    Task.objects.create(user=user, title="Later", due_at=now + timedelta(days=3))

    summary = dashboard_summary(user)

    assert summary["done_today"] == 2
    assert summary["due_today"] == 2
    assert summary["total_today"] == 3
    assert summary["progress_percent"] == 67
    assert summary["counts"] == {
        "today": 1,
        "scheduled": 1,
        "all": 4,
        "overdue": 0,
    }


def test_dashboard_summary_progress_is_zero_without_work_today(user, monkeypatch):
    now = freeze_local_noon(monkeypatch)
    Task.objects.create(user=user, title="Later", due_at=now + timedelta(days=4))

    summary = dashboard_summary(user)

    assert summary["done_today"] == 0
    assert summary["due_today"] == 0
    assert summary["total_today"] == 0
    assert summary["progress_percent"] == 0


def test_dashboard_summary_buckets_the_week_by_local_day(user, monkeypatch):
    now = freeze_local_noon(monkeypatch)
    today = timezone.localdate(now)
    late_yesterday = now.replace(hour=23, minute=30) - timedelta(days=1)
    for index in range(3):
        Task.objects.create(user=user, title=f"Today {index}", completed_at=now)
    Task.objects.create(user=user, title="Late", completed_at=late_yesterday)
    Task.objects.create(
        user=user, title="Six days ago", completed_at=now - timedelta(days=6)
    )
    Task.objects.create(
        user=user, title="Out of window", completed_at=now - timedelta(days=8)
    )

    summary = dashboard_summary(user)
    week = summary["week"]

    assert [day["date"] for day in week] == [
        today - timedelta(days=offset) for offset in reversed(range(7))
    ]
    assert [day["completed"] for day in week] == [1, 0, 0, 0, 0, 1, 3]
    assert [day["is_today"] for day in week] == [False] * 6 + [True]
    assert [day["label"] for day in week] == [
        "MTWTFSS"[(today - timedelta(days=offset)).weekday()]
        for offset in reversed(range(7))
    ]
    assert [day["height"] for day in week] == [16, 6, 6, 6, 6, 16, 48]
    assert summary["week_completed_total"] == 5


@pytest.mark.parametrize(
    ("completed_days_ago", "expected_streak"),
    [
        pytest.param((0, 1, 2), 3, id="three-consecutive-days"),
        pytest.param((0, 1, 3), 2, id="gap-resets-the-run"),
        pytest.param((1, 2, 3), 3, id="today-idle-counts-the-run-to-yesterday"),
        pytest.param((2, 3), 0, id="yesterday-idle-breaks-the-run"),
        pytest.param((), 0, id="no-completions"),
        pytest.param(tuple(range(10)), 10, id="run-longer-than-one-week"),
        pytest.param(tuple(range(31)), 30, id="saturates-at-the-window"),
    ],
)
def test_dashboard_summary_counts_the_completion_streak(
    user, monkeypatch, completed_days_ago, expected_streak
):
    now = freeze_local_noon(monkeypatch)
    for days_ago in completed_days_ago:
        Task.objects.create(
            user=user,
            title=f"Done {days_ago}",
            completed_at=now - timedelta(days=days_ago),
        )

    assert dashboard_summary(user)["streak_days"] == expected_streak


def test_dashboard_summary_counts_active_tasks_per_owned_category(
    user, other_user, monkeypatch
):
    now = freeze_local_noon(monkeypatch)
    work = Category.objects.create(
        user=user, name="Work", color=Category.Color.LAVENDER
    )
    admin = Category.objects.create(user=user, name="Admin", color=Category.Color.MINT)
    Category.objects.create(user=user, name="Zen", color=Category.Color.YELLOW)
    foreign = Category.objects.create(
        user=other_user, name="Foreign", color=Category.Color.PINK
    )
    Task.objects.create(user=user, category=work, title="Active one")
    Task.objects.create(user=user, category=work, title="Active two")
    Task.objects.create(user=user, category=work, title="Done", completed_at=now)
    Task.objects.create(user=user, title="Uncategorised")
    Task.objects.create(user=other_user, category=foreign, title="Hidden")
    Task.objects.create(user=other_user, category=work, title="Foreign guest")

    counts = dashboard_summary(user)["category_counts"]

    assert [(row["category"], row["active"]) for row in counts] == [
        (admin, 0),
        (work, 2),
        (Category.objects.get(name="Zen"), 0),
    ]


def test_dashboard_summary_lists_next_active_tasks_with_nulls_last(
    user, other_user, monkeypatch
):
    now = freeze_local_noon(monkeypatch)
    Task.objects.create(user=user, title="Overdue", due_at=now - timedelta(days=1))
    Task.objects.create(user=user, title="Today", due_at=now.replace(hour=23))
    Task.objects.create(
        user=user, title="In three days", due_at=now + timedelta(days=3)
    )
    Task.objects.create(user=user, title="Someday")
    Task.objects.create(
        user=user,
        title="Done tomorrow",
        due_at=now + timedelta(days=1),
        completed_at=now,
    )
    Task.objects.create(user=other_user, title="Hidden", due_at=now)

    summary = dashboard_summary(user)

    assert [task.title for task in summary["next_tasks"]] == [
        "Overdue",
        "Today",
        "In three days",
        "Someday",
    ]
    assert summary["next_scheduled_label"] == (now + timedelta(days=3)).strftime("%a")

    Task.objects.create(user=user, title="In five days", due_at=now + timedelta(days=5))
    Task.objects.create(user=user, title="In six days", due_at=now + timedelta(days=6))

    assert [task.title for task in dashboard_summary(user)["next_tasks"]] == [
        "Overdue",
        "Today",
        "In three days",
        "In five days",
        "In six days",
    ]


@pytest.mark.parametrize(
    ("days_ahead", "expects_weekday"),
    [
        pytest.param(1, True, id="tomorrow-reads-as-a-weekday"),
        pytest.param(6, True, id="last-unambiguous-weekday"),
        pytest.param(7, False, id="a-week-out-reads-as-a-date"),
        pytest.param(30, False, id="far-future-reads-as-a-date"),
    ],
)
def test_dashboard_summary_dates_the_next_scheduled_task_beyond_the_week(
    user, monkeypatch, days_ahead, expects_weekday
):
    now = freeze_local_noon(monkeypatch)
    due_at = now + timedelta(days=days_ahead)
    Task.objects.create(user=user, title="Planned", due_at=due_at)

    label = dashboard_summary(user)["next_scheduled_label"]

    assert label == (f"{due_at:%a}" if expects_weekday else f"{due_at:%b} {due_at.day}")


def test_dashboard_summary_reports_no_label_without_future_work(user, monkeypatch):
    now = freeze_local_noon(monkeypatch)
    Task.objects.create(user=user, title="Overdue", due_at=now - timedelta(days=2))

    summary = dashboard_summary(user)

    assert summary["next_scheduled_label"] == ""
    assert [task.title for task in summary["next_tasks"]] == ["Overdue"]


def test_dashboard_summary_is_user_isolated_within_four_queries(
    user, other_user, monkeypatch, django_assert_num_queries
):
    now = freeze_local_noon(monkeypatch)
    work = Category.objects.create(
        user=user, name="Work", color=Category.Color.LAVENDER
    )
    noise = Category.objects.create(
        user=other_user, name="Noise", color=Category.Color.PINK
    )
    Task.objects.create(user=user, category=work, title="Mine", due_at=now)
    Task.objects.create(user=user, title="Mine done", completed_at=now)
    Task.objects.create(
        user=other_user,
        category=noise,
        title="Theirs",
        due_at=now,
        completed_at=now,
    )

    with django_assert_num_queries(4):
        summary = dashboard_summary(user)
        categories = [row["category"].name for row in summary["category_counts"]]
        titles = [
            f"{task.title} · {task.category.name if task.category else '-'}"
            for task in summary["next_tasks"]
        ]

    assert categories == ["Work"]
    assert titles == ["Mine · Work"]
    assert summary["done_today"] == 1
    assert summary["due_today"] == 1
    assert summary["week_completed_total"] == 1


def test_selector_rejects_invalid_status_and_foreign_category(user, other_user):
    foreign = Category.objects.create(
        user=other_user, name="Foreign", color=Category.Color.PINK
    )
    with pytest.raises(ValueError, match="Unsupported"):
        tasks_for_user(user, status="missing")
    with pytest.raises(ValueError, match="belong"):
        tasks_for_user(user, category=foreign)
