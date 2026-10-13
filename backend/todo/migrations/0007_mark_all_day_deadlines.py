"""Give the deadlines stored at local midnight the all-day flag they never had.

A date-only deadline used to be stored as the start of its day, so the task counted
as overdue from 00:00 on the very day it was due. The task form now stores the LAST
instant of the day and sets Task.due_all_day; this migration rewrites the rows the
old form left behind.

The approximation: a stored deadline cannot say whether its owner typed "00:00" or
typed no time at all, so every deadline at exactly 00:00 local time becomes an
all-day one, and a task deliberately set at midnight now lasts until the day ends.
The local day is the server's TIME_ZONE, the only zone the form ever used. The day is
rebuilt from its local date and never by adding 24 hours, which would slip an hour
into the next day when the clocks change.
"""

from datetime import datetime, time

from django.db import migrations
from django.utils import timezone

# Rows are read this many at a time, so a large table is never held whole in memory.
CHUNK = 500


def _local_days(rows):
    """Yield lists of at most CHUNK (pk, local date of due_at) pairs, by primary key."""
    rows = rows.order_by("pk").only("pk", "due_at")
    chunk = list(rows[:CHUNK])
    while chunk:
        yield [(row.pk, timezone.localtime(row.due_at).date()) for row in chunk]
        # Keyset paging rather than OFFSET: the caller rewrites rows between chunks.
        chunk = list(rows.filter(pk__gt=chunk[-1].pk)[:CHUNK])


def mark_midnight_deadlines_all_day(apps, schema_editor):
    """Move every deadline at local midnight to the end of its day and flag it."""
    tasks = apps.get_model("todo", "Task")._default_manager.using(
        schema_editor.connection.alias
    )
    for chunk in _local_days(tasks.filter(due_all_day=False, due_at__time=time.min)):
        for pk, day in chunk:
            tasks.filter(pk=pk).update(
                due_all_day=True,
                due_at=timezone.make_aware(datetime.combine(day, time.max)),
            )


def restore_midnight_deadlines(apps, schema_editor):
    """Put every all-day deadline back at the start of its day, the old shape."""
    tasks = apps.get_model("todo", "Task")._default_manager.using(
        schema_editor.connection.alias
    )
    for chunk in _local_days(tasks.filter(due_all_day=True, due_at__isnull=False)):
        for pk, day in chunk:
            tasks.filter(pk=pk).update(
                due_at=timezone.make_aware(datetime.combine(day, time.min))
            )


class Migration(migrations.Migration):
    dependencies = [("todo", "0006_task_due_all_day")]

    operations = [
        migrations.RunPython(
            mark_midnight_deadlines_all_day, restore_midnight_deadlines
        )
    ]
