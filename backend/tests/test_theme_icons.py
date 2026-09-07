"""Contracts for the glyphs, now that a glyph's colour is a style and not a file.

Every icon used to be a pre-tinted PNG, so the file and the style beside it were
two independent copies of one colour and the guards decoded the artefact. With a
theme the file cannot carry the colour any more: tintColor is a post-decode
colour filter (react-native ImageViewNativeComponent declares it on both the
Android and the iOS RCTImageView config), so the baked pixels are irrelevant and
the STYLE is the only thing left to hold to account.
"""

import pytest
from django.test import Client
from django.urls import reverse

from tests.test_forms_ui import (
    NS,
    assert_hxml,
    contrast_ratio,
    declared_ids,
    style_by_id,
    style_ids,
)
from todo import theme

pytestmark = pytest.mark.django_db
NAV_HOSTS = ("todo:dashboard", "todo:tasks", "todo:categories", "todo:settings")
# Glyphs that legitimately carry no tint. The four stat badges sit on category
# fills, which are identical in BOTH palettes by design, so their baked colours
# stay correct; test_hxml_views.py still decodes them against those fills.
UNTINTED = {"list.png", "sun.png", "alert.png", "calendar.png"}


def screen(who, route, **query):
    """Sign in and render one screen document."""
    client = Client()
    client.force_login(who)
    return assert_hxml(client.get(reverse(route), query))


@pytest.mark.parametrize("route", NAV_HOSTS)
@pytest.mark.parametrize("palette", ["light", "dark"])
def test_the_nav_glyph_is_tinted_the_colour_the_nav_label_declares(
    palette, route, request
):
    # The tie the deleted PNG-decoding guard made, one level up: the glyph and the
    # word under it are still two declarations of one colour, and they still must
    # not drift into a grey icon beside a blue word.
    root = screen(request.getfixturevalue(f"{palette}_user"), route)

    assert (
        style_by_id(root, "nav-icon").attrib["tintColor"]
        == (style_by_id(root, "nav-label").attrib["color"])
    )
    assert (
        style_by_id(root, "nav-icon-active").attrib["tintColor"]
        == (style_by_id(root, "nav-label-active").attrib["color"])
    )


@pytest.mark.parametrize("palette", ["light", "dark"])
def test_the_sign_out_glyph_is_tinted_the_colour_its_label_declares(palette, request):
    root = screen(request.getfixturevalue(f"{palette}_user"), "todo:dashboard")
    tint = style_by_id(root, "side-menu-logout-icon").attrib["tintColor"]

    assert tint == style_by_id(root, "side-menu-logout-text").attrib["color"]
    assert (
        contrast_ratio(
            tint, style_by_id(root, "side-menu-footer").attrib["backgroundColor"]
        )
        >= 3
    )


@pytest.mark.parametrize("palette", ["light", "dark"])
def test_the_side_menu_glyphs_stay_visible_on_every_row_state(palette, request):
    # Same contract as before the migration -- a glyph carries the row's identity
    # and owes 3:1 idle, active and pressed -- read from the tint instead of the
    # file, and now checked in both palettes rather than only the one that ships.
    who = request.getfixturevalue(f"{palette}_user")
    root = screen(who, "todo:dashboard")
    client = Client()
    client.force_login(who)
    opened = assert_hxml(client.get(reverse("todo:menu"), {"active": "tasks"}))

    def fill(style_id):
        return style_by_id(root, style_id).attrib.get("backgroundColor")

    pressed = root.find(
        ".//hv:style[@id='side-menu-link']/hv:modifier[@pressed='true']/hv:style", NS
    ).attrib["backgroundColor"]

    for row in opened.iter(f"{{{NS['hv']}}}view"):
        classes = (row.attrib.get("style") or "").split()
        if "side-menu-link" not in classes:
            continue
        glyph = row.find("./hv:image", NS)
        ids = glyph.attrib["style"].split()
        tint = style_by_id(root, ids[-1]).attrib["tintColor"]
        backdrop = (
            fill("side-menu-link-active")
            if len(classes) > 1
            else fill("side-menu-panel")
        )
        for background in (backdrop, pressed):
            assert contrast_ratio(tint, background) >= 3, (
                f"{palette}: {ids} {tint} on {background}"
            )


@pytest.mark.parametrize("route", NAV_HOSTS + ("todo:task-new", "todo:category-new"))
@pytest.mark.parametrize("palette", ["light", "dark"])
def test_every_glyph_on_a_themed_surface_declares_a_tint(palette, route, request):
    # The completeness half: a NEW glyph dropped onto a card cannot ship untinted,
    # because in the dark palette it would keep whatever colour it was exported in
    # and there is no test that would otherwise notice.
    who = request.getfixturevalue(f"{palette}_user")
    root = screen(who, route)
    documents = [root]
    if route == "todo:dashboard":
        # dashboard.xml is the only screen that includes side_menu_host.xml, so it
        # is the only stylesheet the menu fragment's ids can be resolved against.
        client = Client()
        client.force_login(who)
        documents.append(assert_hxml(client.get(reverse("todo:menu"))))

    for document in documents:
        for image in document.iter(f"{{{NS['hv']}}}image"):
            # The avatar preview ships with NO source attribute at all until a
            # photo is picked, on purpose: HvImage only builds a source from a
            # TRUTHY attribute (hv-image/index.tsx:17-21), but createProps copies
            # every attribute verbatim (:23), so source="" would reach React
            # Native as the empty STRING rather than as absent. It draws no glyph,
            # so it owes no tint.
            if "source" not in image.attrib:
                continue
            source = image.attrib["source"].rsplit("/", 1)[-1]
            if source in UNTINTED:
                continue
            tints = [
                style_by_id(root, name).attrib.get("tintColor")
                for name in image.attrib["style"].split()
            ]
            assert any(tints), f"{palette}/{route}: {source} declares no tintColor"


def test_the_two_palettes_tint_the_navigation_differently():
    # A tint that is identical in both palettes is a token someone forgot to give
    # a dark value; this is what stops the migration being cosmetic.
    assert theme.LIGHT["ink_nav"] != theme.DARK["ink_nav"]
    assert theme.LIGHT["ink_nav_active"] != theme.DARK["ink_nav_active"]


@pytest.mark.parametrize("palette", ["light", "dark"])
def test_every_style_the_side_menu_uses_is_declared_by_the_screen_that_hosts_it(
    palette, request
):
    # `replace` does not rebuild stylesheets, so the menu fragment may only name ids
    # its HOST SCREEN declares, and dashboard.xml is the only screen that includes
    # side_menu_host.xml. Right XPath is ./hv:styles/hv:style, never .//hv:style.
    who = request.getfixturevalue(f"{palette}_user")
    root = screen(who, "todo:dashboard")
    client = Client()
    client.force_login(who)
    opened = assert_hxml(client.get(reverse("todo:menu"), {"active": "tasks"}))

    assert style_ids(opened) <= declared_ids(root), sorted(
        style_ids(opened) - declared_ids(root)
    )
