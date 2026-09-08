"""Scroll-behaviour contract tests for Hyperview screens.

The dashboard's scroll container is transparent and its first child is the blue
hero, so an iOS rubber-band at the top slid the hero down and exposed the body
canvas as a light strip under the fixed blue status-bar inset. These tests pin
the fix and the assumptions it rests on.
"""

from xml.etree import ElementTree

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db
MEDIA_TYPE = "application/vnd.hyperview+xml"
NS = {"hv": "https://hyperview.org/hyperview"}


def assert_hxml(response, *, status=200, media_type=MEDIA_TYPE):
    """Assert a response is parseable UTF-8 Hyperview XML."""
    assert response.status_code == status
    assert response.headers["Content-Type"] == f"{media_type}; charset=utf-8"
    return ElementTree.fromstring(response.content)


def style_by_id(root, style_id):
    """Return the screen stylesheet rule with the given id."""
    return root.find(f".//hv:style[@id='{style_id}']", NS)


def test_dashboard_scroll_container_disables_over_scroll(user):
    """The dashboard scroller must refuse to bounce, exactly as the client reads it."""
    client = Client()
    client.force_login(user)
    root = assert_hxml(client.get(reverse("todo:dashboard")))

    content = root.find(".//hv:view[@id='screen-content']", NS)

    assert content is not None
    assert content.attrib["scroll"] == "true"
    # hv-view only honours the literal string "false"; anything else is a no-op.
    assert content.attrib["over-scroll"] == "false"


def test_dashboard_hero_scrolls_over_an_unpainted_container(user):
    """Document why over-scroll is load-bearing: the exposed band would be canvas."""
    client = Client()
    client.force_login(user)
    root = assert_hxml(client.get(reverse("todo:dashboard")))

    content = root.find(".//hv:view[@id='screen-content']", NS)
    container_style = style_by_id(root, "screen-content-style")

    assert container_style is not None
    assert "backgroundColor" not in container_style.attrib
    assert style_by_id(root, "screen").attrib["backgroundColor"] == "#F7F8FC"
    assert style_by_id(root, "hero").attrib["backgroundColor"] == "#278CFF"
    assert content.find(".//hv:view[@id='dashboard-hero']", NS) is not None


def test_login_body_disables_over_scroll_over_its_blue_canvas():
    """The login sheet has the same shape as the dashboard: light card on blue."""
    root = assert_hxml(Client().get(reverse("todo:login")))

    body = root.find(".//hv:body", NS)

    assert body is not None
    assert body.attrib["scroll"] == "true"
    assert body.attrib["over-scroll"] == "false"
    assert style_by_id(root, "login-body").attrib["backgroundColor"] == "#278CFF"
    assert style_by_id(root, "login-sheet").attrib["backgroundColor"] == "#F7F8FC"


@pytest.mark.parametrize(
    ("url_name", "list_id"),
    [("todo:tasks", "task-list"), ("todo:categories", "category-list")],
)
def test_refresh_lists_keep_their_over_scroll(user, url_name, list_id):
    """Pull-to-refresh needs the bounce; hv-list reads the same attribute."""
    client = Client()
    client.force_login(user)
    root = assert_hxml(client.get(reverse(url_name)))

    node = root.find(f".//hv:list[@id='{list_id}']", NS)

    assert node is not None
    assert node.attrib["trigger"] == "refresh"
    assert "over-scroll" not in node.attrib
