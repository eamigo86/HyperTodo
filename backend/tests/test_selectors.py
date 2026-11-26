"""Tests for task selection and dashboard counts."""

from datetime import date, datetime, time, timedelta

import pytest
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from pytest_django.fixtures import DjangoAssertNumQueries

from todo.models import Category, Task
from todo.selectors import dashboard_counts, dashboard_summary, tasks_for_user

pytestmark = pytest.mark.django_db


def freeze_local_noon(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Freeze timezone.now on the local noon of the current day.

    Patching the shared django.utils.timezone.now freezes auto_now_add too.

    Args:
        monkeypatch: Patches timezone.now.

    Returns:
        The frozen local noon.
    """
    now = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0)
    monkeypatch.setattr("django.utils.timezone.now", lambda: now)
    return now


def test_task_filters_are_composable_and_user_isolated(
    user: AbstractUser, other_user: AbstractUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Task filters compose and stay isolated per user.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
        monkeypatch: Patches the clock of the selectors for this test.
    """
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
    user: AbstractUser,
    other_user: AbstractUser,
    monkeypatch: pytest.MonkeyPatch,
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """Dashboard counts describe only the user's own work.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
        monkeypatch: Patches the clock of the selectors for this test.
        django_assert_num_queries: Asserts the exact number of queries the block runs.
    """
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


def test_dashboard_summary_measures_today_progress(
    user: AbstractUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dashboard summary measures today's progress.

    Args:
        user: Signed-in user who owns the data in this test.
        monkeypatch: Patches the clock of the selectors for this test.
    """
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


def test_dashboard_summary_progress_is_zero_without_work_today(
    user: AbstractUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dashboard summary reports zero progress when there is no work today.

    Args:
        user: Signed-in user who owns the data in this test.
        monkeypatch: Patches the clock of the selectors for this test.
    """
    now = freeze_local_noon(monkeypatch)
    Task.objects.create(user=user, title="Later", due_at=now + timedelta(days=4))

    summary = dashboard_summary(user)

    assert summary["done_today"] == 0
    assert summary["due_today"] == 0
    assert summary["total_today"] == 0
    assert summary["progress_percent"] == 0


def test_dashboard_summary_buckets_the_week_by_local_day(
    user: AbstractUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dashboard summary buckets the week by local day.

    Args:
        user: Signed-in user who owns the data in this test.
        monkeypatch: Patches the clock of the selectors for this test.
    """
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
    user: AbstractUser,
    monkeypatch: pytest.MonkeyPatch,
    completed_days_ago: tuple[int, ...],
    expected_streak: int,
) -> None:
    """The dashboard summary counts the completion streak.

    Args:
        user: Signed-in user who owns the data in this test.
        monkeypatch: Patches the clock of the selectors for this test.
        completed_days_ago: Days before today on which a task was completed.
        expected_streak: Streak the summary is expected to report.
    """
    now = freeze_local_noon(monkeypatch)
    for days_ago in completed_days_ago:
        Task.objects.create(
            user=user,
            title=f"Done {days_ago}",
            completed_at=now - timedelta(days=days_ago),
        )

    assert dashboard_summary(user)["streak_days"] == expected_streak


def test_dashboard_summary_counts_active_tasks_per_owned_category(
    user: AbstractUser, other_user: AbstractUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dashboard summary counts active tasks per owned category.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
        monkeypatch: Patches the clock of the selectors for this test.
    """
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
    user: AbstractUser, other_user: AbstractUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dashboard summary lists the next active tasks with unscheduled ones last.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
        monkeypatch: Patches the clock of the selectors for this test.
    """
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
    user: AbstractUser,
    monkeypatch: pytest.MonkeyPatch,
    days_ahead: int,
    expects_weekday: bool,
) -> None:
    """The dashboard summary dates the next scheduled task once it is beyond the week.

    Args:
        user: Signed-in user who owns the data in this test.
        monkeypatch: Patches the clock of the selectors for this test.
        days_ahead: Days from today until the next scheduled task.
        expects_weekday: Whether the label is expected to be a weekday name instead of a
        date.
    """
    now = freeze_local_noon(monkeypatch)
    due_at = now + timedelta(days=days_ahead)
    Task.objects.create(user=user, title="Planned", due_at=due_at)

    label = dashboard_summary(user)["next_scheduled_label"]

    assert label == (f"{due_at:%a}" if expects_weekday else f"{due_at:%b} {due_at.day}")


def test_dashboard_summary_reports_no_label_without_future_work(
    user: AbstractUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dashboard summary reports no label when there is no future work.

    Args:
        user: Signed-in user who owns the data in this test.
        monkeypatch: Patches the clock of the selectors for this test.
    """
    now = freeze_local_noon(monkeypatch)
    Task.objects.create(user=user, title="Overdue", due_at=now - timedelta(days=2))

    summary = dashboard_summary(user)

    assert summary["next_scheduled_label"] == ""
    assert [task.title for task in summary["next_tasks"]] == ["Overdue"]


def test_dashboard_summary_is_user_isolated_within_four_queries(
    user: AbstractUser,
    other_user: AbstractUser,
    monkeypatch: pytest.MonkeyPatch,
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """The dashboard summary is isolated per user and runs within four queries.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
        monkeypatch: Patches the clock of the selectors for this test.
        django_assert_num_queries: Asserts the exact number of queries the block runs.
    """
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


def test_selector_rejects_invalid_status_and_foreign_category(
    user: AbstractUser, other_user: AbstractUser
) -> None:
    """The selector rejects an invalid status and another user's category.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
    """
    foreign = Category.objects.create(
        user=other_user, name="Foreign", color=Category.Color.PINK
    )
    with pytest.raises(ValueError, match="Unsupported"):
        tasks_for_user(user, status="missing")
    with pytest.raises(ValueError, match="belong"):
        tasks_for_user(user, category=foreign)


def end_of_day(day: date) -> datetime:
    """Return the last instant of a local calendar day, as the task form stores it.

    Args:
        day: Local calendar day.

    Returns:
        The last instant of the day, as an aware datetime.
    """
    return timezone.make_aware(datetime.combine(day, time.max))


def test_an_all_day_deadline_stays_open_until_its_day_ends(
    user: AbstractUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An all-day deadline stays open until its day ends.

    Args:
        user: Signed-in user who owns the data in this test.
        monkeypatch: Patches the clock of the selectors for this test.
    """
    now = freeze_local_noon(monkeypatch)
    due_at = end_of_day(timezone.localdate(now))
    Task.objects.create(user=user, title="Pay rent", due_at=due_at, due_all_day=True)

    assert dashboard_counts(user) == {
        "today": 1,
        "scheduled": 0,
        "all": 1,
        "overdue": 0,
    }
    assert list(tasks_for_user(user, status="overdue")) == []
    # The last instant of the day still belongs to it...
    monkeypatch.setattr("django.utils.timezone.now", lambda: due_at)
    assert dashboard_counts(user)["overdue"] == 0
    # ...and the first instant of the next one does not.
    monkeypatch.setattr(
        "django.utils.timezone.now", lambda: due_at + timedelta(microseconds=1)
    )
    assert dashboard_counts(user) == {
        "today": 0,
        "scheduled": 0,
        "all": 1,
        "overdue": 1,
    }


def test_a_timed_deadline_is_overdue_the_moment_it_passes(
    user: AbstractUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timed deadline is overdue the moment it passes.

    Args:
        user: Signed-in user who owns the data in this test.
        monkeypatch: Patches the clock of the selectors for this test.
    """
    now = freeze_local_noon(monkeypatch)
    Task.objects.create(user=user, title="Morning call", due_at=now.replace(hour=9))
    Task.objects.create(user=user, title="Evening call", due_at=now.replace(hour=18))

    assert [t.title for t in tasks_for_user(user, status="overdue")] == ["Morning call"]
    assert dashboard_counts(user)["overdue"] == 1


def test_an_all_day_task_sorts_after_the_timed_tasks_of_its_day(
    user: AbstractUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An all-day task sorts after the timed tasks of its day.

    Args:
        user: Signed-in user who owns the data in this test.
        monkeypatch: Patches the clock of the selectors for this test.
    """
    now = freeze_local_noon(monkeypatch)
    today = timezone.localdate(now)
    Task.objects.create(
        user=user, title="All day", due_at=end_of_day(today), due_all_day=True
    )
    Task.objects.create(user=user, title="Afternoon", due_at=now.replace(hour=15))
    Task.objects.create(user=user, title="Morning", due_at=now.replace(hour=9))

    ordered = [t.title for t in tasks_for_user(user, status="today")]

    assert ordered == ["Morning", "Afternoon", "All day"]
