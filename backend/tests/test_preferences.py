"""Contracts for the one endpoint that writes a stored presentation preference.

Both switchers post here. There is one endpoint and one transition fragment
rather than two of each, because a theme and a language differ only in which
column they write.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from tests.test_forms_ui import NS, assert_hxml, csrf_client, style_by_id, token_from
from todo.context_processors import THEME_COOKIE
from todo.middleware import THEME_HEADER
from todo.models import Profile

pytestmark = pytest.mark.django_db
HV = NS["hv"]
RESTRICTED = {f"{{{HV}}}{name}" for name in ("doc", "navigator", "screen", "body")}


def url(**query):
    """Build the preference href the switcher markup uses."""
    trailer = "&".join(f"{key}={value}" for key, value in query.items())
    return f"{reverse('todo:preferences')}{'?' if trailer else ''}{trailer}"


def post(client, **query):
    """POST the preference endpoint with a valid CSRF token."""
    token = token_from(client.get(reverse("todo:settings")))
    return client.post(url(**query), {"csrfmiddlewaretoken": token})


def test_a_get_is_rejected_with_405_and_an_allow_header(user):
    client = Client()
    client.force_login(user)

    response = client.get(reverse("todo:preferences"))

    assert response.status_code == 405
    assert response.headers["Allow"] == "POST"


def test_an_anonymous_caller_gets_401_in_the_fragment_shape():
    response = Client().post(url(theme="dark"))

    root = assert_hxml(response, status=401)
    assert not {node.tag for node in root.iter()} & RESTRICTED


def test_posting_dark_creates_a_profile_for_a_user_who_had_none(user):
    client = csrf_client()
    client.force_login(user)

    assert_hxml(post(client, theme="dark"))

    assert Profile.objects.get(user=user).theme == "dark"


def test_posting_the_same_value_twice_writes_absolute_state_not_a_toggle(user):
    # The switcher carries the TARGET value in its href, so a double tap, a retry
    # after a dropped response, or two queued behaviors all land on the same state.
    client = csrf_client()
    client.force_login(user)

    post(client, theme="dark")
    post(client, theme="dark")

    assert Profile.objects.get(user=user).theme == "dark"
    assert Profile.objects.filter(user=user).count() == 1


def test_writing_one_preference_leaves_the_other_untouched(user):
    # The three preferences share one row, which is exactly why every field
    # defaults to blank: writing a theme must not state a language on the user's
    # behalf and flip a Spanish phone to English.
    client = csrf_client()
    client.force_login(user)

    post(client, theme="dark")

    assert Profile.objects.get(user=user).language == ""


@pytest.mark.parametrize(
    "query",
    [{"theme": "neon"}, {"language": "zz"}, {}, {"theme": "dark", "language": "es"}],
)
def test_an_unaccepted_body_is_refused_in_the_callers_shape(query, user):
    client = csrf_client()
    client.force_login(user)

    root = assert_hxml(post(client, **query), status=400)

    assert not {node.tag for node in root.iter()} & RESTRICTED
    assert not Profile.objects.filter(user=user).exists()


def test_the_confirmation_arrives_in_the_language_that_was_just_selected(user):
    # The middleware resolved the language BEFORE the write, so without an explicit
    # activate the snackbar comes back in the old language while the screen behind
    # it repaints in the new one. Half-right output is harder to notice than
    # fully-wrong output.
    client = csrf_client()
    client.force_login(user)

    root = assert_hxml(post(client, language="es"))
    message = root.find(".//hv:behavior[@action='show-snackbar']", NS).attrib["message"]

    assert message == "Idioma actualizado."


def test_the_transition_is_a_bare_single_root_view_that_declares_no_style(user):
    # It lands on two different screens, and `replace` does not rebuild
    # stylesheets, so it may not name a style id that only one of them declares.
    client = csrf_client()
    client.force_login(user)

    root = assert_hxml(post(client, theme="dark"))

    assert root.tag == f"{{{HV}}}view"
    assert not {node.tag for node in root.iter()} & RESTRICTED
    assert not any("style" in node.attrib for node in root.iter())


def test_the_transition_repaints_the_screen_without_pointing_a_reload_at_the_navigator(
    user,
):
    client = csrf_client()
    client.force_login(user)

    root = assert_hxml(post(client, theme="dark"))
    behaviors = root.findall("./hv:behavior", NS)
    actions = [node.attrib["action"] for node in behaviors]

    # The dispatch IS the repaint, for this screen as much as for the parked ones:
    # Events.dispatch is a global emit that reaches the dispatching screen too
    # (hyperview.tsx:291-299) and both hosts listen for session-changed. It also
    # never names a url, so it cannot point at /hv/ and nest a navigator in a
    # screen. A second href-less reload beside it would only fire a concurrent GET
    # of the same screen url whose render is thrown away.
    assert actions[-1] == "dispatch-event"
    assert "reload" not in actions
    assert not any(node.attrib.get("delay") for node in behaviors)


def test_the_theme_survives_a_session_lapse_so_the_login_screen_is_not_a_white_flash(
    user,
):
    # The login and session-expired screens render ANONYMOUSLY and have no profile
    # to read. Without the cookie a dark-mode user whose session lapses at night is
    # handed a full-brightness white screen. A LAPSE and not an explicit sign-out:
    # nothing server-side runs when a session simply expires, so the cookie is the
    # only channel left, which is the whole reason it exists.
    client = csrf_client()
    client.force_login(user)
    post(client, theme="dark")
    client.cookies.pop(settings.SESSION_COOKIE_NAME)

    assert client.cookies[THEME_COOKIE].value == "dark"
    root = assert_hxml(client.get(reverse("todo:login")))
    body = root.find(".//hv:style[@id='login-body']", NS)

    assert body.attrib["backgroundColor"] == "#1F6FD1"


def test_signing_out_clears_the_mirrors_so_the_next_account_does_not_inherit_them(
    user, other_user
):
    # The cookies mirror ONE device-holder's choice, and an explicit sign-out hands
    # the device over. A blank profile overrides neither channel, so without this the
    # next account inherits the language from LocaleMiddleware's cookie and the
    # palette from the context processor's fallback: an English phone with no stated
    # preference used to come back in Spanish, in the dark palette.
    client = csrf_client()
    client.force_login(user)
    post(client, theme="dark")
    post(client, language="es")
    # The real exit, not Client.logout(): the test client's helper resets its whole
    # cookie jar, which the app never does.
    client.post(
        reverse("todo:logout"),
        {"csrfmiddlewaretoken": token_from(client.get(reverse("todo:settings")))},
    )
    client.force_login(other_user)
    root = assert_hxml(
        client.get(reverse("todo:tasks"), headers={"accept-language": "en-US,en;q=0.9"})
    )

    assert root.find(".//hv:style[@id='screen']", NS).attrib["backgroundColor"] == (
        "#F7F8FC"
    )
    assert "All tasks" in root.find(".//hv:text[@id='filter-summary']", NS).text


# ONE host. Settings dropped the switcher when it became a single deferred form,
# because a control that commits on tap cannot share a screen with unsaved text.
# Still a list, and still parametrised: this is what the derived-host guard below
# reads, so restoring a second host is a one-line change here rather than a rewrite.
HOSTS = ["todo:dashboard"]


def switcher(user, host, **headers):
    """Return the document that hosts the shared preference switcher.

    The dashboard hosts it inside the side menu, which is its own endpoint, so the
    route is not simply reverse(host).
    """
    client = Client()
    client.force_login(user)
    assert host == "todo:dashboard", f"add the route for {host}"
    return assert_hxml(client.get(reverse("todo:menu"), headers=headers))


def toggle_of(root):
    """Return the appearance row, found by the style id nothing else carries.

    Not by id, because these three triggers deliberately have none: see
    test_no_preference_trigger_carries_an_id_that_android_would_speak.
    """
    return root.find(".//hv:view[@style='pref-toggle-row']", NS)


def option_of(root, language):
    """Return one language chip, found by the href that names its own target."""
    return root.find(f".//hv:view[@href='{url(language=language)}']", NS)


@pytest.mark.parametrize("host", HOSTS)
def test_no_preference_trigger_carries_an_id_that_android_would_speak(host, user):
    # HyperRef applies createTestProps to its own TouchableOpacity
    # (hyper-ref.tsx:299 and 343) and createTestPropsFromId returns
    # {accessibilityLabel: id} on every non-iOS platform (services/index.ts:81-84).
    # A ViewGroup carrying a contentDescription is the node TalkBack focuses, so an
    # id here shadows the state the child <text> was built to announce: a Spanish
    # user would hear "language-option-es" and no state at all. The dashboard hero
    # trigger is asserted the same way in tests/test_settings.py, for this reason.
    root = switcher(user, host)
    triggers = [toggle_of(root), option_of(root, "en"), option_of(root, "es")]

    assert all(node is not None for node in triggers)
    for node in triggers:
        assert "id" not in node.attrib, node.attrib


@pytest.mark.parametrize("host", HOSTS)
def test_the_drawer_switcher_offers_every_shipped_language_and_marks_the_current_one(
    host, user
):
    root = switcher(user, host)

    for value in ("en", "es"):
        option = option_of(root, value)
        assert option is not None, value
        assert option.attrib["verb"] == "post"
        assert option.attrib["action"] == "replace"
        assert option.attrib["target"] == "preference-panel"

    current = option_of(root, "en")
    assert "preference-option-current" in current.attrib["style"].split()
    # aria-selected does not survive createProps into React Native, so the selected
    # state has to live in the accessible NAME or it is not announced at all.
    label = current.find("./hv:text[@accessibilityRole='button']", NS)
    assert "current" in label.attrib["accessibilityLabel"].lower()
    assert "id" not in label.attrib


# Not a hand-written list. A tuple naming only the five pill ids left the seven
# chip ids unguarded, and deleting the whole pressed modifier from
# `preference-option` in screens/dashboard.xml alone kept the suite green while the
# drawer's chips fell back to DEFAULT_PRESS_OPACITY. The set is read off the
# rendered partial instead, so an id added to the switcher is covered on arrival.
SWITCHER_CONDITIONAL_IDS = frozenset(
    {"pref-toggle-track-on", "preference-option-current"}
)


def switcher_style_ids(user):
    """Return every style id the shared switcher references, read from its markup.

    Both palettes are rendered because pref-toggle-track-on is only emitted while
    the stored theme is dark; the current-language ids come out of either.

    Args:
        user: Account whose stored theme is flipped to reach both branches.

    Returns:
        The set of style ids the partial names anywhere.
    """
    ids = set()
    for stored in (Profile.Theme.LIGHT, Profile.Theme.DARK):
        Profile.objects.update_or_create(user=user, defaults={"theme": stored})
        user.refresh_from_db()
        panel = switcher(user, "todo:dashboard").find(
            ".//hv:view[@id='preference-panel']", NS
        )
        ids |= {
            name
            for node in panel.iter()
            for name in node.attrib.get("style", "").split()
        }
    # A derivation that silently returned the wrong branch would be a guard asleep,
    # which is the exact failure this replaced.
    assert SWITCHER_CONDITIONAL_IDS <= ids, sorted(SWITCHER_CONDITIONAL_IDS - ids)
    return ids


@pytest.mark.parametrize("host", HOSTS)
@pytest.mark.parametrize(
    ("stored", "opposite"),
    [(Profile.Theme.LIGHT, "dark"), (Profile.Theme.DARK, "light")],
)
def test_the_appearance_control_is_one_toggle_that_posts_the_other_theme(
    host, stored, opposite, user
):
    # A real <switch> can never post from inside a <form>: HvSwitch clones the
    # element before triggering, the clone has no parentNode, getFormData walks up
    # to nothing and hyperview.tsx posts a null body -- no CSRF token, so Django
    # rejects every tap. The pill is built out of <view>/<text> and core `replace`
    # for that reason, and the href names the OPPOSITE theme so the server keeps
    # writing absolute state and a double tap cannot desync it.
    Profile.objects.update_or_create(user=user, defaults={"theme": stored})
    user.refresh_from_db()

    root = switcher(user, host)
    toggle = toggle_of(root)

    assert root.find(".//hv:switch", NS) is None, "rule 11: a switch cannot post here"
    assert toggle is not None
    assert toggle.attrib["href"] == f"{reverse('todo:preferences')}?theme={opposite}"
    assert toggle.attrib["verb"] == "post"
    assert toggle.attrib["action"] == "replace"
    assert toggle.attrib["target"] == "preference-panel"

    track = toggle.find("./hv:view", NS)
    on = stored == Profile.Theme.DARK
    assert track.attrib["style"].split() == (
        ["pref-toggle-track", "pref-toggle-track-on"] if on else ["pref-toggle-track"]
    )
    assert track.find("./hv:view", NS).attrib["style"] == "pref-toggle-knob"


@pytest.mark.parametrize("host", HOSTS)
@pytest.mark.parametrize(
    ("stored", "state"), [(Profile.Theme.LIGHT, "off"), (Profile.Theme.DARK, "on")]
)
def test_the_toggle_says_its_own_state_because_no_string_can_reach_accessibilitystate(
    host, stored, state, user
):
    # accessibilityState is NOT reachable from HXML: createProps copies attributes
    # verbatim and coerces only numberOfLines, adjustsFontSizeToFit,
    # allowFontScaling, multiline, selectable, maxFontSizeMultiplier and
    # minimumFontScale, so accessibilityState="checked" arrives as the literal
    # STRING where React Native wants {checked: boolean}. accessibilityRole="switch"
    # without it announces "switch" and then no state at all, so the role is
    # "button" and the NAME carries the state in words. The name lives on the
    # <text>, because HvView copies no server attribute and HyperRef's
    # TouchableOpacity is accessible={false}; and that <text> carries no id,
    # because createTestProps is spread LAST and on Android an id overwrites
    # accessibilityLabel with the slug.
    Profile.objects.update_or_create(user=user, defaults={"theme": stored})
    user.refresh_from_db()

    label = toggle_of(switcher(user, host)).find(
        "./hv:text[@style='pref-toggle-label']", NS
    )

    assert "accessibilityState" not in label.attrib
    assert label.attrib["accessibilityRole"] == "button"
    assert f", {state}." in label.attrib["accessibilityLabel"]
    assert "id" not in label.attrib
    assert label.text == "Dark theme"


FLAGS = {"en": "\U0001f1ec\U0001f1e7", "es": "\U0001f1ea\U0001f1f8"}


@pytest.mark.parametrize("host", HOSTS)
@pytest.mark.parametrize("language", sorted(FLAGS))
def test_a_language_option_wears_a_flag_that_no_screen_reader_ever_announces(
    host, language, user
):
    # The accessible outer text names the language and state. Nested text is
    # inline, with role none to prevent an inherited button run on iOS. The
    # Android hiding prop is a string enum; unsupported boolean strings are gone.
    option = option_of(switcher(user, host), language)
    texts = option.findall("./hv:text", NS)
    assert len(texts) == 1
    word = texts[0]
    inline = word.find("./hv:text[@accessibilityRole='none']", NS)
    flag = inline.find("./hv:text", NS)
    assert flag.text == FLAGS[language]
    assert flag.attrib["style"] == "preference-option-flag"
    assert flag.attrib["importantForAccessibility"] == "no"
    assert "accessibilityElementsHidden" not in flag.attrib
    assert "accessibilityLabel" not in flag.attrib
    assert "id" not in flag.attrib
    language_name = "".join(inline.itertext()).removeprefix(FLAGS[language]).strip()

    assert language_name == {"en": "English", "es": "Español"}[language]
    assert word.attrib["accessibilityRole"] == "button"
    # The accessible name is unchanged by the flag, and it still names the
    # LANGUAGE: a country name reaching it would be the failure the flag risks.
    assert word.attrib["accessibilityLabel"] == (
        f"{language_name}, current language"
        if language == "en"
        else f"Switch to {language_name}"
    )


TEMPLATES = Path(settings.HYPERVIEW["TEMPLATE_DIRS"][0])
INCLUDE = re.compile(r'{%\s*include\s+"([^"]+)"')
# The first start tag of a fragment, past whatever {% load %} prefixes it.
ROOT_TAG = re.compile(r"<([A-Za-z][-\w]*)\b[^>]*>")


def _sources():
    """Return every shipped template keyed by the name an {% include %} would use."""
    return {
        path.relative_to(TEMPLATES).as_posix(): path.read_text()
        for path in TEMPLATES.rglob("*.xml")
    }


def _root_id(source):
    """Return the id of a fragment's single root element, or None."""
    match = ROOT_TAG.search(source)
    if match is None:
        return None
    attribute = re.search(r'\bid="([^"]+)"', match.group(0))
    return attribute.group(1) if attribute else None


def hosts_of(name, sources=None):
    """Return every screens/*.xml this template's markup can be rendered inside.

    Derived from the markup rather than remembered by hand, along the two ways a
    fragment reaches a screen: an {% include %} chain, and a replace landing on
    a slot some other template declares. The second is what makes the drawer's
    copy of the switcher a DASHBOARD fragment: side_menu.xml is served from its
    own endpoint, but its root id is the slot fragments/side_menu_host.xml
    declares, and only screens/dashboard.xml includes that.
    """
    sources = sources or _sources()
    includers = {}
    for template, source in sources.items():
        for included in INCLUDE.findall(source):
            includers.setdefault(included, set()).add(template)
    found, seen, queue = set(), set(), [name]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        if current.startswith("screens/"):
            found.add(current)
            continue
        queue.extend(includers.get(current, ()))
        slot = _root_id(sources[current])
        if slot:
            queue.extend(
                template
                for template, source in sources.items()
                if template != current and f'id="{slot}"' in source
            )
    return found


SWITCHER = "partials/preference_switcher.xml"


def test_the_preference_switcher_declares_its_styles_on_every_screen_that_can_host_it(
    user,
):
    # Replaces the old "the two hand-duplicated copies serialise identically"
    # guard, which goes vacuous the moment there is one host. Rule 2: `replace`
    # does not rebuild stylesheets, so a fragment may only name ids its host
    # SCREEN declares. The host set is DERIVED from the markup, so a second host
    # added by a future edit is checked on arrival instead of shipping missing
    # ids silently -- the exact failure the old test was written for.
    # ./hv:screen/hv:styles/hv:style, never .//hv:style.
    wanted = switcher_style_ids(user)
    client = Client()
    client.force_login(user)

    hosts = hosts_of(SWITCHER)

    # Appearance and language are drawer-only, and the drawer opens from the
    # dashboard hero alone. Widening this set is a deliberate edit.
    assert hosts == {"screens/dashboard.xml"}, sorted(hosts)
    for host in hosts:
        route = {"screens/dashboard.xml": "todo:dashboard"}[host]
        declared = {
            style.attrib["id"]
            for style in assert_hxml(client.get(reverse(route))).findall(
                "./hv:screen/hv:styles/hv:style", NS
            )
        }
        assert wanted <= declared, sorted(wanted - declared)


def test_appearance_and_language_live_only_in_the_side_menu(user):
    # The owner decision this change implements: Settings became one real form
    # with one Save, and a control that commits on tap cannot share a screen with
    # unsaved input. The switcher reloads its host document (session-changed), so
    # keeping it on Settings meant a theme tap had to carry the typed name along
    # or lose it. Moving it out removes the hazard rather than defending it.
    #
    # tests/test_settings.py::test_no_side_menu_destination_is_stranded discards
    # these four hrefs for the same reason it discards sign-out; this is the
    # positive half that stops them being stranded by accident.
    client = Client()
    client.force_login(user)

    settings_screen = assert_hxml(client.get(reverse("todo:settings")))
    drawer = assert_hxml(client.get(reverse("todo:menu")))

    assert not [
        node
        for node in settings_screen.iter()
        if (node.attrib.get("href") or "").startswith(reverse("todo:preferences"))
    ]
    # Rule 2 in reverse: the ids have to LEAVE with the markup, or they are
    # orphans nothing can catch.
    declared = {
        style.attrib["id"]
        for style in settings_screen.findall("./hv:screen/hv:styles/hv:style", NS)
    }
    assert not switcher_style_ids(user) & declared
    assert toggle_of(drawer) is not None
    for language in ("en", "es"):
        assert option_of(drawer, language) is not None


# --- defect: a preference tap used to discard unsaved profile edits -----------


def _profile_post(client, body, **query):
    """POST the preference endpoint with a whole settings-form body attached.

    Every field the form declares is always present, because that is what
    getFormData actually serialises: a <text-field> posts its value attribute even
    when it is empty. Partial bodies are the drawer's shape, not this one.
    """
    payload = {"first_name": "", "last_name": "", "email": "", **body}
    token = token_from(client.get(reverse("todo:settings")))
    return client.post(url(**query), {**payload, "csrfmiddlewaretoken": token})


def _field_value(root, name):
    """Return the rendered value of one settings text-field."""
    node = root.find(f".//hv:text-field[@name='{name}']", NS)
    assert node is not None, name
    return node.attrib.get("value", "")


def test_the_drawer_posts_no_profile_at_all_and_still_flips_the_theme(user):
    # The side menu has no profile fields, so its body is the CSRF token alone.
    # The endpoint must not read that as "clear my profile".
    user.first_name = "Ada"
    user.save(update_fields=("first_name",))
    client = csrf_client()
    client.force_login(user)

    assert_hxml(post(client, theme="dark"))

    user.refresh_from_db()
    assert user.first_name == "Ada"
    assert Profile.objects.get(user=user).theme == "dark"


def test_the_preference_endpoint_never_writes_a_profile_it_was_handed(user):
    # Was test_an_invalid_edit_still_applies_the_preference_and_drops_only_the_bad
    # _field, which pinned _save_profile_riding_along: a Settings-hosted tap shared
    # settings-form with the name and email fields, so getFormData posted them here
    # and this endpoint had to save them or the response's session-changed reload
    # threw them away.
    #
    # That defence is dead by CONSTRUCTION now, not by neglect. Its only host is
    # the drawer, whose form holds the CSRF token alone, and
    # test_the_preference_switcher_declares_its_styles_on_every_screen_that_can
    # _host_it is what keeps that true. So the assertion inverts: a body that
    # carries profile keys anyway -- a replayed request, a future second host --
    # must change nothing but the preference, rather than half-saving a profile
    # this endpoint no longer renders back.
    user.first_name = "Ada"
    user.email = "ada@example.com"
    user.save(update_fields=("first_name", "email"))
    client = csrf_client()
    client.force_login(user)

    response = _profile_post(
        client, {"first_name": "Maria", "email": "not-an-email"}, theme="dark"
    )

    assert_hxml(response, status=200)
    user.refresh_from_db()
    assert (user.first_name, user.email) == ("Ada", "ada@example.com")
    assert Profile.objects.get(user=user).theme == "dark"


def test_the_header_names_the_palette_the_write_just_stored_not_the_one_it_replaced(
    user,
):
    # ThemeHeaderMiddleware calls the same theme() the context processor does, and
    # that reads request.user.profile. ProfileLanguageMiddleware already walked
    # that reverse one-to-one on the way in, so the instance is holding the row as
    # it was BEFORE the write and update_or_create fetched a different one. Without
    # the cache repair in set_preference this response said "light" while its own
    # cookie and the database both said "dark". The headline test in
    # tests/test_hxml_views.py cannot see it: it only ever issues a GET, and
    # nothing is written on a GET.
    Profile.objects.create(user=user, theme=Profile.Theme.LIGHT)
    user.refresh_from_db()
    client = csrf_client()
    client.force_login(user)

    response = post(client, theme="dark")

    assert response.headers[THEME_HEADER] == "dark"
    assert response.cookies[THEME_COOKIE].value == "dark"
    assert Profile.objects.get(user=user).theme == "dark"


def _parents(root):
    """Return a child -> parent map, which ElementTree does not keep."""
    return {child: parent for parent in root.iter() for child in parent}


def _closest_form(root, node):
    """Return the <form> ancestor whose data a control inside it would post."""
    parents = _parents(root)
    while node is not None:
        if node.tag == f"{{{HV}}}form":
            return node
        node = parents.get(node)
    return None


def test_the_drawer_gives_the_shared_switcher_a_form_of_its_own(user):
    # The partial no longer carries its own <form>, so every host owes one. A
    # preference control with no form ancestor posts a null body and Django
    # rejects it at the CSRF check, which is exactly the failure a <switch> has.
    client = Client()
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:menu")))
    form = _closest_form(root, toggle_of(root))

    assert form is not None
    assert form.find(".//hv:text-field[@name='csrfmiddlewaretoken']", NS) is not None, (
        "no CSRF token in the drawer's preference form"
    )
    assert form.find(".//hv:form", NS) is None, "nested forms"


def test_the_drawer_gives_the_switcher_a_wrapper_that_does_not_claim_half_the_panel(
    user,
):
    # Yoga expands `flex: 1` to grow 1 / shrink 1 / basis 0, so two flex="1"
    # siblings split the panel evenly whatever they hold. When this block reused
    # side-menu-links the four nav rows and the switcher each took half: a dead gap
    # under Settings on a large phone, and at large OS text sizes on a small one
    # the rows overflowed their half onto the block below, which neither clips nor
    # scrolls. Only the nav block may absorb the free height.
    client = Client()
    client.force_login(user)

    menu = assert_hxml(client.get(reverse("todo:menu")))
    wrapper = _parents(menu)[_closest_form(menu, toggle_of(menu))]
    dashboard = assert_hxml(client.get(reverse("todo:dashboard")))

    assert wrapper.attrib["style"] == "side-menu-preferences"
    assert "flex" not in style_by_id(dashboard, "side-menu-preferences").attrib
    assert style_by_id(dashboard, "side-menu-links").attrib["flex"] == "1"
