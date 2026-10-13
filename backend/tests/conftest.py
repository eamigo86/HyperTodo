"""Shared pytest fixtures for HyperTodo."""

import threading

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import translation


@pytest.fixture(autouse=True, scope="session")
def worker_threads_close_their_own_sqlite_connections():
    """Let a worker thread close its connection to the in-memory test database.

    Django ignores close() on an in-memory SQLite database, because closing its last
    connection destroys it. The test database is a shared-cache one that the main
    thread's connection keeps alive, so a worker thread may close its own. The
    realtime stream checks identity on the executor's threads and hands each
    connection back, and without this every thread that ends leaves an unclosed
    database behind for the garbage collector to warn about.
    """
    from django.db.backends.base.base import BaseDatabaseWrapper
    from django.db.backends.sqlite3.base import DatabaseWrapper

    original = DatabaseWrapper.close

    def close(self):
        if threading.current_thread() is threading.main_thread():
            original(self)
        else:
            BaseDatabaseWrapper.close(self)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(DatabaseWrapper, "close", close)
        yield


@pytest.fixture(autouse=True)
def private_fixture_workspace(monkeypatch, tmp_path_factory):
    """Allocate fixture data only under pytest's explicit private workspace."""
    monkeypatch.setenv(
        "HYPERTODO_FIXTURE_WORKSPACE", str(tmp_path_factory.getbasetemp())
    )


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    """Keep the biometric and password throttle counters out of every other test.

    LocMemCache is process-global and a counter lives for minutes of wall time, so a
    single rejected token in one module used to leak into every module that ran after
    it. Suite-wide because any test may POST /hv/biometric/login/ or /hv/login/.
    """
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def isolated_media(settings, tmp_path):
    """Keep every upload any test makes out of the working tree.

    Suite-wide and not scoped to the avatar module on purpose:
    tests/test_fragment_contract.py scans every template href and fires its
    declared POST, so the avatar endpoint writes a file from a second module the
    moment it appears in a template. One fixture here beats two copies that can
    drift, and a per-test tmp_path also stops uploads leaking between tests.
    """
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture(autouse=True)
def reset_active_language():
    """Stop one request's language leaking into the next test.

    Django's LocaleMiddleware activates a language and never deactivates it,
    which is harmless in production because process_request runs on every
    request. In-process it means a test that renders a Spanish screen leaves
    Spanish active for the next test that calls model code directly, with no
    request to reset it.
    """
    yield
    translation.deactivate()


@pytest.fixture
def user(db):
    """Create the primary test user."""
    return get_user_model().objects.create_user(
        username="ada", password="correct-horse"
    )


@pytest.fixture
def other_user(db):
    """Create a second user for isolation tests."""
    return get_user_model().objects.create_user(
        username="grace", password="correct-horse"
    )


@pytest.fixture
def admin_site():
    """Return Django's default admin site."""
    from django.contrib import admin

    return admin.site


@pytest.fixture
def light_user(user):
    """Return a user whose stored preference is the light theme."""
    from todo.models import Profile

    Profile.objects.create(user=user, theme=Profile.Theme.LIGHT)
    user.refresh_from_db()
    return user


@pytest.fixture
def dark_user(user):
    """Return a user whose stored preference is the dark theme."""
    from todo.models import Profile

    Profile.objects.create(user=user, theme=Profile.Theme.DARK)
    user.refresh_from_db()
    return user
