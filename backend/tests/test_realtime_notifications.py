"""After-commit app invalidation intents, without Redis or stream transport."""

import json
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest
from dj_hyperview.contrib.database.models import HyperviewTemplate
from dj_hyperview.signals import TemplateInvalidation, template_invalidated
from django.apps import apps
from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, transaction
from django.urls import reverse

from todo.models import Category, Task
from todo.services import create_category, create_task, delete_category, toggle_task

CONFIG = {"REDIS_URL": "redis://127.0.0.1:6379/14", "NAMESPACE": "unit-test"}
pytestmark = pytest.mark.django_db


@pytest.fixture
def published(settings, monkeypatch):
    from todo import realtime_notifications as notifications

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG.copy()}
    seen = []
    monkeypatch.setattr(
        notifications, "_publish", lambda config, intent: seen.append((config, intent))
    )
    return seen


def intents(published):
    return [intent for _, intent in published]


def test_normal_application_enables_central_realtime():
    from config import settings

    assert settings.HYPERVIEW["REALTIME"] == {
        "REDIS_URL": settings.REDIS_URL,
        "NAMESPACE": "hypertodo-development",
    }


def test_services_publish_only_after_commit(
    user, published, django_capture_on_commit_callbacks
):
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
    user, published, django_capture_on_commit_callbacks
):
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
    user, admin_client, published, django_capture_on_commit_callbacks
):
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
    user, other_user, admin_client, published, django_capture_on_commit_callbacks
):
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
    user, other_user, published, django_capture_on_commit_callbacks, fields
):
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
    user, other_user, published, django_capture_on_commit_callbacks
):
    task = Task.objects.create(user=user, title="Initial")
    task.user = other_user
    with django_capture_on_commit_callbacks(execute=True):
        task.delete()
        assert task.pk is None
    from todo.realtime_notifications import private_topic

    assert intents(published)[0].topics == (private_topic("default", user.pk),)


def test_category_delete_set_null_captures_related_task_owners(
    user, other_user, published, django_capture_on_commit_callbacks
):
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
    user, other_user, admin_client, published, django_capture_on_commit_callbacks
):
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
    user, published, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        category = create_category(user=user, name="Category", color="mint")
        category.name = "New"
        category.save(update_fields=["name"])
    assert [i.resources for i in intents(published)] == [("categories",)] * 2


def test_disabled_preserves_query_count_and_never_publishes(
    user, settings, published, django_assert_num_queries
):
    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": None}
    with django_assert_num_queries(1):
        task = Task.objects.create(user=user, title="Disabled")
    task.title = "Changed"
    with django_assert_num_queries(1):
        task.save(update_fields=["title"])
    assert published == []


def test_raw_fixture_save_does_not_notify(
    user, published, django_capture_on_commit_callbacks
):
    task = Task(
        user=user, title="Raw", created_at=user.date_joined, updated_at=user.date_joined
    )
    with django_capture_on_commit_callbacks(execute=True):
        task.save_base(raw=True)
    assert published == []


def test_public_template_signal_only_ui_no_name_payload(
    published, django_capture_on_commit_callbacks
):
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
    published, django_capture_on_commit_callbacks
):
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


def test_signal_rejects_unrelated_sender_and_payload(published):
    template_invalidated.send(
        sender=Task, event=TemplateInvalidation(names=frozenset(), using="default")
    )
    template_invalidated.send(
        sender=HyperviewTemplate, event={"names": ["test.xml"], "using": "default"}
    )
    assert published == []


def test_topic_components_are_delimited_and_alias_scoped():
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


def test_callback_copies_values_and_alias_before_mutation(published, monkeypatch):
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
    user, settings, monkeypatch, caplog, django_capture_on_commit_callbacks
):
    from todo import realtime_notifications as notifications

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG.copy()}

    def fail(config, intent):
        raise RuntimeError("SECRET redis://credentials@host and owner")

    monkeypatch.setattr(notifications, "_publish", fail)
    with django_capture_on_commit_callbacks(execute=True):
        task = Task.objects.create(user=user, title="Committed")
    assert Task.objects.filter(pk=task.pk).exists()
    assert "realtime-publication-failed" in caplog.text
    assert "SECRET" not in caplog.text
    assert "credentials" not in caplog.text


def test_real_publisher_calls_public_broker_not_a_success_stub(settings, monkeypatch):
    from dj_hyperview.realtime import RedisBroker

    from todo.realtime_config import get_realtime_config
    from todo.realtime_notifications import Notification, _publish

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG.copy()}
    seen = []

    def publish(broker, event, topics, *, using):
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
def test_invalid_configuration_rejected_without_network(settings, value):
    from todo.realtime_config import get_realtime_config

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": value}
    with pytest.raises(ImproperlyConfigured, match="REALTIME"):
        get_realtime_config()


def test_valid_configuration_does_not_expose_url_and_freezes(settings):
    from todo.realtime_config import get_realtime_config

    settings.HYPERVIEW = {**settings.HYPERVIEW, "REALTIME": CONFIG.copy()}
    config = get_realtime_config()
    assert config.redis_url == CONFIG["REDIS_URL"]
    assert config.namespace == "unit-test"
    assert "redis://" not in repr(config)
    with pytest.raises(FrozenInstanceError):
        config.namespace = "other"


def test_ready_idempotent_without_redis_database_or_cache(
    user, published, django_capture_on_commit_callbacks
):
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


def test_actual_other_alias_commit_and_rollback_do_not_use_default(tmp_path):
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
    published, django_capture_on_commit_callbacks
):
    from todo.realtime_notifications import notify_after_commit

    with django_capture_on_commit_callbacks(execute=True):
        notify_after_commit(using="default", owners=(), resources=("tasks",))
    assert published == []
    for resources in ((), ("unknown",), ("tasks", "unknown")):
        with pytest.raises(ValueError, match="resources"):
            notify_after_commit(using="default", owners=(1,), resources=resources)


def test_direct_disabled_notifications_and_template_signal_are_inert(
    settings, published
):
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
def test_invalid_redis_location_is_rejected_without_disclosing_it(settings, url):
    from todo.realtime_config import get_realtime_config

    settings.HYPERVIEW = {
        **settings.HYPERVIEW,
        "REALTIME": {**CONFIG, "REDIS_URL": url},
    }
    with pytest.raises(ImproperlyConfigured, match="REALTIME"):
        get_realtime_config()


def test_save_failure_does_not_reuse_snapshot_after_disable(
    user, other_user, settings, published, django_capture_on_commit_callbacks
):
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
    user, other_user, published, django_capture_on_commit_callbacks
):
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
    user, published, django_capture_on_commit_callbacks
):
    task = Task.objects.create(user=user, title="Task")
    with django_capture_on_commit_callbacks(execute=True):
        assert Task.objects.filter(pk=task.pk).update(title="Direct SQL") == 1
    assert published == []


def test_category_admin_bulk_delete_notifies_affected_task_owners(
    user, admin_client, published, django_capture_on_commit_callbacks
):
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
