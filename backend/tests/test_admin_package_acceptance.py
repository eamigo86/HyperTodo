"""Consumer acceptance for the database-template Admin integration."""

import json

import pytest
from dj_hyperview.contrib.database.models import HyperviewTemplate
from django.conf import settings
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils.html import escape


@pytest.mark.django_db
def test_real_template_survives_admin_save_and_reopen(admin_client):
    source = (
        (settings.BASE_DIR / "hyperview/screens/about.xml")
        .read_text(encoding="utf-8")
        .rstrip("\n")
    )
    template = HyperviewTemplate.objects.create(
        name="screens/admin-roundtrip.xml",
        content=source,
    )
    url = reverse(
        "admin:dj_hyperview_database_hyperviewtemplate_change",
        args=[template.pk],
    )

    saved = admin_client.post(
        url,
        {
            "name": template.name,
            "content": source,
            "active": "on",
            "expected_revision": "1",
            "_continue": "Save and continue editing",
        },
    )
    reopened = admin_client.get(url)

    assert saved.status_code == 302
    template.refresh_from_db()
    assert template.content == source
    assert template.revision == 2
    assert reopened.status_code == 200
    assert reopened.context["adminform"].form.initial["content"] == source


@pytest.mark.django_db
@pytest.mark.parametrize(
    "name,marker",
    [
        ("screens/about.xml", b"about-screen"),
        ("partials/about_content.xml", b"about-app-version"),
    ],
)
def test_view_only_user_sees_real_template_without_edit_controls(
    client, django_user_model, name, marker
):
    source = (settings.BASE_DIR / "hyperview" / name).read_text(encoding="utf-8")
    template = HyperviewTemplate.objects.create(
        name="screens/admin-read-only.xml",
        content=source,
    )
    reader = django_user_model.objects.create_user(
        username="template-reader",
        password="secret",
        is_staff=True,
    )
    reader.user_permissions.add(
        Permission.objects.get(
            content_type__app_label=HyperviewTemplate._meta.app_label,
            codename="view_hyperviewtemplate",
        )
    )
    client.force_login(reader)
    url = reverse(
        "admin:dj_hyperview_database_hyperviewtemplate_change",
        args=[template.pk],
    )

    response = client.get(url)

    assert response.status_code == 200
    assert response.context["has_change_permission"] is False
    assert response.context["has_delete_permission"] is False
    assert "content" not in response.context["adminform"].form.fields
    assert b'name="_save"' not in response.content
    assert b'class="deletelink"' not in response.content
    assert b"djhv-format-hxml" not in response.content
    assert b"{% load i18n %}" in response.content
    # The app-version text moved into the single shared partial. Both real
    # sources must remain fully visible, escaped and non-editable to this role.
    for line in source.splitlines():
        assert escape(line).encode() in response.content
    assert marker in response.content


@pytest.mark.django_db
def test_installed_package_validates_an_unsaved_hxml_source(admin_client):
    source = (
        '<doc xmlns="https://hyperview.org/hyperview">'
        '<screen id="draft-screen"><body><text>Stored copy</text></body></screen>'
        "</doc>"
    )
    template = HyperviewTemplate.objects.create(
        name="screens/admin-validation.xml",
        content=source,
    )
    change_url = reverse(
        "admin:dj_hyperview_database_hyperviewtemplate_change",
        args=[template.pk],
    )
    validation_url = reverse(
        "admin:dj_hyperview_database_hyperviewtemplate_hxml_validate"
    )

    editor = admin_client.get(change_url)
    response = admin_client.post(
        validation_url,
        data=json.dumps(
            {
                "name": template.name,
                "content": "<view>\n{% if ready %}<text />\n</view>",
            }
        ),
        content_type="application/json",
    )

    assert editor.status_code == 200
    assert b"djhv-format-validate" in editor.content
    assert b"Format and Validate" in editor.content
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["diagnostics"][0]["code"] == "django_syntax"
    template.refresh_from_db()
    assert template.content == source
    assert template.revision == 1
