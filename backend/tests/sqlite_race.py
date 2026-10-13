"""Race the real write endpoints from two threads against a file-based SQLite database.

Run by tests/test_sqlite_concurrency.py in a child interpreter, as
"python -m tests.sqlite_race" with DJANGO_SETTINGS_MODULE=tests.settings_file_database
and HYPERTODO_RACE_DATABASE naming a scratch file, and never against the real
db.sqlite3. It prints one JSON object: for every scenario, the pair of statuses each
trial answered.

A deferred SQLite transaction reads first and upgrades to a write lock later, and when
two of them do that at once SQLite refuses the second immediately ("database is
locked") instead of waiting, so the endpoint answers a 500 for what is only a lost race.
A transaction that takes the write lock when it BEGINs queues behind the other one.

To reproduce by hand, take the OPTIONS off DATABASES in a scratch copy of the settings
and run this module the same way; it reports the 500s.
"""

import json
import os
import sys
import threading
from pathlib import Path

TRIALS = 30


def race(*calls):
    """Run each call in its own thread, released together, and return the results."""
    from django.db import connections

    barrier = threading.Barrier(len(calls))
    results = [None] * len(calls)

    def run(index, call):
        try:
            barrier.wait(timeout=30)
            results[index] = call()
        except Exception as error:
            results[index] = f"raised {type(error).__name__}"
        finally:
            connections.close_all()

    threads = [
        threading.Thread(target=run, args=(index, call))
        for index, call in enumerate(calls)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    return results


def signed_in(user):
    """Return a client for one user that reports a 500 instead of raising it."""
    from django.test import Client

    client = Client(raise_request_exception=False)
    client.force_login(user)
    return client


def post(client, path, **fields):
    """Return a call that POSTs the fields and answers the status code."""
    return lambda: client.post(path, fields).status_code


def duplicate_category(users, trial):
    """Two devices create the same category at once."""
    first, second = (signed_in(users["ada"]) for _ in range(2))
    fields = {"name": f"Work {trial}", "color": "mint"}
    return race(
        post(first, "/hv/categories/new/", **fields),
        post(second, "/hv/categories/new/", **fields),
    )


def colliding_renames(users, trial):
    """Two devices rename different categories to the same name at once."""
    from todo.models import Category

    one = Category.objects.create(user=users["ada"], name=f"One {trial}", color="mint")
    two = Category.objects.create(user=users["ada"], name=f"Two {trial}", color="mint")
    first, second = (signed_in(users["ada"]) for _ in range(2))
    fields = {"name": f"Same {trial}", "color": "mint"}
    return race(
        post(first, f"/hv/categories/{one.pk}/edit/", **fields),
        post(second, f"/hv/categories/{two.pk}/edit/", **fields),
    )


def task_against_category_delete(users, trial):
    """A task is created in a category while another device deletes the category."""
    from todo.models import Category

    category = Category.objects.create(
        user=users["ada"], name=f"Doomed {trial}", color="mint"
    )
    creating, deleting = (signed_in(users["ada"]) for _ in range(2))
    return race(
        post(creating, "/hv/tasks/new/", title=f"Task {trial}", category=category.pk),
        post(deleting, f"/hv/categories/{category.pk}/delete/"),
    )


def two_users_create_tasks(users, trial):
    """Two accounts create tasks at the same moment."""
    return race(
        post(signed_in(users["ada"]), "/hv/tasks/new/", title=f"Ada {trial}"),
        post(signed_in(users["grace"]), "/hv/tasks/new/", title=f"Grace {trial}"),
    )


SCENARIOS = (
    duplicate_category,
    colliding_renames,
    task_against_category_delete,
    two_users_create_tasks,
)


def main():
    """Migrate the scratch database, run every scenario and print the statuses."""
    import django
    from django.conf import settings

    # Never the project's Redis: realtime would publish a hint to the development
    # channels for every write, and a Redis cache would fill the development one.
    hyperview = settings.HYPERVIEW
    caches = {cache["BACKEND"] for cache in settings.CACHES.values()}
    if (
        hyperview.get("REALTIME")
        or "CACHE" in hyperview
        or caches != {"django.core.cache.backends.locmem.LocMemCache"}
    ):
        sys.exit("refusing to run with realtime or a cache other than local memory")
    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.test.utils import setup_test_environment

    # What the test runner does before it builds a Client: allow the "testserver" host.
    setup_test_environment()

    scratch = Path(os.environ["HYPERTODO_RACE_DATABASE"]).resolve()
    configured = Path(settings.DATABASES["default"]["NAME"]).resolve()
    # Never the project's own database: migrate and user creation write to it.
    if configured != scratch or scratch.name == "db.sqlite3":
        sys.exit(f"refusing to run against {configured}")
    call_command("migrate", verbosity=0, interactive=False)
    users = {
        name: get_user_model().objects.create_user(name, password="correct-horse")
        for name in ("ada", "grace")
    }
    outcome = {
        scenario.__name__: [scenario(users, trial) for trial in range(TRIALS)]
        for scenario in SCENARIOS
    }
    print(json.dumps(outcome))


if __name__ == "__main__":
    main()
