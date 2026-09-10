"""Balanced formatter input preserves real About output under both contracts."""

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from dj_hyperview import validate_hyperview_schema
from dj_hyperview.contrib.database.models import HyperviewTemplate
from dj_hyperview.contrib.database.services import publish_template

from tests.test_session_contract import _confirm, _headers
from todo.models import Profile

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = Path(__file__).parent / "fixtures/about_before_balanced_wrapper.xml"


def test_about_shares_one_content_partial_between_balanced_branches():
    source = (ROOT / "hyperview/screens/about.xml").read_text()
    include = '{% include "partials/about_content.xml" %}'
    assert source.count(include) == 2
    assert "{% else %}" in source
    assert "{{ app_version }}" not in source
    partial = (ROOT / "hyperview/partials/about_content.xml").read_text()
    assert "{{ app_version }}" in partial
    assert "realtime_enabled" not in partial


def xml_semantics(content):
    validate_hyperview_schema(content.decode())
    root = ET.fromstring(content)
    for node in root.iter():
        if node.text is not None and not node.text.strip():
            node.text = None
        if node.tail is not None and not node.tail.strip():
            node.tail = None
    return ET.tostring(root)


@pytest.mark.django_db
@pytest.mark.parametrize("contract", ["legacy", "v1", "v2"])
@pytest.mark.parametrize("language", ["en", "es"])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_about_balanced_source_keeps_preexisting_rendered_semantics(
    client, user, contract, language, theme
):
    Profile.objects.create(user=user, language=language, theme=theme)
    client.force_login(user)
    headers = {"X-App-Version": "1.2.0"}
    if contract != "legacy":
        binding, _ = _confirm(client, True)
        headers.update(_headers(binding))
        headers["X-HyperTodo-Request-ID"] = "gate-about-equivalence-1"
        if contract == "v2":
            headers["X-HyperTodo-Realtime-Features"] = "changes-v2"
    publish_template("screens/about.xml", REFERENCE.read_text(), using="default")
    before = client.get("/hv/about/", headers=headers)
    assert before.status_code == 200
    HyperviewTemplate.objects.get(name="screens/about.xml").delete()
    after = client.get("/hv/about/", headers=headers)
    assert after.status_code == 200
    assert xml_semantics(after.content) == xml_semantics(before.content)
