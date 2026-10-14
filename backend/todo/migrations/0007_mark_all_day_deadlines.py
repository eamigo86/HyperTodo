"""Give the deadlines stored at local midnight the all-day flag they never had.

A date-only deadline used to be stored as the start of its day, so the task counted
as overdue from 00:00 on the very day it was due. The task form now stores the LAST
instant of the day and sets Task.due_all_day; this migration rewrites the rows the
old form left behind.

The approximation: a stored deadline cannot say whether its owner typed "00:00" or
typed no time at all, so every deadline at exactly 00:00 local time becomes an
all-day one, and a task deliberately set at midnight now lasts until the day ends.
The local day is the server's TIME_ZONE, the only zone the old date-only form used.
The day is rebuilt from its local date and never by adding 24 hours, which would slip
an hour into the next day when the clocks change.

Apply it once. It is correct for its first application, on deadlines the old
date-only form wrote in the server zone, and it is not a repair tool. Do not run it
again (migrate todo 0006, then migrate todo 0007) on a database the current app has
used. Both directions work in the server zone, while the task form has saved in the
zone each client reports (X-Timezone) since UserTimezoneMiddleware, so a second pass
re-anchors every all-day row created in another zone (a Tokyo one moves 13 or 14
hours on a New York server), turns a task deliberately set at 00:00 into an all-day
one, and leaves wrong a row that an earlier version of this migration wrote with
fold=0 (an hour early on a repeated hour, a day late in Nuuk's skipped one). Data
damaged that way needs a selective repair of the affected rows, after a backup.

A day whose clocks skip 00:00 (Africa/Cairo on a spring Friday) never had a midnight
to store, so a date-only deadline the old form saved there sits at 01:00 and stays a
timed one.

The two ends of the calendar are left alone. The last instant of 9999-12-31 in New
York is in year 10000 once it is converted to UTC, and the first days of year 1 have
no local reading west of Greenwich; either raises OverflowError (or, inside SQLite's
own date functions, a DataError) and used to abort the whole migration, which rolled
back and left the database at 0006. The task form only accepts 2000 to 2100, so such a
row is stray legacy data, and it stays the timed deadline it always was.
"""

from datetime import UTC, datetime, time

from django.db import migrations
from django.utils import timezone

# Rows are read this many at a time, so a large table is never held whole in memory.
CHUNK = 500
# Explicit instants, not a lookup like due_at__year: that has to convert every row to
# local time first, and fails on the very rows it is meant to exclude.
CONVERTIBLE_FROM = datetime(1, 1, 2, tzinfo=UTC)
CONVERTIBLE_BEFORE = datetime(9999, 1, 1, tzinfo=UTC)
# The last instant of a day, as the task form stores it: fold=1 is the later reading of
# 23:59:59.999999 on a night the clocks go back and the instant before the jump on a
# night they go forward. The default, fold=0, ended such a day an hour early or on the
# next day.
END_OF_DAY = time.max.replace(fold=1)


def _convertible(rows):
    """Keep the rows whose local day can be read and written back as UTC.

    The bounds are plain comparisons, applied before any filter that converts a row to
    local time, so SQLite never meets a value it cannot convert.
    """
    return rows.filter(due_at__gte=CONVERTIBLE_FROM, due_at__lt=CONVERTIBLE_BEFORE)


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
    midnights = _convertible(tasks.filter(due_all_day=False)).filter(
        due_at__time=time.min
    )
    for chunk in _local_days(midnights):
        for pk, day in chunk:
            tasks.filter(pk=pk).update(
                due_all_day=True,
                due_at=timezone.make_aware(datetime.combine(day, END_OF_DAY)),
            )


def restore_midnight_deadlines(apps, schema_editor):
    """Put every all-day deadline back at the start of its day, unflagged.

    The flag goes with the end of the day: the forward migration only reads unflagged
    rows, so a row left flagged here would be skipped by the next run and stay at
    00:00. With it cleared, 0007, 0006 and 0007 again give the same rows.

    A day whose clocks skip 00:00 (Africa/Cairo on a spring Friday) has no start to
    go back to: 00:00 would read 01:00, and the forward migration, which only moves
    rows at midnight, would never flag that row again. Such a row keeps its flag and
    its end of day, which is exactly what a later forward run expects to find. The same
    goes for a day whose start lies below CONVERTIBLE_FROM: the forward run never reads
    that far back, so an unflagged row there would lose the flag for good.

    Rolling back and forward again is exact only for rows the old date-only form wrote
    in the server zone; see the module docstring before using it on anything else.
    """
    tasks = apps.get_model("todo", "Task")._default_manager.using(
        schema_editor.connection.alias
    )
    for chunk in _local_days(_convertible(tasks.filter(due_all_day=True))):
        for pk, day in chunk:
            start = timezone.make_aware(datetime.combine(day, time.min))
            # Through UTC, as the database stores it: an aware value already in the
            # local zone would read back as the 00:00 it was built with.
            start_utc = start.astimezone(UTC)
            if start_utc < CONVERTIBLE_FROM or (
                timezone.localtime(start_utc).time() != time.min
            ):
                continue
            tasks.filter(pk=pk).update(due_all_day=False, due_at=start)


class Migration(migrations.Migration):
    dependencies = [("todo", "0006_task_due_all_day")]

    operations = [
        migrations.RunPython(
            mark_midnight_deadlines_all_day, restore_midnight_deadlines
        )
    ]
