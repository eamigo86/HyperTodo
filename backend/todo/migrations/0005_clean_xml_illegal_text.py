"""Replace XML 1.0 forbidden characters stored before the validators existed.

A row saved with one of those characters keeps every screen that renders it at a
persistent 500, and a profile name even takes /hv/settings/ down, so the owner
cannot repair it in the app. Each character becomes U+FFFD. The helpers come from
todo.validators on purpose: the character class is a spec constant, not app state.
"""

from django.conf import settings
from django.db import migrations

from todo.validators import XML_ILLEGAL, scrub_xml

COLUMNS = (
    ("todo.Task", ("title", "notes")),
    (settings.AUTH_USER_MODEL, ("first_name", "last_name", "email")),
)
# Category.name is unique per user ignoring case, and the suffix below has to fit
# the column, so the base is cut before " (n)" is appended.
CATEGORY_BASE = 70
# Rows are read this many at a time, so a large table is never held whole in memory
# (200000 tasks with 2 KB notes peaked at 636 MB when read in one go).
CHUNK = 500


def _dirty_rows(manager, columns):
    """Yield (pk, replacements) for every row holding a forbidden character."""
    rows = manager.only("pk", *columns).order_by("pk")
    chunk = list(rows[:CHUNK])
    while chunk:
        for row in chunk:
            changes = {
                column: scrub_xml(text)
                for column in columns
                if XML_ILLEGAL.search(text := getattr(row, column))
            }
            if changes:
                yield row.pk, changes
        # Keyset paging rather than OFFSET: the caller rewrites rows between chunks,
        # and each chunk is fully read before it is yielded, so no cursor stays open
        # on the table being updated.
        chunk = list(rows.filter(pk__gt=chunk[-1].pk)[:CHUNK])


def _clean_categories(manager):
    """Rename dirty categories, numbering any that now collide with a sibling."""
    rows = list(manager.order_by("created_at", "pk"))
    taken = {(row.user_id, row.name.lower()) for row in rows}
    for row in rows:
        if not XML_ILLEGAL.search(row.name):
            continue
        base = scrub_xml(row.name)
        name, number = base, 1
        while (row.user_id, name.lower()) in taken:
            number += 1
            name = f"{base[:CATEGORY_BASE]} ({number})"
        taken.add((row.user_id, name.lower()))
        manager.filter(pk=row.pk).update(name=name)


def clean_xml_text(apps, schema_editor):
    """Heal every stored column that dj-hyperview could not render."""
    using = schema_editor.connection.alias
    for label, columns in COLUMNS:
        manager = apps.get_model(label)._default_manager.using(using)
        for pk, changes in _dirty_rows(manager, columns):
            manager.filter(pk=pk).update(**changes)
    _clean_categories(apps.get_model("todo", "Category")._default_manager.using(using))


class Migration(migrations.Migration):
    dependencies = [
        ("todo", "0004_xml_safe_text"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [migrations.RunPython(clean_xml_text, migrations.RunPython.noop)]
