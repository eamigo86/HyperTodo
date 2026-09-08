"""Automatic validation of routes, source precedence and unsaved Admin data."""

import json
from itertools import product
from uuid import uuid4
from xml.etree import ElementTree

import pytest
from dj_hyperview import TemplateResolver, validate_hyperview_schema
from dj_hyperview.contrib.database.models import HyperviewTemplate
from dj_hyperview.contrib.database.services import publish_template
from dj_hyperview.exceptions import TemplateValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone, translation

from tests.test_fragment_contract import (
    INVALID_FRAGMENT_URLS,
    _fragment_body,
    _requests,
    _restore,
)
from tests.test_schema_compatibility import MANIFEST, ROOT
from todo.context_processors import THEME_COOKIE
from todo.middleware import THEME_HEADER
from todo.models import Category, Profile, Task
from todo.services import issue_biometric_token

pytestmark = pytest.mark.django_db
NS = {"hv": "https://hyperview.org/hyperview"}


@pytest.fixture
def isolated_runtime(settings):
    settings.HYPERVIEW = dict(settings.HYPERVIEW)
    settings.HYPERVIEW.pop("CACHE", None)
    settings.MAILERS = {
        "default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}
    }
    assert settings.CACHES["default"]["BACKEND"].endswith("LocMemCache")


def _validate_response(response):
    assert response.status_code in {200, 201, 400, 401, 403, 404, 405, 422, 429}
    assert response.headers["Content-Type"].startswith("application/vnd.hyperview")
    value = response.content.decode("utf-8")
    validate_hyperview_schema(value)
    return ElementTree.fromstring(value)


@pytest.mark.parametrize(
    "theme,language,version,populated",
    list(
        product(
            ("light", "dark"), ("en", "es"), (None, "1.0.0", "1.2.0"), (False, True)
        )
    ),
)
def test_every_source_is_rendered_in_real_route_contexts(
    isolated_runtime, user, monkeypatch, theme, language, version, populated
):
    seen = set()
    resolve = TemplateResolver.resolve

    def track(resolver, name):
        result = resolve(resolver, name)
        seen.add(name)
        return result

    monkeypatch.setattr(TemplateResolver, "resolve", track)
    Profile.objects.create(user=user, theme=theme, language=language)
    user.first_name = 'Ada < & " >'
    user.save(update_fields=["first_name"])
    if populated:
        category = Category.objects.create(user=user, name='Home < & " >', color="mint")
        Task.objects.create(user=user, title='Task < & " >', category=category)
        Task.objects.create(user=user, title="Completed", completed_at=timezone.now())
    headers = {"accept-language": language}
    if version:
        headers["x-app-version"] = version
    client = Client(headers=headers)
    client.cookies[THEME_COOKIE] = theme
    client.force_login(user)
    for url in (
        "/hv/",
        "/hv/source-probe/",
        "/hv/about/",
        "/hv/dashboard/",
        "/hv/settings/",
        "/hv/tasks/",
        "/hv/categories/",
        "/hv/tasks/new/",
        "/hv/categories/new/",
        "/hv/tasks/?status=bogus",
    ):
        response = client.get(url)
        assert response.headers[THEME_HEADER] == theme
        _validate_response(response)
    anonymous = Client(headers=headers)
    anonymous.cookies[THEME_COOKIE] = theme
    for url in ("/hv/", "/hv/login/", "/hv/dashboard/"):
        response = anonymous.get(url)
        assert response.headers[THEME_HEADER] == theme
        _validate_response(response)

    ids = {"task": str(uuid4()), "category": str(uuid4())}
    for _label, verb, url in _requests("fragment", ids):
        _restore(user, ids)
        client.force_login(user)
        body = (
            _fragment_body(url, ids, token=issue_biometric_token(user=user))
            if verb == "post"
            else {}
        )
        _validate_response(getattr(client, verb)(url, body))
    client.force_login(user)
    for url in INVALID_FRAGMENT_URLS:
        _validate_response(client.get(url))
    for url, body in (
        ("/hv/tasks/new/", {}),
        ("/hv/categories/new/", {}),
        ("/hv/settings/", {"email": "invalid"}),
        ("/hv/login/", {"username": "ada", "password": "wrong"}),
        ("/hv/biometric/login/", {"biometric_token": "synthetic-invalid"}),
    ):
        _validate_response(client.post(url, body))
    assert set(MANIFEST) <= seen, sorted(set(MANIFEST) - seen)


@pytest.mark.parametrize("name", MANIFEST)
def test_every_source_passes_context_free_admin_validation(isolated_runtime, name):
    from dj_hyperview.contrib.database.admin_validation import validate_draft_source

    result = validate_draft_source(name, (ROOT / name).read_text())
    assert result["ok"], (name, result["diagnostics"])
    assert all(item["severity"] != "error" for item in result["diagnostics"])


@pytest.mark.parametrize(
    "theme,language", list(product(("light", "dark"), ("en", "es")))
)
def test_about_admin_validation_and_rendering_do_not_publish(
    isolated_runtime, admin_client, user, theme, language
):
    source = (ROOT / "screens/about.xml").read_text()
    publish_template("screens/about.xml", source, using="default")
    row = HyperviewTemplate.objects.get(name="screens/about.xml")
    before = (row.content, row.revision, row.active)
    draft = source.replace("HyperTodo", "Unsaved &amp; HyperTodo")
    with translation.override(language):
        response = admin_client.post(
            reverse("admin:dj_hyperview_database_hyperviewtemplate_hxml_validate"),
            data=json.dumps({"name": row.name, "content": draft}),
            content_type="application/json",
        )
    assert response.status_code == 200
    assert response.json()["ok"], response.json()
    row.refresh_from_db()
    assert (row.content, row.revision, row.active) == before
    Profile.objects.create(user=user, theme=theme, language=language)
    client = Client()
    client.force_login(user)
    root = _validate_response(client.get(reverse("todo:about")))
    assert root.find("./hv:screen/hv:styles", NS) is not None
    assert "Unsaved" not in "".join(root.itertext())


@pytest.mark.parametrize(
    "name",
    ("screens/about.xml", "screens/categories.xml", "fragments/category_list.xml"),
)
@pytest.mark.parametrize("active", (False, True))
def test_seeded_names_keep_database_precedence_and_safe_fallback(
    isolated_runtime, user, name, active
):
    source = (ROOT / name).read_text()
    modified = source.replace('id="', 'id="database-', 1)
    publish_template(name, modified, active=active, using="default")
    row = HyperviewTemplate.objects.get(name=name)
    assert TemplateResolver.from_settings().resolve(name).content == (
        modified if active else source
    )
    client = Client(headers={"x-app-version": "1.2.0"})
    client.force_login(user)
    url = "/hv/about/" if name.endswith("about.xml") else "/hv/categories/"
    if name.startswith("fragments/"):
        url += "?fragment=list"
    _validate_response(client.get(url))
    row.refresh_from_db()
    assert (row.content, row.revision, row.active) == (modified, 1, active)


@pytest.mark.parametrize(
    "xml",
    (
        '<text mystery="no">Text</text>',
        '<text ellipsizeMode="invalid">Text</text>',
        '<behavior action="show-snackbar" tone="danger"/>',
        '<behavior action="not-registered"/>',
        '<behavior action="reload" message="custom-only"/>',
        '<image style="icon" source="x" variant="unknown"/>',
        '<view variant="face"/>',
        '<text accessibilityElementsHidden="true">Flag</text>',
    ),
)
def test_invalid_corpus_is_not_made_permissive(isolated_runtime, xml):
    with pytest.raises(TemplateValidationError, match=r"\[schema\]"):
        validate_hyperview_schema(
            xml.replace(" ", ' xmlns="https://hyperview.org/hyperview" ', 1)
        )


def test_integrity_is_not_a_replacement_for_database_override_adoption(
    isolated_runtime, user
):
    import re
    from io import StringIO

    from django.core.management import call_command

    source = (ROOT / "screens/about.xml").read_text()
    legacy, count = re.subn(
        r"(<screen[^>]*>)\n  (<styles>.*?</styles>)", r"\2\n  \1", source, flags=re.S
    )
    assert count == 1
    row = HyperviewTemplate.objects.create(name="screens/about.xml", content=legacy)
    before = (row.content, row.revision, row.active)
    output = StringIO()
    call_command("check_hyperview_templates", database="default", stdout=output)
    client = Client()
    client.force_login(user)
    with pytest.raises(TemplateValidationError, match=r"\[schema\]"):
        client.get("/hv/about/")
    row.refresh_from_db()
    assert (row.content, row.revision, row.active) == before
    # Only an explicit revision-checked publication changes the effective source.
    publish_template(row.name, source, expected_revision=row.revision, using="default")
    _validate_response(client.get("/hv/about/"))
    row.refresh_from_db()
    assert row.content == source and row.revision == before[1] + 1


def test_template_seed_preserves_existing_reviewed_content(isolated_runtime):
    from todo.management.commands.seed_demo import Command

    name = "screens/about.xml"
    source = (ROOT / name).read_text().replace("HyperTodo", "Reviewed application")
    publish_template(name, source, using="default")
    before = list(
        HyperviewTemplate.objects.filter(name=name).values_list(
            "content", "revision", "active"
        )
    )
    # Only template seeding, on the ephemeral test DB; never account/data seeding.
    Command()._seed_hxml_templates()
    assert (
        list(
            HyperviewTemplate.objects.filter(name=name).values_list(
                "content", "revision", "active"
            )
        )
        == before
    )
