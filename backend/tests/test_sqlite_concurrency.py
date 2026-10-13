"""Two writers at once queue on SQLite instead of failing with "database is locked".

The write endpoints already turn a lost race into a 422 on the right field, but that
only helps once the loser reaches its own check. With SQLite's default deferred
transactions the second writer is refused the moment it asks for the write lock, which
is a 500 for a perfectly ordinary double tap. The project asks for transactions that
take the write lock when they begin, and a wait long enough for the other one to end.

The races run in a child interpreter against a scratch FILE database: the test
database is in memory, and its shared-cache locks fail in other ways than a file's.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from config import settings as project

BACKEND = Path(__file__).resolve().parents[1]
# One of two identical creates wins and the other is told, on its field, that it lost.
ONE_WINS_ONE_IS_REFUSED = [201, 422]


def test_the_default_database_takes_the_write_lock_up_front_and_waits_for_it():
    options = project.DATABASES["default"]["OPTIONS"]

    assert options["transaction_mode"] == "IMMEDIATE"
    # Longer than one request takes, with room for a few queued behind it.
    assert options["timeout"] >= 10


@pytest.fixture(scope="module")
def races(tmp_path_factory):
    """Run the scenarios once and return each one's list of per-trial statuses."""
    database = tmp_path_factory.mktemp("races") / "race.sqlite3"
    result = subprocess.run(
        [sys.executable, "-m", "tests.sqlite_race"],
        cwd=BACKEND,
        env={
            **{
                name: value
                for name, value in os.environ.items()
                if not name.startswith(("DJANGO_", "HYPERTODO_"))
            },
            "DJANGO_SETTINGS_MODULE": "tests.settings_file_database",
            "HYPERTODO_RACE_DATABASE": str(database),
        },
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.splitlines()[-1])


def test_no_race_between_two_requests_answers_a_500(races):
    for scenario, trials in races.items():
        failed = [statuses for statuses in trials if 500 in statuses]
        assert not failed, f"{scenario}: {len(failed)} of {len(trials)} trials"


def test_a_duplicate_category_created_twice_at_once_keeps_one_and_refuses_one(races):
    assert all(
        sorted(statuses) == ONE_WINS_ONE_IS_REFUSED
        for statuses in races["duplicate_category"]
    )


def test_two_renames_to_the_same_name_keep_one_and_refuse_one(races):
    assert all(
        sorted(statuses) == [200, 422] for statuses in races["colliding_renames"]
    )


def test_a_task_created_while_its_category_is_deleted_never_errors(races):
    for created, deleted in races["task_against_category_delete"]:
        assert created in (201, 422)
        assert deleted == 200


def test_two_accounts_creating_tasks_at_once_both_succeed(races):
    assert all(statuses == [201, 201] for statuses in races["two_users_create_tasks"])
