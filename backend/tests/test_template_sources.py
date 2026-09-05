"""Consumer acceptance tests for dj-hyperview template sources and caching."""

from uuid import uuid4
from xml.etree import ElementTree

import pytest
from dj_hyperview import TemplateResolver
from dj_hyperview.contrib.database.models import HyperviewTemplate
from dj_hyperview.contrib.database.services import publish_template
from django.conf import settings
from django.core.cache import caches
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


def test_filesystem_source_is_the_default_fallback():
    template = TemplateResolver.from_settings().resolve(NAME)
    assert "filesystem-probe" in template.content


def test_active_database_template_overrides_filesystem_immediately():
    publish_template(NAME, DATABASE_XML, using="default")
    response = Client().get(reverse("todo:source-probe"))
    root = ElementTree.fromstring(response.content)
    assert response.status_code == 200
    assert root.find(f"{{{NAMESPACE}}}screen").attrib["id"] == "database-probe"


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
            "LOCATION": "redis://127.0.0.1:6379/14",
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
        "VALIDATION": {"MODE": "publish_and_render"},
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


def test_database_template_model_is_registered_in_admin(admin_site):
    assert HyperviewTemplate in admin_site._registry
