"""Settings screen: profile form, service, endpoint, and navigation reachability."""

from pathlib import Path
from xml.etree import ElementTree

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.forms.models import model_to_dict
from django.test import Client
from django.urls import reverse

from tests.test_forms_ui import (
    NS,
    assert_hxml,
    contrast_ratio,
    declared_ids,
    over,
    read_png_icon,
    style_by_id,
    style_ids,
    token_from,
)
from todo.forms import ProfileForm
from todo.services import issue_biometric_token, update_profile

pytestmark = pytest.mark.django_db


def _bound(user, **overrides):
    """Bind ProfileForm to a full payload with the given overrides."""
    data = {"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com"}
    return ProfileForm({**data, **overrides}, instance=user)


def test_a_blank_email_is_valid_because_the_model_allows_it(user):
    form = _bound(user, email="")

    assert form.is_valid(), form.errors
    assert form.cleaned_data["email"] == ""


def test_a_blank_profile_is_valid_and_clears_every_field(user):
    # All three model fields are blank=True, so an empty POST is a legitimate
    # "clear my profile", not a validation failure.
    form = ProfileForm({"first_name": "", "last_name": "", "email": ""}, instance=user)

    assert form.is_valid(), form.errors


def test_the_email_domain_is_normalised_the_way_django_normalises_it(user):
    form = _bound(user, email="Ada@EXAMPLE.COM")

    assert form.is_valid(), form.errors
    assert form.cleaned_data["email"] == "Ada@example.com"


def test_an_email_another_account_already_holds_is_rejected(user, other_user):
    other_user.email = "ADA@example.com"
    other_user.save(update_fields=("email",))

    form = _bound(user, email="ada@Example.com")

    assert not form.is_valid()
    assert form.errors["email"] == ["This email is already in use."]


def test_resaving_your_own_email_is_not_a_collision(user):
    user.email = "ada@example.com"
    user.save(update_fields=("email",))

    assert _bound(user, email="ada@example.com").is_valid()


def test_a_first_name_longer_than_the_model_allows_is_rejected(user):
    form = _bound(user, first_name="A" * 151)

    assert not form.is_valid()
    assert "first_name" in form.errors


def test_update_profile_writes_every_field_and_returns_the_instance(user):
    saved = update_profile(
        user=user, first_name="Ada", last_name="Lovelace", email="ada@example.com"
    )

    assert saved is user
    user.refresh_from_db()
    assert (user.first_name, user.last_name, user.email) == (
        "Ada",
        "Lovelace",
        "ada@example.com",
    )


def test_update_profile_leaves_credentials_alone(user):
    password = user.password

    update_profile(user=user, first_name="Ada", last_name="", email="")

    user.refresh_from_db()
    assert user.username == "ada"
    assert user.password == password


# --- endpoint -------------------------------------------------------------


def test_the_settings_screen_prefills_the_signed_in_account(client, user):
    user.first_name = "Ada"
    user.email = "ada@example.com"
    user.save(update_fields=("first_name", "email"))
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:settings")))

    assert root.find("./hv:screen/hv:body", NS) is not None
    values = {
        field.attrib["name"]: field.attrib["value"]
        for field in root.findall(".//hv:text-field", NS)
    }
    assert values["first_name"] == "Ada"
    assert values["last_name"] == ""
    assert values["email"] == "ada@example.com"


def test_settings_sends_an_expired_session_to_the_sign_in_screen(client, user):
    root = assert_hxml(client.get(reverse("todo:settings")), status=401)

    assert root.find(".//hv:screen[@id='session-expired-screen']", NS) is not None


def test_a_settings_post_without_a_session_answers_a_recoverable_fragment(client):
    response = client.post(reverse("todo:settings"), {"first_name": "Ada"})
    root = assert_hxml(response, status=401)

    for forbidden in ("doc", "navigator", "screen", "body"):
        assert root.find(f".//hv:{forbidden}", NS) is None
    assert root.find("./hv:behavior[@action='reload']", NS) is not None


def test_settings_rejects_unsupported_methods(client, user):
    client.force_login(user)

    response = client.put(reverse("todo:settings"))

    assert response.status_code == 405
    assert response.headers["Allow"] == "GET, POST"


def test_a_settings_post_without_a_csrf_token_stays_a_bare_fragment(user):
    enforcing = Client(enforce_csrf_checks=True)
    enforcing.force_login(user)

    response = enforcing.post(
        reverse("todo:settings"),
        {"first_name": "Ada"},
        headers={"accept": "application/vnd.hyperview_fragment+xml"},
    )

    assert response.status_code == 403
    root = ElementTree.fromstring(response.content)
    for forbidden in ("doc", "navigator", "screen", "body"):
        assert root.find(f".//hv:{forbidden}", NS) is None


def test_saving_a_valid_profile_answers_a_bare_reloading_confirmation(client, user):
    client.force_login(user)

    response = client.post(
        reverse("todo:settings"),
        {"first_name": "Ada", "last_name": "Lovelace", "email": "Ada@EXAMPLE.COM"},
    )
    root = assert_hxml(response)

    for forbidden in ("doc", "navigator", "screen", "body"):
        assert root.find(f".//hv:{forbidden}", NS) is None
    snackbar = root.find("./hv:behavior[@action='show-snackbar']", NS)
    assert snackbar is not None
    assert snackbar.attrib["message"] == "Settings saved."
    assert snackbar.attrib["once"] == "true"
    # What re-renders the form with the values that were just saved is the
    # session-changed dispatch below, which this screen listens for like every other
    # mounted one (hyperview.tsx:291-299). It used to be that PLUS an href-less
    # reload, which made the settings route fetch itself twice, concurrently.
    assert root.find("./hv:behavior[@action='dispatch-event']", NS) is not None
    assert root.find("./hv:behavior[@action='reload']", NS) is None
    user.refresh_from_db()
    assert (user.first_name, user.last_name, user.email) == (
        "Ada",
        "Lovelace",
        "Ada@example.com",
    )


def test_saving_a_profile_announces_the_change_to_the_screens_underneath(client, user):
    # The href-less reload above only refreshes the settings route. Home is
    # `#root-route`, a StackRouter NAVIGATE truncation that merges params without
    # touching params.url, so HvDoc never refetches (hv-doc.tsx:178-193) and the
    # dashboard keeps rendering the greeting, name and avatar initials of the profile
    # that was just replaced. dashboard.xml, tasks.xml and categories.xml all already
    # listen for `session-changed`, so announcing it is what heals them.
    client.force_login(user)

    root = assert_hxml(
        client.post(reverse("todo:settings"), {"first_name": "Ada"}),
    )

    event = root.find("./hv:behavior[@action='dispatch-event']", NS)
    assert event is not None, "the dashboard would keep greeting the old name"
    assert event.attrib["event-name"] == "session-changed"
    assert event.attrib["once"] == "true"


def test_an_invalid_profile_answers_the_form_panel_at_422(client, user, other_user):
    other_user.email = "ada@example.com"
    other_user.save(update_fields=("email",))
    client.force_login(user)

    response = client.post(
        reverse("todo:settings"), {"first_name": "Ada", "email": "ada@example.com"}
    )
    root = assert_hxml(response, status=422)

    assert root.attrib["id"] == "settings-form-panel"
    # The only invalid field in this post, so the one field-error node is email's.
    # Selected by style because an id here would become the Android accessible name.
    assert root.find(".//hv:text[@style='field-error']", NS).text == (
        "This email is already in use."
    )
    user.refresh_from_db()
    assert user.first_name == ""


def test_an_empty_profile_post_clears_the_account_instead_of_failing(client, user):
    user.first_name = "Ada"
    user.save(update_fields=("first_name",))
    client.force_login(user)

    response = client.post(reverse("todo:settings"), {})

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.first_name == ""


def test_saving_a_profile_survives_a_username_the_form_never_shows(client, db):
    # A username stored before UnicodeUsernameValidator ran over it (data import,
    # management command, shell create_user) must not make the settings screen
    # unusable: the form does not expose username, so the user could never fix it.
    legacy = get_user_model().objects.create_user(
        username="ada bell", password="correct-horse"
    )
    client.force_login(legacy)

    response = client.post(reverse("todo:settings"), {"first_name": "Ada"})

    assert response.status_code == 200
    legacy.refresh_from_db()
    assert legacy.first_name == "Ada"


def test_a_settings_post_cannot_escalate_or_rename_the_account(client, user):
    # The allowlist itself is the thing under test: `fields = "__all__"` is the
    # single most common ModelForm mistake and would hand every signed-in user
    # is_staff, is_superuser and a password overwrite.
    client.force_login(user)
    password = user.password

    client.post(
        reverse("todo:settings"),
        {
            "first_name": "Ada",
            "is_staff": "true",
            "is_superuser": "true",
            "username": "root",
            "password": "zzz",
            "id": user.pk + 99,
        },
    )

    user.refresh_from_db()
    assert set(ProfileForm().fields) == {"first_name", "last_name", "email"}
    assert user.is_staff is False
    assert user.is_superuser is False
    assert user.username == "ada"
    assert user.password == password


def test_a_settings_post_cannot_reach_another_account(client, user, other_user):
    client.force_login(user)
    before = model_to_dict(other_user)

    client.post(
        reverse("todo:settings"),
        {
            "id": other_user.pk,
            "user": other_user.pk,
            "first_name": "Stolen",
            "email": "stolen@example.com",
        },
    )

    other_user.refresh_from_db()
    assert model_to_dict(other_user) == before


# --- app version ----------------------------------------------------------


def _version_text(response):
    root = ElementTree.fromstring(response.content)
    return root.find(".//hv:text[@id='app-version']", NS).text


def test_the_screen_renders_the_version_the_binary_reports(client, user):
    client.force_login(user)

    response = client.get(reverse("todo:settings"), headers={"x-app-version": "1.4.2"})

    assert _version_text(response) == "Version 1.4.2"


def test_an_old_binary_that_sends_no_version_says_so(client, user):
    client.force_login(user)

    assert _version_text(client.get(reverse("todo:settings"))) == "Version unknown"


@pytest.mark.parametrize(
    "junk", ["A" * 200, "<script>alert(1)</script>", "1.0 OR 1=1", "1.0\n2.0"]
)
def test_a_junk_version_header_never_reaches_the_document(client, user, junk):
    # The header is attacker-controlled text rendered into XML. Escaping is not
    # enough on its own: a 4KB value would still wreck the layout.
    client.force_login(user)

    response = client.get(reverse("todo:settings"), headers={"x-app-version": junk})

    assert _version_text(response) == "Version unknown"
    # The whole value, not a prefix: "1.0" alone also appears in the XML declaration.
    assert junk.encode() not in response.content


# --- screen contract ------------------------------------------------------


def test_the_settings_screen_only_uses_styles_it_declares(client, user):
    client.force_login(user)
    issue_biometric_token(user=user)

    root = assert_hxml(client.get(reverse("todo:settings")))

    assert style_ids(root) <= declared_ids(root)


def _every_settings_shape(user):
    """Render every branch of the settings screen and its 422 fragment.

    The screen's markup is conditional four ways: the client can or cannot pick a
    photo, the account is or is not enrolled, the form is or is not in error, and
    a photo is or is not pending. A converse assertion read off one render alone
    would call the other branches' ids orphans.
    """
    old_client = Client()
    old_client.force_login(user)
    modern = Client(headers={"x-app-version": "1.2.0"})
    modern.force_login(user)
    return [
        assert_hxml(old_client.get(reverse("todo:settings"))),
        assert_hxml(modern.get(reverse("todo:settings"))),
        assert_hxml(
            modern.post(reverse("todo:settings"), {"email": "not-an-email"}),
            status=422,
        ),
    ]


def test_the_settings_screen_declares_no_style_it_no_longer_uses(client, user):
    # The converse of the test above, and the half that was missing. `used <=
    # declared` catches a style id that resolves to nothing; it says nothing at
    # all about twelve rules left behind by markup that moved to another screen,
    # which is exactly what happened when the preference switcher left. An orphan
    # is not merely dead weight: it is a rule the next reader assumes something
    # renders, and the day someone reuses the id it silently inherits the shape.
    issue_biometric_token(user=user)
    documents = _every_settings_shape(user)
    declared = declared_ids(documents[0])

    used = set().union(*(style_ids(document) for document in documents))

    assert declared <= used, sorted(declared - used)


def test_the_settings_fragments_only_use_styles_the_screen_declares(user):
    enforcing = Client(enforce_csrf_checks=True)
    enforcing.force_login(user)
    screen = enforcing.get(reverse("todo:settings"))
    declared = declared_ids(assert_hxml(screen))
    issue_biometric_token(user=user)

    invalid = enforcing.post(
        reverse("todo:settings"),
        {"email": "not-an-email", "csrfmiddlewaretoken": token_from(screen)},
    )
    # The one 422 fragment there is now. It carries the photo card, the profile
    # card, the security card and the button, so this single `replace` restores
    # every pending edit at once -- which is exactly why it has to be checked
    # against the screen's own stylesheet.
    saved = enforcing.post(
        reverse("todo:settings"),
        {
            "first_name": "",
            "last_name": "",
            "email": "",
            "biometric_unlock": "off",
            "csrfmiddlewaretoken": token_from(screen),
        },
    )

    assert style_ids(assert_hxml(invalid, status=422)) <= declared
    assert style_ids(assert_hxml(saved)) <= declared


def test_the_settings_save_button_stays_readable_on_blue(client, user):
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:settings")))
    button = style_by_id(root, "button")
    text = style_by_id(root, "button-text")

    assert contrast_ratio(text.attrib["color"], button.attrib["backgroundColor"]) > 3
    assert int(text.attrib["fontSize"]) >= 19
    assert text.attrib["fontWeight"] == "700"


def test_the_settings_version_line_is_readable_body_text(client, user):
    # 13px is not WCAG large text, so the one line a user is asked to read out during
    # support owes the full 4.5:1 against the `screen` canvas it is drawn on. #6E738A
    # was 4.41:1: a fail nobody could see because the string, not the colour, was
    # what the suite pinned.
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:settings")))
    version = style_by_id(root, "version")
    canvas = style_by_id(root, "screen").attrib["backgroundColor"]

    assert int(version.attrib["fontSize"]) < 18
    assert contrast_ratio(version.attrib["color"], canvas) >= 4.5


def test_every_settings_field_is_labelled_and_tall_enough_to_tap(client, user):
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:settings")))

    fields = [
        field
        for field in root.findall(".//hv:text-field", NS)
        if field.attrib["name"] != "csrfmiddlewaretoken"
    ]
    assert fields
    for field in fields:
        assert field.attrib["accessibilityLabel"]
        # createProps copies unknown attributes to TextInput VERBATIM
        # (hyperview services/index.ts:140-157), so an invented kebab-case
        # attribute silently does nothing while reading like a working guard.
        assert set(field.attrib) <= {
            "name",
            "value",
            "placeholder",
            "placeholderTextColor",
            "accessibilityLabel",
            "style",
            "keyboard-type",
        }, field.attrib
    assert int(style_by_id(root, "field").attrib["minHeight"]) >= 48
    assert int(style_by_id(root, "action-row").attrib["minHeight"]) >= 44


# The single column the owner asked for, top to bottom, with no deviation left:
# the Save button is LAST, because everything above it is now a field of the one
# form it posts. It used to sit inside the Profile card saying "Save name and
# email", because the card boundary was the only honest statement of its scope
# while the photo, the preferences and the biometric row each committed on their
# own tap.
#
# The security card is named by its WRAPPER id. The switch inside it cannot be
# named here: its own id is its translated accessible name, because HvSwitch
# builds props from createTestProps alone and the id is the only channel React
# Native ever sees, so keying on it would make this order fail in Spanish.
SETTINGS_ORDER = (
    "avatar-panel",
    "first_name",
    "last_name",
    "email",
    "biometric-panel",
    "settings-submit",
    "app-version",
)


def _ordering_key(node):
    """Return whatever names this node in SETTINGS_ORDER, if anything does."""
    return node.attrib.get("id") or node.attrib.get("name") or node.attrib.get("href")


def test_the_settings_screen_is_one_column_in_the_order_it_was_asked_for(client, user):
    client.force_login(user)
    # The switch only exists for an enrolled account, and it is part of the order.
    issue_biometric_token(user=user)

    root = assert_hxml(client.get(reverse("todo:settings")))
    seen = [
        _ordering_key(node)
        for node in root.iter()
        if _ordering_key(node) in SETTINGS_ORDER
    ]

    assert seen == list(SETTINGS_ORDER), seen

    # LAST inside the form, not merely last in document order: everything above
    # it is a field this one button posts.
    form = root.find(".//hv:form[@id='settings-form']", NS)
    assert list(form)[-1].attrib["id"] == "settings-submit"
    assert form.find("./hv:view[@id='settings-submit']/hv:text", NS).text == (
        "Save settings"
    )


def test_the_settings_scroll_view_pads_its_content_not_itself(client, user):
    # Rule 4: on a scroll view, padding of the scrolled content belongs in
    # content-container-style; padding on the view itself clips the scroll.
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:settings")))
    content = root.find(".//hv:view[@id='screen-content']", NS)

    assert content.attrib["scroll"] == "true"
    assert content.attrib["content-container-style"] == "screen-content-inner"
    assert not [
        key
        for key in style_by_id(root, "screen-content-style").attrib
        if "padding" in key
    ]


# --- navigation reachability ----------------------------------------------

PRIMARY_SCREENS = ("dashboard", "tasks", "categories", "settings")


@pytest.mark.parametrize("screen", PRIMARY_SCREENS)
def test_every_primary_screen_reaches_settings_from_the_tab_bar(client, user, screen):
    client.force_login(user)

    root = assert_hxml(client.get(reverse(f"todo:{screen}")))
    tab = root.find(".//hv:view[@id='nav-settings']", NS)

    assert tab is not None
    assert tab.attrib["href"] == reverse("todo:settings")
    assert tab.attrib["action"] == "navigate"
    assert root.find(".//hv:view[@id='open-side-menu']", NS) is None


def test_the_dashboard_avatar_is_the_door_to_the_side_menu(client, user):
    # The trigger is the avatar disc alone, sized to be its own hit area. It used
    # to be the whole identity row plus a chevron; the row-wide target forced a
    # minHeight, a pressed modifier and a margin workaround on the sibling, all of
    # which die with it.
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:dashboard")))
    menu_href = f"{reverse('todo:menu')}?active=dashboard"
    trigger = root.find(f".//hv:view[@href='{menu_href}']", NS)
    host = root.find(".//hv:view[@id='side-menu-host']", NS)

    assert trigger is not None
    assert trigger.attrib["action"] == "replace"
    assert trigger.attrib["target"] == "side-menu-host"
    assert trigger.attrib["style"] == "hero-avatar"
    # href-style resolves only against stylesheets.regular (hyper-ref.tsx:198-205),
    # so a pressed modifier on it would be dead code. A 52pt disc IS its own hit
    # area, and the old wrapper style is gone for good.
    assert "href-style" not in trigger.attrib
    assert "hero-avatar-hit-area" not in declared_ids(root)

    disc = style_by_id(root, "hero-avatar")
    assert int(disc.attrib["width"]) == int(disc.attrib["height"]) >= 44
    assert int(disc.attrib["borderRadius"]) * 2 == int(disc.attrib["width"])
    # HyperRef gives the TouchableOpacity only href-style (hyper-ref.tsx:198-205,
    # :343), which this disc does not set, so the touchable has no style of its own
    # and sizes to the child's MARGIN box: a margin here would hang off the disc as
    # tappable dead space. The gap lives on the parent as `gap` instead, which sits
    # outside every child's box.
    assert not {name for name in disc.attrib if name.startswith("margin")}, (
        "margin on the trigger is tappable dead space; use gap on the parent"
    )

    row = style_by_id(root, "hero-row")
    assert int(row.attrib["gap"]) == 12
    assert int(row.attrib["marginBottom"]) == 18
    # The row is not a touchable any more, so a minHeight and a pressed modifier on
    # it would be dead markup describing a constraint that no longer exists.
    assert "minHeight" not in row.attrib
    assert row.find("./hv:modifier[@pressed='true']", NS) is None
    assert "marginTop" not in style_by_id(root, "hero-headline").attrib

    # The trigger cannot carry an accessible name, so nobody may pretend it does.
    # HvView builds its props from an allowlist -- style, the id-derived test props,
    # collapsable (hv-view/index.tsx:69-86) -- and never copies element attributes
    # the way hv-text does (services/index.ts:135-161), so an accessibility label
    # written here is dropped without a warning.
    assert not [
        name
        for name in trigger.attrib
        if name.startswith(("accessib", "aria-")) or name == "alt"
    ], "hyperview has no server-set accessible name for <view>; this is a no-op"
    # And no id either. With one, createTestPropsFromId hands the TouchableOpacity
    # accessibilityLabel="dashboard-menu" on Android (services/index.ts:84), which
    # can make TalkBack focus the wrapper as one node and read the slug instead of
    # the label below. Nothing but this test ever referenced that id.
    assert "id" not in trigger.attrib

    # The name rides the initials, because HvText builds its props with createProps,
    # which copies EVERY attribute verbatim onto RN's <Text>
    # (services/index.ts:139-157).
    initials = trigger.find("./hv:text[@style='hero-initials']", NS)
    assert initials is not None
    assert "menu" in initials.attrib["accessibilityLabel"].lower()
    assert initials.attrib["accessibilityRole"] == "button"
    # NO id: createProps spreads testProps LAST (services/index.ts:161), so an id
    # would overwrite that label with the slug on Android.
    assert "id" not in initials.attrib

    # The hero draws no images at all now.
    hero = root.find(".//hv:view[@id='dashboard-hero']", NS)
    assert hero.findall(".//hv:image", NS) == []
    assert "hero-chevron" not in declared_ids(root)

    assert host is not None and len(host) == 0


def test_the_dashboard_avatar_survives_its_own_press_state(client, user):
    # `pressed` propagates to every descendant and each one with a style attribute
    # but no pressed rule falls back to opacity 0.7 (services/index.ts:20-41,
    # DEFAULT_PRESS_OPACITY at services/types.ts:1). The disc IS the whole visual
    # identification of this control, so it cannot take that fallback; the initials
    # can, and their dimming is what makes the press read.
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:dashboard")))
    band = style_by_id(root, "hero").attrib["backgroundColor"]
    disc = style_by_id(root, "hero-avatar")
    initials = style_by_id(root, "hero-initials")

    assert initials.find("./hv:modifier[@pressed='true']", NS) is None
    assert int(initials.attrib["fontSize"]) >= 19
    assert initials.attrib["fontWeight"] == "700"

    ink = initials.attrib["color"]
    face = disc.attrib["backgroundColor"]
    assert contrast_ratio(ink, face) >= 4.5
    assert contrast_ratio(face, band) >= 3

    # The pressed rule is not decoration, it is the ONLY thing keeping the disc off
    # the fallback: dimmed, white composites to #BEDCFF over the band -- 2.37:1 --
    # and no lighter fill can rescue that, because white itself is only 3.34:1 here.
    assert contrast_ratio(over(face, band, 0.7), band) < 3
    pressed = disc.find("./hv:modifier[@pressed='true']/hv:style", NS)
    assert pressed is not None, "the pressed disc falls back to opacity 0.7"
    pressed_face = pressed.attrib["backgroundColor"]
    assert contrast_ratio(pressed_face, band) >= 3

    # The initials still dim, once, inside a disc that no longer dims with them.
    assert contrast_ratio(over(ink, pressed_face, 0.7), pressed_face) >= 3


def test_no_side_menu_destination_is_stranded(client, user):
    # The enumerated guard: every href the side menu offers must also be reachable
    # from the tab bar or from the settings screen, so nothing can only live behind
    # a menu a future edit might drop.
    client.force_login(user)
    menu = ElementTree.fromstring(client.get(reverse("todo:menu")).content)
    dashboard = assert_hxml(client.get(reverse("todo:dashboard")))
    settings = assert_hxml(client.get(reverse("todo:settings")))

    tabs = {
        node.attrib["href"]
        for node in dashboard.find(".//hv:view[@id='bottom-navigation']", NS).iter()
        if node.attrib.get("href")
    }
    elsewhere = {
        node.attrib["href"] for node in settings.iter() if node.attrib.get("href")
    }
    offered = {node.attrib["href"] for node in menu.iter() if node.attrib.get("href")}
    offered.discard(reverse("todo:menu-close"))
    # Sign-out is deliberately menu-only: the Settings card was deleted so the
    # session has one exit, not two. It is the one destination that is SUPPOSED
    # to live behind the menu, and test_sign_out_lives_only_in_the_side_menu
    # guards it there. The four navigation destinations stay covered below.
    offered.discard(reverse("todo:logout"))
    # About is intentionally a drawer-only informational destination. Unlike an
    # action or a required workflow, it has a native Back header and strands no
    # user when the drawer is unavailable.
    offered.discard(reverse("todo:about"))
    # Appearance and language joined it. Settings became one real form with one
    # Save button, and a control that commits the instant it is tapped -- and
    # reloads the document doing it -- cannot share that screen with unsaved
    # input. The drawer's host holds no fields at all, so it is the only safe
    # place left for them. Owner decision, not drift: the positive half is
    # tests/test_preferences.py::test_appearance_and_language_live_only_in_the
    # _side_menu, which pins them TO the drawer and OFF Settings.
    offered -= {
        href for href in offered if href.startswith(reverse("todo:preferences"))
    }

    assert offered
    assert offered <= tabs | elsewhere, f"stranded: {offered - tabs - elsewhere}"


def test_the_side_menu_links_to_settings_and_no_longer_owns_biometrics(client, user):
    client.force_login(user)
    issue_biometric_token(user=user)

    menu = ElementTree.fromstring(client.get(reverse("todo:menu")).content)

    hrefs = {node.attrib["href"] for node in menu.iter() if node.attrib.get("href")}
    assert reverse("todo:settings") in hrefs
    assert menu.find(".//hv:view[@id='biometric-panel']", NS) is None


def test_settings_offers_forgetting_biometrics_only_when_enrolled(client, user):
    # Was a "Forget biometrics on this phone" row posting to its own endpoint.
    # That endpoint is gone: it was an immediate writer on a screen that also
    # holds unsaved text. The control is a pending <switch> inside settings-form
    # now, and its full contract lives in tests/test_biometrics.py. What this
    # keeps asserting is the SHAPE of the card either way round.
    client.force_login(user)

    before = assert_hxml(client.get(reverse("todo:settings")))
    panel = before.find(".//hv:view[@id='biometric-panel']", NS)
    assert panel is not None
    assert panel.find(".//hv:switch", NS) is None

    issue_biometric_token(user=user)
    switch = assert_hxml(client.get(reverse("todo:settings"))).find(
        ".//hv:view[@id='biometric-panel']/hv:switch", NS
    )

    assert switch is not None
    assert switch.attrib["name"] == "biometric_unlock"
    assert switch.attrib["value"] == "on"
    # No href, no verb, no target: it writes nothing until Save is tapped.
    assert not {"href", "verb", "action", "target"} & set(switch.attrib)


def test_sign_out_lives_only_in_the_side_menu(user):
    # One exit, not two. The Settings sign-out card was deleted so the side menu
    # is the single place the session can end; this pins both halves of that.
    enforcing = Client(enforce_csrf_checks=True)
    enforcing.force_login(user)
    settings_screen = assert_hxml(enforcing.get(reverse("todo:settings")))

    assert settings_screen.find(".//hv:view[@id='settings-logout']", NS) is None
    assert not [
        node
        for node in settings_screen.iter()
        if node.attrib.get("href") == reverse("todo:logout")
    ]
    assert not {"signout-row", "signout-text"} & declared_ids(settings_screen)

    menu = enforcing.get(reverse("todo:menu"))
    row = ElementTree.fromstring(menu.content).find(
        ".//hv:view[@id='side-menu-logout']", NS
    )
    assert row.attrib["href"] == reverse("todo:logout")
    assert row.attrib["verb"] == "post"
    assert row.attrib["action"] == "replace"
    assert row.attrib["target"] == "logout-panel"

    enforcing.post(reverse("todo:logout"), {"csrfmiddlewaretoken": token_from(menu)})
    assert "_auth_user_id" not in enforcing.session


# --- dead side-menu contract removed --------------------------------------


@pytest.mark.parametrize("screen", ["tasks", "categories"])
def test_screens_that_cannot_open_the_side_menu_carry_none_of_its_contract(
    client, user, screen
):
    # The menu opens from the dashboard hero only, so its host and its sixteen
    # style declarations were dead markup here. This pins the deletion: anyone
    # adding a second trigger has to re-add the declarations deliberately.
    client.force_login(user)

    root = assert_hxml(client.get(reverse(f"todo:{screen}")))

    assert root.find(".//hv:view[@id='side-menu-host']", NS) is None
    assert not [
        style_id for style_id in declared_ids(root) if style_id.startswith("side-menu")
    ]


def test_no_template_still_asks_for_the_retired_menu_icon():
    sources = [
        path.read_text()
        for path in Path(settings.HYPERVIEW["TEMPLATE_DIRS"][0]).rglob("*.xml")
    ]
    assert not [text for text in sources if "icons/menu" in text]


# A press fill that matches the surface underneath is not press feedback. Material
# Design's WEAKEST state layer -- the 8% hover overlay -- lands at 1.20:1 over a
# near-white surface, and a press owes at least as much as a hover. side-menu-logout
# filled #FFFFFF over the #F7F8FC footer: 1.06:1, with the icon pinned to opacity 1
# and the label re-declaring its colour, so holding the row changed nothing at all
# and this guard, which only asked that SOME backgroundColor be declared, passed.
MIN_PRESS_FILL_CONTRAST = 1.2


# Third id per row: the surface the row is drawn on when it declares no fill of its
# own. Sign out sits in side-menu-footer, NOT on the panel -- reading the panel here
# measured this row against a colour it never touches.
@pytest.mark.parametrize(
    ("route", "rows"),
    [
        (
            "todo:dashboard",
            (
                ("side-menu-link", "side-menu-link-text", "side-menu-panel"),
                ("side-menu-logout-style", "side-menu-logout-text", "side-menu-footer"),
            ),
        ),
        ("todo:settings", (("action-row", "action-row-text", "card"),)),
    ],
)
def test_pressing_a_row_does_not_dim_its_own_label_out_of_contrast(
    client, user, route, rows
):
    # `pressed` reaches every descendant (hyper-ref.tsx:445 puts it in options,
    # hv-view/index.tsx:196-212 spreads options into renderChildren) and every styled
    # element whose ids declare NO pressed rule falls back to opacity 0.7
    # (services/index.ts:33-41). The row and the label inside it each take that
    # fallback, and RN nests the layers, so the label lands at 0.49 effective:
    # #20243D composites to #9294A0 (3.01:1) and #B42318 to #D6908C (2.41:1), both
    # under the 4.5:1 that 16px normal text owes. Hold a finger on "Tasks", on
    # "Sign out" or on "Forget biometrics on this phone" and the one thing you are
    # looking at drops below AA.
    client.force_login(user)
    issue_biometric_token(user=user)

    root = assert_hxml(client.get(reverse(route)))

    for row_id, text_id, surface_id in rows:
        text = style_by_id(root, text_id)
        ink = text.attrib["color"]
        backdrop = (
            style_by_id(root, row_id).attrib.get("backgroundColor")
            or style_by_id(root, surface_id).attrib["backgroundColor"]
        )

        assert int(text.attrib["fontSize"]) < 19, text_id
        assert contrast_ratio(ink, backdrop) >= 4.5, text_id
        # The failure the modifiers below prevent, in the suite's own arithmetic.
        assert (
            contrast_ratio(over(over(ink, backdrop, 0.7), backdrop, 0.7), backdrop)
            < 4.5
        ), f"{text_id}: the nested fallback would be harmless, so this guard is dead"

        held = style_by_id(root, row_id).find(
            "./hv:modifier[@pressed='true']/hv:style", NS
        )
        assert held is not None, (
            f"{row_id}: the row dims to 0.7 and drags the label with it"
        )
        assert "backgroundColor" in held.attrib, (
            f"{row_id}: press feedback must be a fill, not another opacity"
        )
        assert contrast_ratio(ink, held.attrib["backgroundColor"]) >= 4.5, row_id
        assert (
            contrast_ratio(held.attrib["backgroundColor"], backdrop)
            >= MIN_PRESS_FILL_CONTRAST
        ), f"{row_id}: the press fill is the surface it is drawn on"

        held_text = text.find("./hv:modifier[@pressed='true']/hv:style", NS)
        assert held_text is not None, (
            f"{text_id}: dims to 0.7 inside a row that does not"
        )
        assert held_text.attrib["color"] == ink, text_id


def test_the_side_menu_glyph_does_not_dim_with_the_row_it_sits_in(client, user):
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:dashboard")))

    icon = style_by_id(root, "side-menu-icon")
    assert icon.find("./hv:modifier[@pressed='true']/hv:style", NS) is not None, (
        "side-menu-icon: a pre-tinted glyph at 0.7 is a different colour"
    )


def test_the_sign_out_icon_is_baked_in_the_colour_its_label_declares(client, user):
    # A pre-tinted PNG carries no tintColor, so the file and the style beside it are
    # two independent copies of one colour. Decoding is what stops them drifting.
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:dashboard")))
    label = style_by_id(root, "side-menu-logout-text").attrib["color"]
    footer = style_by_id(root, "side-menu-footer").attrib["backgroundColor"]
    icon = read_png_icon(finders.find("todo/icons/logout.png"))

    assert icon.colour == label
    assert contrast_ratio(icon.colour, footer) >= 3
