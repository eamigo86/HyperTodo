"""After-commit app invalidation intents, without Redis or stream transport."""

import json
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Never
from unittest.mock import patch

import pytest
from dj_hyperview.contrib.database.models import HyperviewTemplate
from dj_hyperview.signals import TemplateInvalidation, template_invalidated
from django.apps import apps
from django.conf import settings as django_settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, transaction
from django.test import Client
from django.urls import reverse
from pytest_django.fixtures import (
    DjangoAssertNumQueries,
    DjangoCaptureOnCommitCallbacks,
    Settings,
)

from todo.models import Category, Task
from todo.realtime_notifications import Notification
from todo.services import create_category, create_task, delete_category, toggle_task

CONFIG = {"REDIS_URL": "redis://127.0.0.1:6379/14", "NAMESPACE": "unit-test"}
pytestmark = pytest.mark.django_db


@pytest.fixture
def cold_broker_cache() -> Iterator[None]:
    """Forget the cached brokers, so a test that counts constructions starts cold.

    get_broker is cached for the life of the process: without this the counting test
    passes only the first time its namespace is seen, and fails on a rerun or when
    another test has used the same configuration before it.

    Yields:
        Nothing; the broker cache is empty while the test runs.
    """
    from todo.realtime_config import get_broker

    get_broker.cache_clear()
    yield
    get_broker.cache_clear()


@pytest.fixture
def published(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[object, Notification]]:
    """Enable realtime and record every notification instead of publishing it.

    Args:
        settings: Django settings overridden by this test.
        monkeypatch: Patches the code under test for this test.

    Returns:
        The config and intent pairs recorded by the patched publisher.
    """
    from todo import realtime_notifications as notifications

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG.copy()}
    seen = []
    monkeypatch.setattr(
        notifications, "_publish", lambda config, intent: seen.append((config, intent))
    )
    return seen


def intents(published: list[tuple[object, Notification]]) -> list[Notification]:
    """Return only the intents of the recorded notifications.

    Args:
        published: Notifications captured instead of being published, as config and
        intent pairs.

    Returns:
        The recorded intents, in publication order.
    """
    return [intent for _, intent in published]


def test_normal_application_enables_central_realtime() -> None:
    """The normal application enables the central realtime configuration."""
    from config import settings

    assert settings.HYPERVIEW["REALTIME"] == {
        "REDIS_URL": settings.REDIS_URL,
        "NAMESPACE": "hypertodo-development",
    }


def test_services_publish_only_after_commit(
    user: AbstractUser,
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """Services publish their notification only after the transaction commits.

    Args:
        user: Signed-in user who owns the data in this test.
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    with django_capture_on_commit_callbacks(execute=True):
        task = create_task(
            user=user,
            title="Private title",
            notes="Private notes",
            category=None,
            due_at=None,
        )
        assert published == []
    from todo.realtime_notifications import private_topic

    assert len(published) == 1
    event = intents(published)[0]
    assert event.using == "default"
    assert event.topics == (private_topic("default", user.pk),)
    assert event.resources == ("tasks",)
    from todo.realtime_changes import capture_entities

    assert event.payload == {
        "version": 2,
        "resources": ["tasks"],
        "mutation_id": None,
        "entities": capture_entities("default", [("tasks", task.pk)]).payload,
    }
    assert str(task.pk) not in json.dumps(event.payload)
    assert "Private" not in repr(event)
    with pytest.raises(FrozenInstanceError):
        event.resources = ("ui",)


def test_nested_rollback_and_outer_rollback_drop_intents(
    user: AbstractUser,
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """A nested rollback and an outer rollback both drop the pending intents.

    Args:
        user: Signed-in user who owns the data in this test.
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                Task.objects.create(user=user, title="Outer rolled back")
                raise RuntimeError
        with transaction.atomic():
            with pytest.raises(RuntimeError):
                with transaction.atomic():
                    Task.objects.create(user=user, title="Inner rolled back")
                    raise RuntimeError
            Task.objects.create(user=user, title="Committed")
    assert len(published) == 1


def test_task_lifecycle_and_real_admin_delete_selected(
    user: AbstractUser,
    admin_client: Client,
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """The task lifecycle and the admin delete-selected action publish intents.

    Args:
        user: Signed-in user who owns the data in this test.
        admin_client: Client signed in as a superuser that requests the admin.
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    with django_capture_on_commit_callbacks(execute=True):
        task = create_task(
            user=user, title="Task", notes="", category=None, due_at=None
        )
        toggle_task(user=user, task_id=task.pk)
        response = admin_client.post(
            reverse("admin:todo_task_changelist"),
            {
                "action": "delete_selected",
                "_selected_action": [str(task.pk)],
                "post": "yes",
            },
        )
        assert response.status_code == 302
    assert not Task.objects.filter(pk=task.pk).exists()
    assert [i.resources for i in intents(published)] == [("tasks",)] * 3


def test_task_admin_owner_transfer_targets_old_and_new(
    user: AbstractUser,
    other_user: AbstractUser,
    admin_client: Client,
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """Transferring a task in the admin notifies the old and the new owner.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
        admin_client: Client signed in as a superuser that requests the admin.
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    task = Task.objects.create(user=user, title="Task")
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            reverse("admin:todo_task_change", args=[task.pk]),
            {
                "user": str(other_user.pk),
                "title": "Changed",
                "notes": "",
                "category": "",
                "due_at_0": "",
                "due_at_1": "",
                "completed_at_0": "",
                "completed_at_1": "",
                "_save": "Save",
            },
        )
        assert response.status_code == 302
    from todo.realtime_notifications import private_topic

    task.refresh_from_db()
    assert task.user_id == other_user.pk
    assert set(intents(published)[0].topics) == {
        private_topic("default", user.pk),
        private_topic("default", other_user.pk),
    }


@pytest.mark.parametrize(
    "fields",
    [
        lambda: ["title"],
        lambda: iter(["title"]),
        lambda: (field for field in ["title"]),
    ],
)
def test_partial_save_uses_persisted_owner_not_unsaved_memory(
    user: AbstractUser,
    other_user: AbstractUser,
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    fields: Callable[[], Iterable[str]],
) -> None:
    """A partial save targets the persisted owner, not the unsaved in-memory one.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
        fields: Factory of the update_fields iterable passed to the save.
    """
    task = Task.objects.create(user=user, title="Initial")
    task.user = other_user
    task.title = "Changed"
    with django_capture_on_commit_callbacks(execute=True):
        task.save(update_fields=fields())
    from todo.realtime_notifications import private_topic

    assert intents(published)[0].topics == (private_topic("default", user.pk),)
    task.refresh_from_db()
    assert task.user_id == user.pk


def test_delete_uses_persisted_owner_and_captures_before_pk_cleared(
    user: AbstractUser,
    other_user: AbstractUser,
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """A delete targets the persisted owner, captured before the primary key clears.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    task = Task.objects.create(user=user, title="Initial")
    task.user = other_user
    with django_capture_on_commit_callbacks(execute=True):
        task.delete()
        assert task.pk is None
    from todo.realtime_notifications import private_topic

    assert intents(published)[0].topics == (private_topic("default", user.pk),)


def test_category_delete_set_null_captures_related_task_owners(
    user: AbstractUser,
    other_user: AbstractUser,
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """Deleting a category notifies the owners of the tasks whose category it clears.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    category = Category.objects.create(user=user, name="Shared history")
    task = Task.objects.create(user=user, category=category, title="Task")
    # Existing Admin permits this transfer; do not silently repair persisted data.
    category.user = other_user
    category.save(update_fields=["user"])
    with django_capture_on_commit_callbacks(execute=True):
        delete_category(user=other_user, category_id=category.pk)
    from todo.realtime_notifications import private_topic

    task.refresh_from_db()
    assert task.category is None
    assert len(published) == 1  # SET_NULL does not emit Task.post_save.
    assert set(intents(published)[0].topics) == {
        private_topic("default", user.pk),
        private_topic("default", other_user.pk),
    }
    assert intents(published)[0].resources == ("tasks", "categories")


def test_category_admin_transfer_includes_related_owners(
    user: AbstractUser,
    other_user: AbstractUser,
    admin_client: Client,
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """Transferring a category in the admin also notifies its related task owners.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
        admin_client: Client signed in as a superuser that requests the admin.
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    category = Category.objects.create(user=user, name="Category")
    task = Task.objects.create(user=user, category=category, title="Task")
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            reverse("admin:todo_category_change", args=[category.pk]),
            {
                "user": str(other_user.pk),
                "name": "New",
                "color": "mint",
                "_save": "Save",
            },
        )
        assert response.status_code == 302
    from todo.realtime_notifications import private_topic

    assert set(intents(published)[0].topics) == {
        private_topic("default", user.pk),
        private_topic("default", other_user.pk),
    }
    assert intents(published)[0].resources == ("categories",)
    task.refresh_from_db()
    assert task.user_id == user.pk
    assert task.category_id == category.pk


def test_category_create_and_update_only_categories(
    user: AbstractUser,
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """Creating and updating a category invalidates only categories.

    Args:
        user: Signed-in user who owns the data in this test.
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    with django_capture_on_commit_callbacks(execute=True):
        category = create_category(user=user, name="Category", color="mint")
        category.name = "New"
        category.save(update_fields=["name"])
    assert [i.resources for i in intents(published)] == [("categories",)] * 2


def test_disabled_preserves_query_count_and_never_publishes(
    user: AbstractUser,
    settings: Settings,
    published: list[tuple[object, Notification]],
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    """With realtime disabled, the query count is unchanged and nothing is published.

    Args:
        user: Signed-in user who owns the data in this test.
        settings: Django settings overridden by this test.
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_assert_num_queries: Asserts the exact number of queries the block runs.
    """
    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": None}
    with django_assert_num_queries(1):
        task = Task.objects.create(user=user, title="Disabled")
    task.title = "Changed"
    with django_assert_num_queries(1):
        task.save(update_fields=["title"])
    assert published == []


def test_raw_fixture_save_does_not_notify(
    user: AbstractUser,
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """A raw fixture save does not notify.

    Args:
        user: Signed-in user who owns the data in this test.
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    task = Task(
        user=user, title="Raw", created_at=user.date_joined, updated_at=user.date_joined
    )
    with django_capture_on_commit_callbacks(execute=True):
        task.save_base(raw=True)
    assert published == []


def test_public_template_signal_only_ui_no_name_payload(
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """The public template signal invalidates only ui and carries no template name.

    Args:
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    with django_capture_on_commit_callbacks(execute=True):
        template_invalidated.send(
            sender=HyperviewTemplate,
            event=TemplateInvalidation(
                names=frozenset({"private/secret.xml"}), using="tenant:a"
            ),
        )
    from todo.realtime_notifications import ui_topic

    event = intents(published)[0]
    assert event.using == "tenant:a"
    assert event.topics == (ui_topic("tenant:a"),)
    assert event.payload == {"version": 1, "resources": ["ui"]}
    assert "secret" not in repr(event)


def test_template_model_emits_when_cache_disabled(
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """Template model changes still notify when the cache is disabled.

    Args:
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    assert "CACHE" not in django_settings.HYPERVIEW
    with django_capture_on_commit_callbacks(execute=True):
        HyperviewTemplate.objects.create(
            name="test.xml",
            content=(
                '<doc xmlns="https://hyperview.org/hyperview">'
                "<screen><body /></screen></doc>"
            ),
        )
    assert [i.resources for i in intents(published)] == [("ui",)]


def test_signal_rejects_unrelated_sender_and_payload(
    published: list[tuple[object, Notification]],
) -> None:
    """The template signal ignores an unrelated sender and payload.

    Args:
        published: Notifications captured instead of being published, as config and
        intent pairs.
    """
    template_invalidated.send(
        sender=Task, event=TemplateInvalidation(names=frozenset(), using="default")
    )
    template_invalidated.send(
        sender=HyperviewTemplate, event={"names": ["test.xml"], "using": "default"}
    )
    assert published == []


def test_topic_components_are_delimited_and_alias_scoped() -> None:
    """Topic components are delimited and scoped to the database alias."""
    from todo.realtime_notifications import private_topic, ui_topic

    values = {
        private_topic("a:b", "c"),
        private_topic("a", "b:c"),
        private_topic("default", "1"),
        private_topic("other", "1"),
        ui_topic("default"),
        ui_topic("other"),
    }
    assert len(values) == 6
    assert all("\n" not in t and "*" not in t for t in values)


def test_callback_copies_values_and_alias_before_mutation(
    published: list[tuple[object, Notification]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The commit callback copies its values and alias, so later mutation cannot leak.

    Args:
        published: Notifications captured instead of being published, as config and
        intent pairs.
        monkeypatch: Patches the code under test for this test.
    """
    from todo.realtime_notifications import notify_after_commit, private_topic

    callbacks = []
    monkeypatch.setattr(
        transaction,
        "on_commit",
        lambda func, using=None, robust=False: callbacks.append((using, func)),
    )
    owners = {1}
    resources = ["tasks"]
    notify_after_commit(using="tenant", owners=owners, resources=resources)
    owners.add(2)
    resources.append("ui")
    assert published == []
    assert callbacks[0][0] == "tenant"
    callbacks[0][1]()
    assert intents(published)[0].topics == (private_topic("tenant", 1),)
    assert intents(published)[0].resources == ("tasks",)


def test_publisher_failure_does_not_revert_committed_business(
    user: AbstractUser,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """A failing publisher does not revert the committed business change.

    Args:
        user: Signed-in user who owns the data in this test.
        settings: Django settings overridden by this test.
        monkeypatch: Patches the code under test for this test.
        caplog: Captures the log records emitted by this test.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    from todo import realtime_notifications as notifications

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG.copy()}

    def fail(config: object, intent: Notification) -> Never:
        raise RuntimeError("SECRET redis://credentials@host and owner")

    monkeypatch.setattr(notifications, "_publish", fail)
    with django_capture_on_commit_callbacks(execute=True):
        task = Task.objects.create(user=user, title="Committed")
    assert Task.objects.filter(pk=task.pk).exists()
    assert "realtime-publication-failed" in caplog.text
    assert "SECRET" not in caplog.text
    assert "credentials" not in caplog.text


def test_real_publisher_calls_public_broker_not_a_success_stub(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real publisher calls the public broker instead of a success stub.

    Args:
        settings: Django settings overridden by this test.
        monkeypatch: Patches the code under test for this test.
    """
    from dj_hyperview.realtime import RedisBroker

    from todo.realtime_config import get_realtime_config
    from todo.realtime_notifications import Notification, _publish

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG.copy()}
    seen = []

    def publish(
        broker: RedisBroker,
        event: dict[str, object],
        topics: Sequence[str],
        *,
        using: str,
    ) -> None:
        seen.append((event, topics, using))

    monkeypatch.setattr(RedisBroker, "publish_after_commit", publish)
    _publish(get_realtime_config(), Notification("default", ("topic",), ("tasks",)))
    assert seen == [
        (
            {"event": "invalidate", "data": {"version": 1, "resources": ["tasks"]}},
            ("topic",),
            "default",
        )
    ]


def test_one_broker_serves_every_publish_and_every_stream_of_a_configuration(
    settings: Settings,
) -> None:
    """One broker serves every publish and every stream of a configuration.

    Args:
        settings: Django settings overridden by this test.
    """
    from todo.realtime_config import get_broker, get_realtime_config
    from todo.realtime_views import _broker

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG.copy()}
    config = get_realtime_config()

    assert _broker(config) is _broker(config) is get_broker(config)

    # An equal configuration read again is still the same one.
    assert get_broker(get_realtime_config()) is get_broker(config)


def test_the_broker_is_constructed_once_not_per_publish_and_per_stream(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, cold_broker_cache: None
) -> None:
    """The broker is constructed once, not once per publish and per stream.

    Args:
        settings: Django settings overridden by this test.
        monkeypatch: Patches the code under test for this test.
        cold_broker_cache: Forgets the cached brokers before and after the test.
    """
    from dj_hyperview.realtime import RedisBroker

    from todo.realtime_config import get_realtime_config
    from todo.realtime_notifications import Notification, _publish
    from todo.realtime_views import _broker

    settings.HYPERVIEW = {
        **settings.HYPERVIEW,
        "REALTIME": {**CONFIG, "NAMESPACE": "built-once"},
    }
    built = []
    real_init = RedisBroker.__init__

    def counting_init(broker: RedisBroker, url: str | None, namespace: str) -> None:
        built.append(namespace)
        real_init(broker, url, namespace)

    monkeypatch.setattr(RedisBroker, "__init__", counting_init)
    monkeypatch.setattr(RedisBroker, "publish_after_commit", lambda *a, **k: None)
    config = get_realtime_config()

    for _ in range(3):
        _publish(config, Notification("default", ("topic",), ("tasks",)))
        _broker(config)

    assert built == ["built-once"]


def test_a_different_configuration_gets_its_own_broker(settings: Settings) -> None:
    """A different configuration gets its own broker.

    Args:
        settings: Django settings overridden by this test.
    """
    from todo.realtime_config import get_broker, get_realtime_config

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG.copy()}
    first = get_broker(get_realtime_config())
    settings.HYPERVIEW = {
        **settings.HYPERVIEW,
        "REALTIME": {**CONFIG, "NAMESPACE": "another-unit-test"},
    }
    second = get_broker(get_realtime_config())

    assert second is not first
    assert second._config.namespace == "another-unit-test"


def test_publishing_reuses_the_cached_broker(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publishing reuses the cached broker.

    Args:
        settings: Django settings overridden by this test.
        monkeypatch: Patches the code under test for this test.
    """
    from dj_hyperview.realtime import RedisBroker

    from todo.realtime_config import get_broker, get_realtime_config
    from todo.realtime_notifications import Notification, _publish

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG.copy()}
    config = get_realtime_config()
    used = []
    monkeypatch.setattr(
        RedisBroker,
        "publish_after_commit",
        lambda broker, event, topics, *, using: used.append(broker),
    )

    for _ in range(3):
        _publish(config, Notification("default", ("topic",), ("tasks",)))

    assert len(used) == 3
    assert all(broker is get_broker(config) for broker in used)


@pytest.mark.parametrize(
    "value",
    [
        {},
        True,
        {"REDIS_URL": CONFIG["REDIS_URL"]},
        {**CONFIG, "extra": True},
        {**CONFIG, "REDIS_URL": "https://example.com"},
        {**CONFIG, "NAMESPACE": ""},
        {**CONFIG, "NAMESPACE": "unsafe:*"},
    ],
)
def test_invalid_configuration_rejected_without_network(
    settings: Settings, value: object
) -> None:
    """An invalid configuration is rejected without any network use.

    Args:
        settings: Django settings overridden by this test.
        value: Realtime configuration under test.
    """
    from todo.realtime_config import get_realtime_config

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": value}
    with pytest.raises(ImproperlyConfigured, match="REALTIME"):
        get_realtime_config()


def test_valid_configuration_does_not_expose_url_and_freezes(
    settings: Settings,
) -> None:
    """A valid configuration neither exposes its URL nor stays mutable.

    Args:
        settings: Django settings overridden by this test.
    """
    from todo.realtime_config import get_realtime_config

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG.copy()}
    config = get_realtime_config()
    assert config.redis_url == CONFIG["REDIS_URL"]
    assert config.namespace == "unit-test"
    assert "redis://" not in repr(config)
    with pytest.raises(FrozenInstanceError):
        config.namespace = "other"


def test_ready_idempotent_without_redis_database_or_cache(
    user: AbstractUser,
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """Running ready twice is harmless and needs no Redis, database or cache.

    Args:
        user: Signed-in user who owns the data in this test.
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    from django.db.backends.base.base import BaseDatabaseWrapper

    app = apps.get_app_config("todo")
    with (
        patch.object(
            BaseDatabaseWrapper,
            "ensure_connection",
            side_effect=AssertionError("SQL during ready"),
        ),
        patch("builtins.__import__", wraps=__import__) as imports,
    ):
        app.ready()
        app.ready()
    assert not any(
        str(c.args[0]).split(".")[0] in {"redis", "django_redis"}
        for c in imports.call_args_list
    )
    with django_capture_on_commit_callbacks(execute=True):
        Task.objects.create(user=user, title="Once")
    assert len(published) == 1


def test_actual_other_alias_commit_and_rollback_do_not_use_default(
    tmp_path: Path,
) -> None:
    """Commit and rollback on another database alias do not involve the default alias.

    Args:
        tmp_path: Temporary directory that holds the SQLite file of the second database
        alias.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    code = """
import django
django.setup()
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import DatabaseError, transaction
from todo.models import Task
from todo import realtime_notifications as n
from dj_hyperview.contrib.database.models import HyperviewTemplate
seen = []
n._publish = lambda config, intent: seen.append(intent)
for alias in ("default", "other"):
    call_command("migrate", database=alias, verbosity=0, interactive=False)
owner = get_user_model().objects.db_manager("other").create_user(username="Synthetic")
with transaction.atomic(using="other"):
    Task.objects.using("other").create(user=owner, title="Other alias")
    assert not seen
assert len(seen) == 1
assert seen[0].using == "other"
assert seen[0].topics == (n.private_topic("other", owner.pk),)
assert not Task.objects.using("default").exists()
try:
    with transaction.atomic(using="other"):
        Task.objects.using("other").create(user=owner, title="Rollback")
        raise RuntimeError
except RuntimeError:
    pass
assert len(seen) == 1
with transaction.atomic(using="other"):
    HyperviewTemplate.objects.using("other").create(
        name="test.xml",
        content=('<doc xmlns="https://hyperview.org/hyperview">'
                 '<screen><body /></screen></doc>'),
    )
    assert len(seen) == 1
assert seen[1].topics == (n.ui_topic("other"),)
assert seen[1].using == "other"
print("two independent SQLite aliases: committed scope and rollback verified")
"""
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "tests.settings_realtime_aliases",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=Path(__file__).parents[1],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "two independent SQLite aliases" in result.stdout


def test_empty_owners_do_not_publish_and_invalid_resources_fail(
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """An empty owner list publishes nothing, and invalid resources fail.

    Args:
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    from todo.realtime_notifications import notify_after_commit

    with django_capture_on_commit_callbacks(execute=True):
        notify_after_commit(using="default", owners=(), resources=("tasks",))
    assert published == []
    for resources in ((), ("unknown",), ("tasks", "unknown")):
        with pytest.raises(ValueError, match="resources"):
            notify_after_commit(using="default", owners=(1,), resources=resources)


def test_direct_disabled_notifications_and_template_signal_are_inert(
    settings: Settings, published: list[tuple[object, Notification]]
) -> None:
    """Direct notifications and the template signal are inert while realtime is off.

    Args:
        settings: Django settings overridden by this test.
        published: Notifications captured instead of being published, as config and
        intent pairs.
    """
    from todo.realtime_notifications import notify_after_commit

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": None}
    notify_after_commit(using="default", owners=(1,), resources=("tasks",))
    template_invalidated.send(
        sender=HyperviewTemplate,
        event=TemplateInvalidation(names=frozenset({"test.xml"}), using="default"),
    )
    assert published == []


@pytest.mark.parametrize(
    "url",
    [
        None,
        "redis://host:abc",
        "redis://host:0",
        "redis://host:65536",
        "redis://host#fragment",
    ],
)
def test_invalid_redis_location_is_rejected_without_disclosing_it(
    settings: Settings, url: str | None
) -> None:
    """An invalid Redis location is rejected without disclosing it.

    Args:
        settings: Django settings overridden by this test.
        url: Redis location under test, or None when it is missing.
    """
    from todo.realtime_config import get_realtime_config

    settings.HYPERVIEW = {
        **settings.HYPERVIEW,
        "REALTIME": {**CONFIG, "REDIS_URL": url},
    }
    with pytest.raises(ImproperlyConfigured, match="REALTIME"):
        get_realtime_config()


def test_save_failure_does_not_reuse_snapshot_after_disable(
    user: AbstractUser,
    other_user: AbstractUser,
    settings: Settings,
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """A failed save does not reuse its snapshot after realtime is disabled.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
        settings: Django settings overridden by this test.
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    task = Task.objects.create(user=user, title="Task")
    with django_capture_on_commit_callbacks(execute=True):
        task.pk = "00000000-0000-0000-0000-000000000000"
        with pytest.raises(DatabaseError, match="did not affect any rows"):
            with transaction.atomic():
                task.save(force_update=True)
        settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": None}
        task.user = other_user
        task.save()
    assert published == []


def test_category_partial_owner_change_does_not_notify_unwritten_owner(
    user: AbstractUser,
    other_user: AbstractUser,
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """A partial category save does not notify an owner whose change was not written.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    category = Category.objects.create(user=user, name="Initial")
    category.user = other_user
    category.name = "New"
    with django_capture_on_commit_callbacks(execute=True):
        category.save(update_fields=(f for f in ["name"]))
    from todo.realtime_notifications import private_topic

    assert intents(published)[0].topics == (private_topic("default", user.pk),)
    category.refresh_from_db()
    assert category.user_id == user.pk


def test_bulk_sql_is_explicitly_outside_automatic_notifications(
    user: AbstractUser,
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """Bulk SQL writes are explicitly outside the automatic notifications.

    Args:
        user: Signed-in user who owns the data in this test.
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    task = Task.objects.create(user=user, title="Task")
    with django_capture_on_commit_callbacks(execute=True):
        assert Task.objects.filter(pk=task.pk).update(title="Direct SQL") == 1
    assert published == []


def test_category_admin_bulk_delete_notifies_affected_task_owners(
    user: AbstractUser,
    admin_client: Client,
    published: list[tuple[object, Notification]],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """The admin bulk delete of categories notifies the affected task owners.

    Args:
        user: Signed-in user who owns the data in this test.
        admin_client: Client signed in as a superuser that requests the admin.
        published: Notifications captured instead of being published, as config and
        intent pairs.
        django_capture_on_commit_callbacks: Captures and runs the on_commit callbacks of
        this test.
    """
    category = Category.objects.create(user=user, name="Category")
    task = Task.objects.create(user=user, category=category, title="Task")
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            reverse("admin:todo_category_changelist"),
            {
                "action": "delete_selected",
                "_selected_action": [str(category.pk)],
                "post": "yes",
            },
        )
        assert response.status_code == 302
    task.refresh_from_db()
    assert task.category is None
    assert [i.resources for i in intents(published)] == [("tasks", "categories")]
