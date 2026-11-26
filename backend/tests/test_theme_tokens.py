"""Proof that extracting colours into tokens left the light theme untouched.

The golden fixture in fixtures/light_stylesheets.json was captured from the
tree BEFORE a single hex literal moved into todo/theme.py. It is the only
thing that makes "light is unchanged" falsifiable rather than a claim, so it must
never be regenerated to make a failure go away: a diff here means a token
resolved to something other than the literal it replaced.
"""

import json
import re
from pathlib import Path
from xml.etree.ElementTree import Element

import pytest
from django.contrib.auth.models import AbstractUser, AnonymousUser
from django.test import Client, RequestFactory
from django.urls import reverse

from tests.test_forms_ui import NS, assert_hxml, contrast_ratio, style_by_id
from todo import context_processors, theme
from todo.context_processors import THEME_COOKIE
from todo.models import Profile

pytestmark = pytest.mark.django_db
GOLDEN = Path(__file__).resolve().parent / "fixtures/light_stylesheets.json"

# Every screen document that declares a stylesheet, with the request that renders
# it. `error` and `session_expired` are reached by failing on purpose, which is the
# only way those two documents are ever produced.
SCREENS = {
    "categories": ("auth", "todo:categories", {}),
    "category_form": ("auth", "todo:category-new", {}),
    "dashboard": ("auth", "todo:dashboard", {}),
    "error": ("auth", "todo:tasks", {"status": "nope"}),
    "login": ("anon", "todo:login", {}),
    "session_expired": ("anon", "todo:dashboard", {}),
    "settings": ("auth", "todo:settings", {}),
    "task_form": ("auth", "todo:task-new", {}),
    "tasks": ("auth", "todo:tasks", {}),
}


def render_screen(
    user: AbstractUser,
    screen: str,
    *,
    headers: dict[str, str] | None = None,
    palette: str | None = None,
) -> Element:
    """Return the parsed document for one named screen of the golden set.

    Args:
        user: Account to sign in when the screen needs one.
        screen: Key into SCREENS.
        headers: Optional extra request headers.
        palette: Optional theme cookie value, which is the ONLY channel the
            anonymous screens have: login and session_expired have no profile to
            read, so without it they always render light.

    Returns:
        Parsed HXML root element for that screen.
    """
    who, route, query = SCREENS[screen]
    client = Client()
    if palette:
        client.cookies[THEME_COOKIE] = palette
    if who == "auth":
        client.force_login(user)
    expected = {"error": 400, "session_expired": 401}.get(screen, 200)
    response = client.get(reverse(route), query, headers=headers or {})
    return assert_hxml(response, status=expected)


def stylesheet_rules(root: Element) -> dict[str, dict[str, str]]:
    """Return one screen's stylesheet as {rule key: {attribute: value}}.

    A rule key is the style id, or id:modifier for a <modifier> block, so a
    pressed fill is compared against the pressed fill it replaced and never
    against the idle one.

    Args:
        root: Parsed screen document.

    Returns:
        Mapping of rule key to that rule's attributes.
    """
    styles = root.find("./hv:screen/hv:styles", NS)
    assert styles is not None, "screen declares no stylesheet"
    rules = {}
    for style in styles.findall("./hv:style", NS):
        key = style.attrib["id"]
        rules[key] = {k: v for k, v in style.attrib.items() if k != "id"}
        for modifier in style.findall("./hv:modifier", NS):
            state = "+".join(sorted(f"{k}={v}" for k, v in modifier.attrib.items()))
            for inner in modifier.findall("./hv:style", NS):
                rules[f"{key}:{state}"] = dict(inner.attrib)
    return rules


@pytest.mark.parametrize("screen", sorted(SCREENS))
def test_the_light_stylesheet_still_resolves_to_the_literals_it_shipped_with(
    screen: str, user: AbstractUser
) -> None:
    """The light stylesheet still resolves to the literals it shipped with.

    Args:
        screen: Screen under test.
        user: Signed-in user who owns the data in this test.
    """
    # This is the falsifiable half of "the extraction did not touch light". Every
    # (rule, attribute) the screen shipped with before todo/theme.py existed must
    # still resolve to the same value. ADDING an attribute is allowed -- tintColor
    # had to be added for the dark palette to reach the glyphs -- but moving or
    # dropping one is not, and regenerating the fixture to make this pass defeats
    # the entire point of having captured it first.
    golden = json.loads(GOLDEN.read_text())[screen]
    rendered = stylesheet_rules(render_screen(user, screen))

    for rule, attributes in golden.items():
        assert rule in rendered, f"{screen}: lost style rule {rule}"
        for attribute, value in attributes.items():
            assert rendered[rule].get(attribute) == value, (
                f"{screen}: {rule}.{attribute} moved {value} -> "
                f"{rendered[rule].get(attribute)}"
            )


COLOUR_ATTRIBUTES = (
    "color",
    "backgroundColor",
    "borderColor",
    "borderTopColor",
    "tintColor",
    "shadowColor",
    "placeholderTextColor",
)
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def test_light_and_dark_declare_the_same_token_names() -> None:
    """Light and dark declare the same token names."""
    assert set(theme.LIGHT) == set(theme.DARK)
    for name, table in (("light", theme.LIGHT), ("dark", theme.DARK)):
        for token, value in table.items():
            assert HEX.match(value), f"{name}.{token} = {value!r}"


def test_an_account_with_no_profile_row_still_gets_a_palette(
    user: AbstractUser, rf: RequestFactory
) -> None:
    """An account with no profile row still gets a palette.

    Args:
        user: Signed-in user who owns the data in this test.
        rf: Factory that builds the requests under test.
    """
    request = rf.get("/hv/dashboard/")
    request.user = user

    assert context_processors.theme(request)["theme"] is theme.LIGHT


def test_an_anonymous_request_gets_the_light_palette(rf: RequestFactory) -> None:
    """An anonymous request gets the light palette.

    Args:
        rf: Factory that builds the requests under test.
    """
    request = rf.get("/hv/login/")
    request.user = AnonymousUser()

    assert context_processors.theme(request)["theme"] is theme.LIGHT


def test_a_profile_set_to_dark_selects_the_dark_palette(
    user: AbstractUser, rf: RequestFactory
) -> None:
    """A profile set to dark selects the dark palette.

    Args:
        user: Signed-in user who owns the data in this test.
        rf: Factory that builds the requests under test.
    """
    Profile.objects.create(user=user, theme=Profile.Theme.DARK)
    user.refresh_from_db()
    request = rf.get("/hv/dashboard/")
    request.user = user

    assert context_processors.theme(request)["theme"] is theme.DARK


@pytest.mark.parametrize("screen", sorted(SCREENS))
@pytest.mark.parametrize("palette", ["light", "dark"])
def test_no_colour_attribute_on_any_screen_renders_empty(
    palette: str, screen: str, request: pytest.FixtureRequest
) -> None:
    """No colour attribute on any screen renders empty.

    Args:
        palette: Theme palette under test, light or dark.
        screen: Screen under test.
        request: Pytest request used to look up the user fixture of the palette under
        test.
    """
    # A mistyped {{ theme.surfce }} resolves to the empty string and Hyperview's
    # `string` converter passes it straight through to React Native, so a typo
    # ships a colourless screen instead of raising. Both palettes are scanned
    # because a token can exist in one table and not the other.
    root = render_screen(request.getfixturevalue(f"{palette}_user"), screen)

    for node in root.iter():
        for attribute in COLOUR_ATTRIBUTES:
            if attribute in node.attrib:
                assert HEX.match(node.attrib[attribute]), (
                    f"{palette}/{screen}: {node.tag} "
                    f"{attribute}={node.attrib[attribute]!r}"
                )


def _placeholder_fill(root: Element, node: Element) -> str:
    """Return the fill of the box a placeholder string is drawn inside.

    Args:
        root: Rendered screen document.
        node: Element carrying a placeholder attribute.

    Returns:
        The #RRGGBB backgroundColor of the last composed style id that declares one.
    """
    ids = (node.attrib.get("field-style") or node.attrib.get("style") or "").split()
    fills = [
        style_by_id(root, name).attrib["backgroundColor"]
        for name in ids
        if "backgroundColor" in style_by_id(root, name).attrib
    ]
    assert fills, f"{node.tag} style={ids!r} declares no fill to measure against"
    return fills[-1]


@pytest.mark.parametrize("screen", sorted(SCREENS))
@pytest.mark.parametrize("palette", ["light", "dark"])
def test_every_placeholder_states_its_own_colour(
    palette: str, screen: str, request: pytest.FixtureRequest
) -> None:
    """Every placeholder states its own colour.

    Args:
        palette: Theme palette under test, light or dark.
        screen: Screen under test.
        request: Pytest request used to look up the user fixture of the palette under
        test.
    """
    # An omitted placeholderTextColor is not neutral: React Native paints its own
    # grey, which is a hard-coded literal no palette owns, and on <picker-field>
    # the empty-value label falls back to the FULL field ink instead -- so "No
    # category" renders identically to a category the user actually chose.
    # createProps copies both attributes to the component verbatim
    # (services/index.ts:121-157 coerces neither), and hv-picker-field,
    # hv-picker-field.ios and hv-date-field/field-label each read
    # placeholderTextColor BY NAME, so this is a first-class attribute on all
    # three field types rather than something merely tolerated.
    root = render_screen(
        request.getfixturevalue(f"{palette}_user"), screen, palette=palette
    )

    for node in root.iter():
        if "placeholder" not in node.attrib:
            continue
        colour = node.attrib.get("placeholderTextColor", "")
        assert HEX.match(colour), (
            f"{palette}/{screen}: {node.tag} placeholder="
            f"{node.attrib['placeholder']!r} has placeholderTextColor={colour!r}"
        )
        fill = _placeholder_fill(root, node)
        assert contrast_ratio(colour, fill) >= 4.5, (
            f"{palette}/{screen}: placeholder {colour} on {fill} is "
            f"{contrast_ratio(colour, fill):.2f}"
        )


def test_the_sign_in_screens_follow_the_theme_cookie_because_they_have_no_profile(
    rf: RequestFactory,
) -> None:
    """The sign-in screens follow the theme cookie because they have no profile.

    Args:
        rf: Factory that builds the requests under test.
    """
    # Anonymous by construction: a user whose session lapses at night must not be
    # handed a full-brightness white screen because the server has nobody to ask.
    request = rf.get("/hv/login/")
    request.user = AnonymousUser()
    request.COOKIES[THEME_COOKIE] = "dark"

    assert context_processors.theme(request)["theme"] is theme.DARK


def test_a_stored_profile_outranks_the_cookie(
    user: AbstractUser, rf: RequestFactory
) -> None:
    """A stored profile outranks the cookie.

    Args:
        user: Signed-in user who owns the data in this test.
        rf: Factory that builds the requests under test.
    """
    # The cookie is a fallback, never a second source of truth: a preference
    # changed on another device must not lose to a stale copy on this one.
    Profile.objects.create(user=user, theme=Profile.Theme.LIGHT)
    user.refresh_from_db()
    request = rf.get("/hv/dashboard/")
    request.user = user
    request.COOKIES[THEME_COOKIE] = "dark"

    assert context_processors.theme(request)["theme"] is theme.LIGHT


def test_a_junk_cookie_cannot_select_anything_but_a_shipped_palette(
    rf: RequestFactory,
) -> None:
    """A junk cookie cannot select anything but a shipped palette.

    Args:
        rf: Factory that builds the requests under test.
    """
    request = rf.get("/hv/login/")
    request.user = AnonymousUser()
    request.COOKIES[THEME_COOKIE] = "../../etc/passwd"

    assert context_processors.theme(request)["theme"] is theme.LIGHT


def test_no_template_still_holds_a_colour_literal() -> None:
    """No template still holds a colour literal."""
    # Every colour must come from the palette, or the dark theme silently keeps a
    # light value on one attribute nobody looked at.
    root = Path(__file__).resolve().parents[1] / "hyperview"
    offenders = []
    for path in sorted(root.rglob("*.xml")):
        stripped = re.sub(r"<!--.*?-->", "", path.read_text(), flags=re.S)
        for tag in re.findall(r"<[^>]+>", stripped):
            offenders += [
                f"{path.name}: {attribute}={value}"
                for attribute, value in re.findall(r'(\w+)="(#[0-9A-Fa-f]{6})"', tag)
                if attribute in COLOUR_ATTRIBUTES
            ]

    assert not offenders, offenders


def test_no_xml_comment_can_break_the_template_validator() -> None:
    """No XML comment can break the template validator."""
    # dj_hyperview raises TemplateValidationError[malformed_xml] for a comment
    # containing a double hyphen, and this work added a lot of comments.
    root = Path(__file__).resolve().parents[1] / "hyperview"
    offenders = [
        f"{path.name}: {comment[:60]}"
        for path in sorted(root.rglob("*.xml"))
        for comment in re.findall(r"<!--(.*?)-->", path.read_text(), flags=re.S)
        if "--" in comment
    ]

    assert not offenders, offenders
