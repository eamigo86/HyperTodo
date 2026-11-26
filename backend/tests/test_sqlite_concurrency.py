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
from tests.test_config import load_settings

BACKEND = Path(__file__).resolve().parents[1]
# One of two identical creates wins and the other is told, on its field, that it lost.
ONE_WINS_ONE_IS_REFUSED = [201, 422]


def test_the_default_database_takes_the_write_lock_up_front_and_waits_for_it() -> None:
    """The default database takes the write lock up front and waits for it."""
    options = project.DATABASES["default"]["OPTIONS"]

    assert options["transaction_mode"] == "IMMEDIATE"
    # Longer than one request takes, with room for a few queued behind it.
    assert options["timeout"] >= 10


def run_race(
    database: Path, settings_module: str = "tests.settings_file_database", **env: str
) -> subprocess.CompletedProcess[str]:
    """Run the race in a clean child interpreter and return the finished process.

    Args:
        database: Path of the SQLite database file the race uses.
        settings_module: Settings module the child interpreter loads.
        **env: Environment variables added to the child interpreter.

    Returns:
        The finished child process with its output captured.
    """
    return subprocess.run(
        [sys.executable, "-m", "tests.sqlite_race"],
        cwd=BACKEND,
        env={
            **{
                name: value
                for name, value in os.environ.items()
                if not name.startswith(("DJANGO_", "HYPERTODO_"))
            },
            "DJANGO_SETTINGS_MODULE": settings_module,
            "HYPERTODO_RACE_DATABASE": str(database),
            **env,
        },
        capture_output=True,
        text=True,
        timeout=240,
    )


@pytest.fixture(scope="module")
def races(tmp_path_factory: pytest.TempPathFactory) -> dict[str, list[object]]:
    """Run the scenarios once and return each one's list of per-trial statuses.

    Args:
        tmp_path_factory: Factory for the temporary directory of the race database.

    Returns:
        Per-trial statuses of each race scenario.
    """
    result = run_race(tmp_path_factory.mktemp("races") / "race.sqlite3")
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.splitlines()[-1])


def test_no_race_between_two_requests_answers_a_500(
    races: dict[str, list[object]],
) -> None:
    """No race between two requests answers a 500.

    Args:
        races: Per-trial statuses of each race scenario, run once.
    """
    for scenario, trials in races.items():
        failed = [statuses for statuses in trials if 500 in statuses]
        assert not failed, f"{scenario}: {len(failed)} of {len(trials)} trials"


def test_a_duplicate_category_created_twice_at_once_keeps_one_and_refuses_one(
    races: dict[str, list[object]],
) -> None:
    """A duplicate category created twice at once keeps one and refuses one.

    Args:
        races: Per-trial statuses of each race scenario, run once.
    """
    assert all(
        sorted(statuses) == ONE_WINS_ONE_IS_REFUSED
        for statuses in races["duplicate_category"]
    )


def test_two_renames_to_the_same_name_keep_one_and_refuse_one(
    races: dict[str, list[object]],
) -> None:
    """Two renames to the same name keep one and refuse one.

    Args:
        races: Per-trial statuses of each race scenario, run once.
    """
    assert all(
        sorted(statuses) == [200, 422] for statuses in races["colliding_renames"]
    )


def test_a_task_created_while_its_category_is_deleted_never_errors(
    races: dict[str, list[object]],
) -> None:
    """A task created while its category is deleted never errors.

    Args:
        races: Per-trial statuses of each race scenario, run once.
    """
    for created, deleted in races["task_against_category_delete"]:
        assert created in (201, 422)
        assert deleted == 200


def test_two_accounts_creating_tasks_at_once_both_succeed(
    races: dict[str, list[object]],
) -> None:
    """Two accounts creating tasks at once both succeed.

    Args:
        races: Per-trial statuses of each race scenario, run once.
    """
    assert all(statuses == [201, 201] for statuses in races["two_users_create_tasks"])


# --- the races stay away from the project's Redis -------------------------------

LOCMEM = "django.core.cache.backends.locmem.LocMemCache"
SETTINGS_PROBE = (
    "import json; from django.conf import settings as s; "
    "print(json.dumps({'hyperview': s.HYPERVIEW, 'caches': s.CACHES}, default=str))"
)


@pytest.mark.parametrize("redis_cache", ["0", "1"], ids=["cache-off", "cache-on"])
def test_the_race_settings_publish_nothing_and_cache_in_memory(
    tmp_path: Path, redis_cache: str
) -> None:
    """The race settings publish nothing and cache in memory.

    Args:
        tmp_path: Temporary directory for the files this test writes.
        redis_cache: Whether the cache switch is set to on (1) or off (0).
    """
    # The project settings turn on realtime and, with ENABLE_REDIS_CACHE, a Redis
    # template cache. The races used to inherit both: 240 hints published to the
    # development channels of the users with ids 1 and 2.
    result = load_settings(
        SETTINGS_PROBE,
        DJANGO_SETTINGS_MODULE="tests.settings_file_database",
        HYPERTODO_RACE_DATABASE=str(tmp_path / "race.sqlite3"),
        ENABLE_REDIS_CACHE=redis_cache,
    )

    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout)
    assert state["hyperview"]["REALTIME"] is None
    assert "CACHE" not in state["hyperview"]
    assert {cache["BACKEND"] for cache in state["caches"].values()} == {LOCMEM}


# Closed port 1, so a refusal that fails to happen still reaches no real Redis.
NOWHERE = "redis://127.0.0.1:1/15"
LEAKS = {
    "realtime": (
        "HYPERVIEW = {**HYPERVIEW, 'REALTIME': "
        f"{{'REDIS_URL': '{NOWHERE}', 'NAMESPACE': 'leak'}}}}"
    ),
    "template-cache": "HYPERVIEW = {**HYPERVIEW, 'CACHE': {'ALIAS': 'default'}}",
    "redis-cache": (
        "CACHES = {'default': {'BACKEND': 'django_redis.cache.RedisCache', "
        f"'LOCATION': '{NOWHERE}'}}}}"
    ),
}


@pytest.mark.parametrize("leak", LEAKS)
def test_the_race_refuses_to_run_when_settings_would_reach_redis(
    tmp_path: Path, leak: str
) -> None:
    """The race refuses to run when the settings would reach Redis.

    Args:
        tmp_path: Temporary directory for the files this test writes.
        leak: Name of the settings leak the race must refuse to run with.
    """
    (tmp_path / "leaky_race_settings.py").write_text(
        f"from tests.settings_file_database import *\n{LEAKS[leak]}\n"
    )
    database = tmp_path / "race.sqlite3"

    result = run_race(
        database, settings_module="leaky_race_settings", PYTHONPATH=str(tmp_path)
    )

    assert result.returncode != 0
    assert "refusing to run" in result.stderr
    # It stopped before it migrated anything or published a single hint.
    assert not database.exists()
