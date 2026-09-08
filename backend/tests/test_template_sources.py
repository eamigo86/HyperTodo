"""Consumer acceptance tests for dj-hyperview template sources and caching."""

import multiprocessing
import os
from uuid import uuid4
from xml.etree import ElementTree

import pytest
from dj_hyperview import TemplateResolver
from dj_hyperview.cache import TemplateCache
from dj_hyperview.contrib.database.models import HyperviewTemplate
from dj_hyperview.contrib.database.services import delete_template, publish_template
from django.conf import settings
from django.core.cache import caches
from django.db import connections, transaction
from django.test import Client, override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db
NAMESPACE = "https://hyperview.org/hyperview"
NAME = "screens/source_probe.xml"
DATABASE_XML = (
    f'<?xml version="1.0" encoding="UTF-8"?><doc xmlns="{NAMESPACE}">'
    '<screen id="database-probe"><body><text>Database source</text></body>'
    "</screen></doc>"
)
UPDATED_DATABASE_XML = DATABASE_XML.replace("Database source", "Updated source")
ROLLED_BACK_XML = DATABASE_XML.replace("Database source", "Rolled back source")


def _shared_cache_reader(channel):
    """Resolve commands in a long-lived process with independent connections."""
    connections.close_all()
    caches.close_all()
    try:
        while True:
            command = channel.recv()
            if command == "stop":
                return
            if command == "resolve":
                value = TemplateResolver.from_settings().resolve(NAME).content
            elif command == "generation":
                namespace = settings.HYPERVIEW["CACHE"]["NAMESPACE"]
                value = TemplateCache.from_settings(namespace).generation(NAME)
            else:
                raise ValueError("unknown worker command")
            channel.send(("ok", value))
    except BaseException as error:
        channel.send(("error", f"{type(error).__name__}: {error}"))
    finally:
        connections.close_all()
        caches.close_all()
        channel.close()


def _worker_value(channel, command):
    channel.send(command)
    assert channel.poll(10), f"Redis worker timed out during {command}"
    state, value = channel.recv()
    assert state == "ok", value
    return value


def test_filesystem_source_is_the_default_fallback():
    template = TemplateResolver.from_settings().resolve(NAME)
    assert "filesystem-probe" in template.content


def test_active_database_template_overrides_filesystem_immediately():
    publish_template(NAME, DATABASE_XML, using="default")
    response = Client().get(reverse("todo:source-probe"))
    root = ElementTree.fromstring(response.content)
    assert response.status_code == 200
    assert root.find(f"{{{NAMESPACE}}}screen").attrib["id"] == "database-probe"


def test_database_overrides_categories_document_and_refresh_fragment(user):
    document_name = "screens/categories.xml"
    fragment_name = "fragments/category_list.xml"
    document = (
        (settings.BASE_DIR / "hyperview" / document_name)
        .read_text(encoding="utf-8")
        .replace('id="categories-screen"', 'id="database-categories-screen"', 1)
    )
    fragment = (
        (settings.BASE_DIR / "hyperview" / fragment_name)
        .read_text(encoding="utf-8")
        .replace('id="category-list"', 'id="database-category-list"', 1)
    )
    publish_template(document_name, document, using="default")
    publish_template(fragment_name, fragment, using="default")
    client = Client(headers={"x-app-version": "1.2.0"})
    client.force_login(user)

    screen = ElementTree.fromstring(client.get(reverse("todo:categories")).content)
    refreshed = ElementTree.fromstring(
        client.get(reverse("todo:categories"), {"fragment": "list"}).content
    )

    assert screen.find(f"{{{NAMESPACE}}}screen").attrib["id"] == (
        "database-categories-screen"
    )
    assert refreshed.attrib["id"] == "database-category-list"


def test_inactive_database_template_falls_through_to_filesystem():
    publish_template(NAME, DATABASE_XML, active=False, using="default")
    response = Client().get(reverse("todo:source-probe"))
    assert b"filesystem-probe" in response.content


def test_locmem_cache_is_invalidated_after_database_publication():
    hyperview = {
        **settings.HYPERVIEW,
        "CACHE": {
            "ALIAS": "default",
            "NAMESPACE": f"dj-hyperview-test-locmem:{uuid4().hex}",
            "TTL": 30,
            "NEGATIVE_TTL": 2,
            "FAILURE_MODE": "raise",
        },
    }
    with override_settings(HYPERVIEW=hyperview):
        assert (
            "filesystem-probe" in TemplateResolver.from_settings().resolve(NAME).content
        )
        publish_template(NAME, DATABASE_XML, using="default")
        assert (
            "database-probe" in TemplateResolver.from_settings().resolve(NAME).content
        )


@pytest.mark.redis
def test_existing_redis_service_uses_isolated_namespace_without_flushing():
    namespace = f"dj-hyperview-test-tests:{uuid4().hex}"
    redis_cache = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": os.environ.get(
                "HYPERTODO_REDIS_TEST_URL",
                "redis://127.0.0.1:6379/14",
            ),
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
            "KEY_PREFIX": namespace,
        }
    }
    hyperview = {
        "TEMPLATE_DIRS": [
            __import__("django.conf").conf.settings.BASE_DIR / "hyperview"
        ],
        "SOURCES": [
            {
                "BACKEND": "dj_hyperview.contrib.database.sources.DatabaseSource",
                "OPTIONS": {"using": "default"},
            },
            {"BACKEND": "dj_hyperview.sources.FileSystemSource"},
        ],
        "CACHE": {
            "ALIAS": "default",
            "NAMESPACE": namespace,
            "TTL": 30,
            "NEGATIVE_TTL": 2,
            "FAILURE_MODE": "raise",
        },
    }
    with override_settings(CACHES=redis_cache, HYPERVIEW=hyperview):
        try:
            caches["default"].set("connectivity", "ok", timeout=5)
        except Exception as error:
            pytest.skip(f"Existing Redis service is unavailable: {error}")
        assert (
            "filesystem-probe" in TemplateResolver.from_settings().resolve(NAME).content
        )
        publish_template(NAME, DATABASE_XML, using="default")
        assert (
            "database-probe" in TemplateResolver.from_settings().resolve(NAME).content
        )
        caches["default"].delete("connectivity")


@pytest.mark.redis
@pytest.mark.django_db(transaction=True)
@pytest.mark.filterwarnings(
    "ignore:Overriding setting DATABASES can lead to unexpected behavior.:UserWarning"
)
def test_redis_shares_committed_mutations_and_preserves_rollback_across_processes(
    tmp_path,
    django_db_blocker,
):
    if os.environ.get("HYPERTODO_REDIS_INTEGRATION") != "1":
        pytest.skip("Redis multi-process acceptance is explicitly opt-in")
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("Redis multi-process acceptance requires a POSIX fork context")

    namespace = f"hypertodo-processes:{uuid4().hex}"
    redis_url = os.environ.get(
        "HYPERTODO_REDIS_TEST_URL",
        "redis://127.0.0.1:6379/14",
    )
    redis_cache = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": redis_url,
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
            "KEY_PREFIX": namespace,
        }
    }
    databases = {
        **settings.DATABASES,
        "shared": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": tmp_path / "shared.sqlite3",
        },
    }
    hyperview = {
        **settings.HYPERVIEW,
        "SOURCES": [
            {
                "BACKEND": "dj_hyperview.contrib.database.sources.DatabaseSource",
                "OPTIONS": {"using": "shared"},
            },
            {"BACKEND": "dj_hyperview.sources.FileSystemSource"},
        ],
        "CACHE": {
            "ALIAS": "default",
            "NAMESPACE": namespace,
            "TTL": 60,
            "NEGATIVE_TTL": 5,
            "FAILURE_MODE": "raise",
        },
    }

    original_connection_settings = connections._settings
    with (
        override_settings(
            CACHES=redis_cache,
            DATABASES=databases,
            HYPERVIEW=hyperview,
        ),
        django_db_blocker.unblock(),
    ):
        connections._settings = settings.DATABASES
        connections.__dict__.pop("settings", None)
        with connections["shared"].schema_editor() as schema_editor:
            schema_editor.create_model(HyperviewTemplate)
        try:
            caches["default"].set("connectivity", "ok", timeout=5)
        except Exception as error:
            pytest.skip(f"Redis integration service is unavailable: {error}")
        connections.close_all()
        caches.close_all()
        parent, child = multiprocessing.get_context("fork").Pipe()
        worker = multiprocessing.get_context("fork").Process(
            target=_shared_cache_reader,
            args=(child,),
        )
        worker.start()
        child.close()
        try:
            assert "filesystem-probe" in _worker_value(parent, "resolve")
            initial_generation = _worker_value(parent, "generation")

            publish_template(NAME, DATABASE_XML, using="shared")
            published_generation = _worker_value(parent, "generation")

            assert published_generation != initial_generation
            assert "database-probe" in _worker_value(parent, "resolve")

            template = HyperviewTemplate.objects.using("shared").get(name=NAME)
            with transaction.atomic(using="shared"):
                template.content = ROLLED_BACK_XML
                template.revision += 1
                template.save(using="shared")
                transaction.set_rollback(True, using="shared")

            assert _worker_value(parent, "generation") == published_generation
            resolved_after_rollback = _worker_value(parent, "resolve")
            assert "database-probe" in resolved_after_rollback
            assert "Rolled back source" not in resolved_after_rollback

            publish_template(
                NAME,
                UPDATED_DATABASE_XML,
                expected_revision=1,
                using="shared",
            )
            updated_generation = _worker_value(parent, "generation")
            assert updated_generation != published_generation
            assert "Updated source" in _worker_value(parent, "resolve")

            delete_template(NAME, expected_revision=2, using="shared")
            deleted_generation = _worker_value(parent, "generation")
            assert deleted_generation != updated_generation
            assert "filesystem-probe" in _worker_value(parent, "resolve")
        finally:
            if worker.is_alive():
                parent.send("stop")
            worker.join(timeout=10)
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
            parent.close()
            caches["default"].delete("connectivity")
            connections.close_all()
            connections._settings = original_connection_settings
            connections.__dict__.pop("settings", None)


def test_database_template_model_is_registered_in_admin(admin_site):
    assert HyperviewTemplate in admin_site._registry
