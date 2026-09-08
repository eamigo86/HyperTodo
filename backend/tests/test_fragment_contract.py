"""Response-shape contract between every template href and the hyperview client.

The client dispatches on the action attribute (hyperview.tsx:219-262):

  reload / navigate / new / push  -> loadDocument, which REQUIRES
                                     <doc> + (screen>body | navigator>nav-route)
                                     (services/dom/parser.ts:242)
  replace / replace-inner
  / append / prepend              -> loadElement, which THROWS
                                     XMLRestrictedElementFound when doc, navigator,
                                     screen or body appears anywhere in the tree
                                     (services/dom/parser.ts:300-366)

So a fragment action and a document action are two different contracts, and the
backend owes the right one on EVERY reachable branch, not just the happy path.
These tests scan the templates for what the client will actually ask for and then
fire the real requests, so a new href cannot ship without declaring its shape.
"""

import re
from base64 import b64encode
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse
from PIL import Image

from todo.models import Category, Task
from todo.services import issue_biometric_token

# Built in-process rather than committed: the avatar endpoint's happy path needs
# real image bytes, and a binary fixture is a thing nobody can review in a diff.
_buffer = BytesIO()
Image.new("RGB", (16, 16), (200, 200, 200)).save(_buffer, "JPEG")
TINY_JPEG_B64 = b64encode(_buffer.getvalue()).decode()

pytestmark = pytest.mark.django_db

HV = "https://hyperview.org/hyperview"
NS = {"hv": HV}
RESTRICTED = {f"{{{HV}}}{name}" for name in ("doc", "navigator", "screen", "body")}
FRAGMENT_ACCEPT = "application/xml, application/vnd.hyperview_fragment+xml"

TEMPLATE_ROOT: Path = settings.HYPERVIEW["TEMPLATE_DIRS"][0]
ELEMENT = re.compile(r"<[a-zA-Z][\w:-]*\s[^>]*?/?>", re.S)
ATTRIBUTE = re.compile(r'([\w:-]+)="([^"]*)"')
CONDITIONAL = re.compile(
    r"\{%\s*if\s.*?%\}(.*?)(?:\{%\s*else\s*%\}(.*?))?\{%\s*endif\s*%\}", re.S
)
EXPRESSION = re.compile(r"\{\{.*?\}\}")

UPDATE_ACTIONS = frozenset({"replace", "replace-inner", "append", "prepend"})
DOCUMENT_ACTIONS = frozenset({"navigate", "new", "push", "reload"})

# hrefs consumed by custom TypeScript components pick their action in TS, so the
# scan below cannot see it. `close-href` is the only permanent entry
# (mobile/src/components/AnimatedSideMenu.tsx:74, replace); the three below are the
# pre-1.1.0 swipe-row attributes, which the current markup replaced with
# <app:swipe-action> children carrying a plain `href` plus `action` and `verb` the
# scanner reads for itself. Delete them with the legacy branch of
# partials/task_items.xml once 1.0.0 is off the floor.
CUSTOM_HREF_ACTIONS = {
    "close-href": ("replace", "get"),
    "edit-href": ("navigate", "get"),
    "toggle-href": ("replace", "post"),
    "delete-href": ("replace", "post"),
}
# <nav-route href> is loaded by the stack navigator, i.e. as a document.
NAV_ROUTE_ACTION = "push"


def _expand(value: str) -> list[str]:
    """Resolve {% if %} href branches into every concrete alternative."""
    match = CONDITIONAL.search(value)
    if not match:
        return [EXPRESSION.sub("{}", value)]
    return [
        expanded
        for branch in (match.group(1), match.group(2) or "")
        for expanded in _expand(value[: match.start()] + branch + value[match.end() :])
    ]


def _scan_hrefs() -> set[tuple[str, str, str, str]]:
    """Return every (attribute, normalised href, verb, action) a template can issue."""
    found = set()
    for path in sorted(TEMPLATE_ROOT.rglob("*.xml")):
        for raw in ELEMENT.findall(path.read_text()):
            attributes = dict(ATTRIBUTE.findall(raw))
            verb = attributes.get("verb", "get").lower()
            action = attributes.get("action")
            if raw.startswith("<nav-route"):
                action = NAV_ROUTE_ACTION
            for name, value in attributes.items():
                if not name.endswith("href") or name == "href-style":
                    continue
                resolved, resolved_verb = CUSTOM_HREF_ACTIONS.get(name, (action, verb))
                for href in _expand(value.replace("&amp;", "&")):
                    found.add((name, href, resolved_verb, resolved))
    return found


def _placeholder(prefix: str, ids: dict[str, str]) -> str:
    """Resolve one {} in a normalised href from the surrounding text."""
    for suffix, value in (
        ("/hv/tasks/", ids["task"]),
        ("/hv/categories/", ids["category"]),
        ("status=", "all"),
        ("category=", ids["category"]),
        ("page=", "1"),
        ("active=", "tasks"),
    ):
        if prefix.endswith(suffix):
            return value
    if prefix == "":
        # <nav-route href="{{ route_href }}"> in screens/root.xml.
        return "/hv/dashboard/"
    raise AssertionError(
        f"Undeclared href placeholder after {prefix!r}. Add it to _placeholder so "
        "the shape guard keeps covering this href instead of silently skipping it."
    )


def _concrete(href: str, ids: dict[str, str]) -> str:
    """Fill a normalised href's placeholders with live values."""
    parts: list[str] = []
    cursor = 0
    for match in re.finditer(r"\{\}", href):
        prefix = href[cursor : match.start()]
        parts.append(prefix)
        parts.append(_placeholder(prefix, ids))
        cursor = match.end()
    parts.append(href[cursor:])
    return "".join(parts)


def assert_bare_fragment(response, label):
    """Assert a response survives loadElement (parser.ts:300-366)."""
    assert response.__class__.__name__ == "HyperviewFragmentTemplateResponse"
    assert response.headers["Content-Type"].startswith(
        "application/vnd.hyperview_fragment+xml"
    )
    root = ElementTree.fromstring(response.content)
    restricted = sorted(
        {el.tag.split("}")[1] for el in root.iter() if el.tag in RESTRICTED}
    )
    assert not restricted, (
        f"{label} -> HTTP {response.status_code} would raise "
        f"XMLRestrictedElementFound({restricted[0]}) in the client"
    )


def assert_document(response, label):
    """Assert a response survives loadDocument (parser.ts:242)."""
    assert response.__class__.__name__ == "HyperviewTemplateResponse"
    assert response.headers["Content-Type"].startswith(
        "application/vnd.hyperview+xml"
    )
    root = ElementTree.fromstring(response.content)
    assert root.tag == f"{{{HV}}}doc", f"{label} -> root is <{root.tag}>, not <doc>"
    screen = root.find("./hv:screen/hv:body", NS)
    navigator = root.find("./hv:navigator/hv:nav-route", NS)
    assert screen is not None or navigator is not None, (
        f"{label} -> HTTP {response.status_code} has no screen>body nor "
        "navigator>nav-route, so loadDocument raises XMLRequiredElementNotFound"
    )


@pytest.fixture
def fixtures(user):
    """Create one task and one category and return their ids."""
    category = Category.objects.create(user=user, name="Home", color="blue")
    task = Task.objects.create(user=user, title="Water the plants", category=category)
    return {"task": str(task.pk), "category": str(category.pk)}


def _requests(shape, ids):
    """Return (label, verb, url) for every scanned href with the given shape."""
    wanted = UPDATE_ACTIONS if shape == "fragment" else DOCUMENT_ACTIONS
    seen = {}
    for attribute, href, verb, action in _scan_hrefs():
        if action not in wanted:
            continue
        if href.startswith("#"):
            # Not a url: the client never fetches it, it resolves to a declared
            # nav-route name. Covered by
            # test_every_fragment_href_names_a_route_the_server_actually_emits.
            continue
        url = _concrete(href, ids)
        seen[(url, verb)] = f"{verb.upper()} {url} [{attribute} action={action}]"
    return sorted((label, verb, url) for (url, verb), label in seen.items())


def _append_urls(ids):
    """Return every href a template loads with action="append"."""
    return sorted(
        {
            _concrete(href, ids)
            for _, href, _, action in _scan_hrefs()
            if action == "append"
        }
    )


# Minimal valid payloads for the POST half of the fragment scan, keyed the way
# _placeholder is so a new fragment POST raises a fix-me instead of being skipped.
FRAGMENT_POST_BODIES = {
    "/hv/login/": {"username": "ada", "password": "correct-horse"},
    "/hv/logout/": {},
    "/hv/biometric/login/": {"biometric_token": "{token}"},
    "/hv/biometric/forget/": {},
    "/hv/settings/": {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "email": "ada@example.com",
    },
    # The preference endpoint takes its whole payload in the query string, so the
    # scanned href already carries it and the body needs only the CSRF token.
    "/hv/preferences/": {},
    "/hv/tasks/new/": {"title": "Guarded create"},
    "/hv/tasks/{task}/edit/": {"title": "Guarded edit"},
    "/hv/tasks/{task}/toggle/": {},
    "/hv/tasks/{task}/delete/": {},
    "/hv/categories/new/": {"name": "Guarded create", "color": "mint"},
    "/hv/categories/{category}/edit/": {"name": "Guarded edit", "color": "mint"},
    "/hv/categories/{category}/delete/": {},
}


def _fragment_body(url, ids, *, token):
    """Return the POST payload declared for one scanned fragment href."""
    key = url.split("?")[0]
    for name, value in ids.items():
        key = key.replace(value, "{" + name + "}")
    if key not in FRAGMENT_POST_BODIES:
        raise AssertionError(
            f"No POST body declared for {key}. Add one to FRAGMENT_POST_BODIES so the "
            "shape guard exercises this endpoint's happy path instead of skipping it."
        )
    return {
        name: value.format(token=token)
        for name, value in FRAGMENT_POST_BODIES[key].items()
    }


def _restore(user, ids):
    """Recreate the fixture records the delete endpoints remove mid-scan."""
    category, _ = Category.objects.get_or_create(
        pk=ids["category"], defaults={"user": user, "name": "Home", "color": "mint"}
    )
    Task.objects.get_or_create(
        pk=ids["task"],
        defaults={"user": user, "title": "Water the plants", "category": category},
    )


def test_every_template_href_declares_a_shape_the_scan_can_resolve(fixtures):
    scanned = _scan_hrefs()
    assert scanned, "the href scan found nothing, so it is broken"

    custom = {attribute for attribute, *_ in scanned if attribute != "href"}
    assert custom == set(CUSTOM_HREF_ACTIONS), (
        "a custom-component href attribute changed; declare its action in "
        "CUSTOM_HREF_ACTIONS so its response shape stays covered"
    )
    for attribute, href, verb, action in scanned:
        assert action in UPDATE_ACTIONS | DOCUMENT_ACTIONS, (
            f"{attribute}={href!r} (verb={verb}) has action={action!r}, which this "
            "guard cannot classify"
        )
        _concrete(href, fixtures)


def test_no_template_decides_its_action_at_render_time():
    # The scan reads the action attribute literally. A templated action would make
    # every classification above a guess.
    for path in sorted(TEMPLATE_ROOT.rglob("*.xml")):
        for raw in ELEMENT.findall(path.read_text()):
            action = dict(ATTRIBUTE.findall(raw)).get("action", "")
            assert "{%" not in action and "{{" not in action, (
                f"{path.name} builds an action at render time: {action!r}"
            )


def test_the_root_navigator_is_never_requested_by_a_template_at_all():
    # Was: "never with a FRAGMENT action", because /hv/ serves <doc><navigator> and
    # loadElement rejects both tags. That was too weak. /hv/ is equally wrong with a
    # DOCUMENT action, because the only route that may hold a navigator document is
    # the entrypoint route the client built the app with. HvDoc merges a fetched
    # document only when its first child is a <navigator> (hv-doc.tsx:120-131);
    # a navigator document arriving on a SCREEN route has a different first child, so
    # mergeDocument bails to the new document (helpers.ts:534-542) and HvRouteInner
    # then renders a whole HvNavigator INSIDE that route (hv-route.tsx:119-127). The
    # result is a stack nested in a screen, one level deeper on every login/logout
    # cycle, whose inner routes are unreachable by the outer stack's back gesture.
    # <nav-route href> is exempt: that IS the entrypoint load.
    offenders = sorted(
        {
            f"{attribute}={href!r} action={action}"
            for attribute, href, _, action in _scan_hrefs()
            if href == "/hv/" and action != NAV_ROUTE_ACTION
        }
    )
    assert not offenders, (
        "these load the root navigator document into a screen route, which nests a "
        f"stack inside it instead of replacing it: {offenders}"
    )


def test_fragment_endpoints_stay_bare_without_a_session(fixtures):
    # /hv/login/ and /hv/biometric/login/ are public, so the status varies; the
    # shape must not. Private endpoints' 401 is pinned in tests/test_hxml_views.py.
    client = Client()
    for label, verb, url in _requests("fragment", fixtures):
        assert_bare_fragment(getattr(client, verb)(url), f"anonymous {label}")


def test_fragment_endpoints_stay_bare_on_a_csrf_failure(user, fixtures):
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    for label, verb, url in _requests("fragment", fixtures):
        if verb != "post":
            continue
        response = client.post(url, headers={"accept": FRAGMENT_ACCEPT})
        assert response.status_code == 403, f"{label} -> {response.status_code}"
        assert_bare_fragment(response, f"csrf-rejected {label}")


def test_fragment_endpoints_stay_bare_on_the_wrong_method(user, fixtures):
    client = Client()
    client.force_login(user)
    for label, verb, url in _requests("fragment", fixtures):
        opposite = "get" if verb == "post" else "post"
        response = getattr(client, opposite)(url)
        if response.status_code != 405:
            continue
        assert_bare_fragment(response, f"405 {label}")


def test_fragment_endpoints_stay_bare_for_records_deleted_elsewhere(user, fixtures):
    client = Client()
    client.force_login(user)
    missing = {"task": str(uuid4()), "category": str(uuid4())}
    for label, verb, url in _requests("fragment", missing):
        if not any(value in url for value in missing.values()):
            continue
        response = getattr(client, verb)(url)
        assert response.status_code == 404, f"{label} -> {response.status_code}"
        assert_bare_fragment(response, f"404 {label}")


INVALID_FRAGMENT_URLS = [
    "/hv/tasks/?status=bogus&fragment=list",
    "/hv/tasks/?status=all&fragment=bogus",
    "/hv/tasks/?status=all&page=99&fragment=items",
    "/hv/tasks/?status=all&page=abc&fragment=items",
    "/hv/categories/?fragment=bogus",
    "/hv/categories/?page=99&fragment=items",
    # UUIDField.to_python raises ValidationError, not Http404, so an unparseable id
    # used to escape hxml_endpoint as a 500 that the client refuses to render at all.
    "/hv/tasks/?status=all&category=notauuid&fragment=list",
]


@pytest.mark.parametrize("url", INVALID_FRAGMENT_URLS)
def test_fragment_endpoints_stay_bare_for_invalid_parameters(user, url):
    client = Client()
    client.force_login(user)

    response = client.get(url)

    assert response.status_code == 400
    assert_bare_fragment(response, f"400 GET {url}")


def test_fragment_endpoints_stay_bare_for_a_signed_in_user(user, fixtures):
    # The mirror of test_document_endpoints_stay_documents. Without it every fragment
    # axis in this file exercises a FAILURE branch, so a new endpoint whose happy path
    # returns a <doc> ships green and only blows up on the device.
    client = Client()
    for label, verb, url in _requests("fragment", fixtures):
        # /hv/logout/ ends the session and the delete endpoints remove the records,
        # so the loop has to put the world back before each request.
        client.force_login(user)
        _restore(user, fixtures)
        if verb == "post":
            body = _fragment_body(url, fixtures, token=issue_biometric_token(user=user))
            response = client.post(url, body)
        else:
            response = client.get(url)
        assert response.status_code in (200, 201), (
            f"signed-in {label} -> {response.status_code}"
        )
        assert_bare_fragment(response, f"signed-in {label}")


def test_error_fragments_for_append_targets_are_list_items(user, fixtures):
    # Every append target here is a <list>, and hv-list feeds its FlatList only the
    # `<item>` children it owns (elements/hv-list/index.tsx:184-189, 251). A <view>
    # appended into a list never enters `data`, never mounts, and so never fires the
    # trigger="load" behaviors that are the whole recovery: the user gets silence.
    client = Client()
    client.force_login(user)
    urls = _append_urls(fixtures)
    assert urls, "the scan found no append href, so this guard is dead"

    for url in urls:
        response = client.get(url.replace("page=1", "page=99"))

        assert response.status_code == 400, f"{url} -> {response.status_code}"
        root = ElementTree.fromstring(response.content)
        assert root.tag == f"{{{HV}}}item", (
            f"{url} -> error root is <{root.tag}>, which hv-list drops silently"
        )
        assert root.attrib.get("key"), "hv-list keyExtractor reads the key attribute"


def test_the_error_fragment_carries_its_message_and_a_recovery_reload(user):
    # The fragment's entire user-facing payload is these two behaviors; the shape
    # guards above would happily pass an empty <item>.
    client = Client()
    client.force_login(user)

    response = client.get(f"/hv/tasks/?status=all&category={uuid4()}&fragment=list")

    assert response.status_code == 404
    root = ElementTree.fromstring(response.content)
    reload_behavior = root.find("./hv:behavior[@action='reload']", NS)
    snackbar = root.find("./hv:behavior[@action='show-snackbar']", NS)
    assert reload_behavior is not None, "nothing gets the user off the broken screen"
    assert reload_behavior.attrib["trigger"] == "load"
    # An href-less reload resolves to the CURRENT screen url (hyperview.tsx:74-82),
    # which is what lets one template recover any endpoint.
    assert "href" not in reload_behavior.attrib
    assert snackbar is not None, "the failure would be completely silent"
    assert snackbar.attrib["message"] == "The requested item was not found."
    assert snackbar.attrib["once"] == "true"


def test_the_error_screen_explains_the_failure_and_offers_a_way_home(user):
    # The way out reloads a SCREEN url, not /hv/: this document already occupies a
    # route, and reloading the root navigator into it nests a stack inside that route
    # instead of replacing it. Which screen is home depends on the session, so the
    # href is server-chosen rather than a literal in the template.
    client = Client()
    client.force_login(user)

    root = ElementTree.fromstring(client.get("/hv/tasks/?status=bogus").content)

    copy = root.find(".//hv:text[@style='error-copy']", NS)
    home = root.find(".//hv:view[@action='reload']", NS)
    assert copy is not None and copy.text == "Unknown task filter."
    assert home is not None, "the full-screen error would be a dead end"
    assert "".join(home.itertext()).strip() == "Return home"
    assert home.attrib["href"] == "/hv/dashboard/"


def test_login_without_credentials_answers_with_the_login_panel_fragment(user):
    client = Client()

    response = client.post(reverse("todo:login"), {})

    assert response.status_code == 422
    assert_bare_fragment(response, "POST /hv/login/ with no fields")
    root = ElementTree.fromstring(response.content)
    assert root.attrib["id"] == "login-panel"


def test_login_with_a_missing_password_answers_with_the_login_panel_fragment(user):
    client = Client()

    response = client.post(reverse("todo:login"), {"username": "ada"})

    assert response.status_code == 422
    assert_bare_fragment(response, "POST /hv/login/ with no password")


def test_document_endpoints_stay_documents(user, fixtures):
    anonymous = Client()
    signed_in = Client()
    signed_in.force_login(user)
    for label, verb, url in _requests("document", fixtures):
        for who, client in (("anonymous", anonymous), ("signed-in", signed_in)):
            response = getattr(client, verb)(url)
            assert_document(response, f"{who} {label}")


def test_document_endpoints_stay_documents_for_invalid_parameters(user):
    client = Client()
    client.force_login(user)

    assert_document(
        client.get("/hv/tasks/?status=bogus"), "GET /hv/tasks/?status=bogus"
    )


def test_the_error_fragment_carries_no_style_ids(user):
    # Landmine: `replace` does not rebuild stylesheets, so a fragment injected into
    # an arbitrary screen may only use style ids that screen already declares. This
    # one lands anywhere, so it must reference no style at all.
    client = Client()

    response = client.get("/hv/tasks/?status=bogus&fragment=list")

    root = ElementTree.fromstring(response.content)
    styled = [el.tag for el in root.iter() if "style" in el.attrib]
    assert not styled, (
        f"the error fragment uses styles its host may not declare: {styled}"
    )


def test_the_login_panel_reports_what_was_actually_wrong(user):
    client = Client()

    empty = client.post(reverse("todo:login"), {})
    wrong = client.post(reverse("todo:login"), {"username": "ada", "password": "nope"})

    def error_text(response):
        root = ElementTree.fromstring(response.content)
        return root.find(".//hv:view[@style='error-card']/hv:text", NS).text

    assert error_text(empty) == "Enter your username and password."
    assert error_text(wrong) == "The username or password is incorrect."


def test_csrf_failure_stays_a_document_when_the_client_sends_no_accept_header(user):
    # Pins the safe default: everything that does not announce itself as a fragment
    # load keeps the document it used to get, so the existing suite cannot drift.
    response = Client(enforce_csrf_checks=True).post(
        reverse("todo:login"), {"username": "ada", "password": "correct-horse"}
    )

    assert response.status_code == 403
    assert_document(response, "csrf failure without an Accept header")
    # The one error screen an anonymous caller can reach. Its way home is the login
    # screen, not the dashboard it has no session for, and not /hv/.
    home = ElementTree.fromstring(response.content).find(
        ".//hv:view[@action='reload']", NS
    )
    assert home is not None and home.attrib["href"] == "/hv/login/"


def test_csrf_failure_is_a_bare_fragment_for_a_fragment_load(user):
    response = Client(enforce_csrf_checks=True).post(
        reverse("todo:login"),
        {"username": "ada", "password": "correct-horse"},
        headers={"accept": FRAGMENT_ACCEPT},
    )

    assert response.status_code == 403
    assert_bare_fragment(response, "csrf failure on a fragment load")


# A transition fragment is always the response to `action="replace"` whose target is
# its host screen's only content, so performUpdate (services/behaviors/index.ts:76-82)
# empties that screen before the transition's own behaviors run. The screen left
# behind renders nothing, so the transition MUST either remove it from the stack
# (close/back) or re-render it (reload). navigate/push leave it alive and reachable.
STACK_GROWING_ACTIONS = frozenset({"navigate", "push"})


def _transition_behaviors():
    """Return (template name, attributes) for every behavior in a *_transition.xml."""
    found = []
    for path in sorted(TEMPLATE_ROOT.rglob("*_transition.xml")):
        for raw in ELEMENT.findall(path.read_text()):
            if not raw.startswith("<behavior"):
                continue
            attributes = dict(ATTRIBUTE.findall(raw))
            if attributes.get("action"):
                found.append((path.name, attributes))
    return found


def test_no_transition_fragment_leaves_its_emptied_host_screen_in_the_stack():
    behaviors = _transition_behaviors()
    assert behaviors, "the transition scan found nothing, so this guard is dead"

    offenders = sorted(
        {
            f"{name} action={attributes['action']}"
            for name, attributes in behaviors
            if attributes["action"] in STACK_GROWING_ACTIONS
        }
    )
    assert not offenders, (
        "these transitions navigate away from the screen they just emptied instead "
        f"of closing or reloading it, so the blank screen survives in the stack: "
        f"{offenders}"
    )


def test_no_transition_fragment_delays_its_own_dismissal():
    # navigator.ts:187-193 wraps sendRequest in setTimeout, and the panel this
    # fragment replaced is already gone when the timer starts. Every millisecond of
    # `delay` is a millisecond the user spends staring at an emptied screen before
    # anything moves. Nothing needs the wait: SnackbarHost lives outside the
    # NavigationContainer (mobile/App.tsx:72-88) and keeps its own 3.2s timer, and
    # dispatch-event is queued before the dismissal in the same microtask batch
    # (services/behaviors/index.ts:154-171). Reject the attribute outright rather
    # than a specific value, or the blank frame comes back as delay="120".
    offenders = sorted(
        {
            f"{name} action={attributes['action']} delay={attributes['delay']}"
            for name, attributes in _transition_behaviors()
            if "delay" in attributes
        }
    )
    assert not offenders, (
        "these transition behaviors make the user watch the screen they just "
        f"emptied before anything happens: {offenders}"
    )


def test_the_form_transitions_dismiss_with_exactly_one_back():
    # `close` needs a route NAMED modal and is otherwise a silent no-op
    # (buildCloseRequest, services/navigator/helpers.ts:301-345 + navigator.ts:89-95),
    # so it can never pair with the `navigate` the guard below requires. `back` pops
    # the focused route whatever its presentation, which is the only dismissal that
    # stays correct if the presentation changes again.
    behaviors = _transition_behaviors()
    closes = sorted(
        {name for name, attributes in behaviors if attributes["action"] == "close"}
    )
    assert not closes, (
        f"these transitions dismiss with `close`, a no-op on a card route: {closes}"
    )
    for form in ("task_transition.xml", "category_transition.xml"):
        backs = [
            name
            for name, attributes in behaviors
            if name == form and attributes["action"] == "back"
        ]
        assert len(backs) == 1, (
            f"{form} must pop its emptied host screen exactly once, found {len(backs)}"
        )


# A screen reached with `navigate` is TRUNCATED back to, not refetched: StackRouter
# returns the existing route with its params merged, params.url does not change, and
# HvDoc only refetches when its url prop changes (hv-doc.tsx:186-193). So everything a
# screen rendered from data another screen can mutate goes stale the moment it is
# parked, and the only thing that refreshes it is a trigger="on-event" listener.
# This table is what each screen RENDERS, not what it owns:
#   dashboard.xml  task counters, "Up next" rows, and category chips built from
#                  summary.category_counts (fragments/dashboard_content.xml:95)
#   tasks.xml      the task list AND one filter chip per category, by name and id
#                  (screens/tasks.xml:63)
#   categories.xml the category list, each row showing "{{ category.task_count }}
#                  tasks" (partials/category_items.xml:7)
#   settings.xml   the signed-in user's own profile fields
# avatar-changed is gone with the endpoint that raised it. It existed because the
# photo committed on its own tap, on a screen that also held an unsaved profile
# form, so it could NOT reuse session-changed: that reloads the settings document
# and would have thrown the typed name away. The photo is a field of settings-form
# now, and the Save that stores it is also the moment nothing is unsaved any more,
# so the transition's session-changed is what repaints the discs.
REQUIRED_EVENT_LISTENERS = {
    "dashboard.xml": {
        "tasks-changed",
        "categories-changed",
        "session-changed",
    },
    "tasks.xml": {"tasks-changed", "categories-changed", "session-changed"},
    "categories.xml": {"tasks-changed", "categories-changed", "session-changed"},
    "settings.xml": {"session-changed"},
}


def _event_names(attribute_name, trigger_or_action):
    """Return {template name: {event-name}} for one behavior kind."""
    found = {}
    for path in sorted(TEMPLATE_ROOT.rglob("*.xml")):
        for raw in ELEMENT.findall(path.read_text()):
            attributes = dict(ATTRIBUTE.findall(raw))
            if attributes.get(attribute_name) != trigger_or_action:
                continue
            if event := attributes.get("event-name"):
                found.setdefault(path.name, set()).add(event)
    return found


def test_every_screen_refreshes_the_data_another_screen_can_invalidate():
    listeners = _event_names("trigger", "on-event")
    missing = {
        name: sorted(required - listeners.get(name, set()))
        for name, required in REQUIRED_EVENT_LISTENERS.items()
        if required - listeners.get(name, set())
    }
    assert not missing, (
        "these screens render data these events invalidate but never listen for "
        f"them, so a parked screen keeps showing the stale version: {missing}"
    )


def _reload_events(name):
    """Return every event name one template answers with a whole-document reload."""
    return {
        attributes["event-name"]
        for raw in ELEMENT.findall((TEMPLATE_ROOT / "screens" / name).read_text())
        for attributes in [dict(ATTRIBUTE.findall(raw))]
        if attributes.get("trigger") == "on-event"
        and attributes.get("action") == "reload"
        and "event-name" in attributes
    }


def test_a_panel_never_dispatches_an_event_that_reloads_its_own_host_screen():
    # `reload` refetches the screen url and swaps the WHOLE document
    # (hyperview.tsx:219-220), and Events.dispatch is a global emit that reaches the
    # dispatching screen too (hyperview.tsx:291-299). So a fragment that is already
    # `replace`d into a screen and ALSO dispatches an event that screen reloads on
    # throws away every unsaved <text-field value> beside it -- a first name typed
    # into settings_form_panel.xml and not yet saved is gone, with no message. The
    # panel's own `replace` is what refreshes the panel; the dispatch exists only for
    # the discs on OTHER routes.
    reloaded = _reload_events("settings.xml")
    dispatched = _event_names("action", "dispatch-event")
    # biometric_forget.xml is gone with its endpoint; the switch that replaced it
    # is a pending field of settings_form_panel.xml and dispatches nothing.
    panels = ("avatar_panel.xml", "settings_form_panel.xml")
    for panel in panels:
        assert not dispatched.get(panel, set()) & reloaded, (
            f"{panel} reloads settings.xml out from under the form it sits beside"
        )


def test_no_transition_asks_one_screen_to_reload_twice():
    # Events.dispatch is a global emit that reaches the DISPATCHING screen too
    # (hyperview.tsx:291-299), so a fragment whose event some screen reloads on has
    # already repainted its own host. An href-less `reload` beside it resolves to
    # that same screen url (hyperview.tsx:74-82) and fires a second, concurrent GET
    # whose render throws the first one away: a doubled round trip and a visible
    # double repaint on every tap. An HREF'd reload is a different destination and
    # not covered here.
    reloaded = {
        event for name in REQUIRED_EVENT_LISTENERS for event in _reload_events(name)
    }
    doubled = {}
    for path in sorted(TEMPLATE_ROOT.rglob("*.xml")):
        behaviors = [
            dict(ATTRIBUTE.findall(raw)) for raw in ELEMENT.findall(path.read_text())
        ]
        if not any(
            attributes.get("action") == "reload" and "href" not in attributes
            for attributes in behaviors
        ):
            continue
        events = {
            attributes["event-name"]
            for attributes in behaviors
            if attributes.get("action") == "dispatch-event"
        }
        if overlap := events & reloaded:
            doubled[path.name] = sorted(overlap)
    assert not doubled, (
        "these fragments repaint their own host twice, once through the event and "
        f"once through their own reload: {doubled}"
    )


def test_no_event_is_dispatched_into_the_void():
    # The mirror: an event nobody is declared to want is dead markup, and the guard
    # above would never notice because it only reads the table.
    dispatched = {
        event
        for events in _event_names("action", "dispatch-event").values()
        for event in events
    }
    wanted = {event for events in REQUIRED_EVENT_LISTENERS.values() for event in events}
    assert dispatched <= wanted, (
        "these events are dispatched but no screen is declared to need them; add "
        "them to REQUIRED_EVENT_LISTENERS or stop dispatching: "
        f"{sorted(dispatched - wanted)}"
    )


# A `#`-prefixed href is NOT a url. getRouteId returns cleanHrefFragment for it
# (services/navigator/helpers.ts:211-218), so the dispatch names a DECLARED nav-route
# and StackRouter truncates the stack back to it (StackRouter.js:224-293). That is the
# only stack reset the server can ask for. Its cost is that StackRouter returns null
# for a name it does not know (:225-227) with no warning and no visual feedback, so a
# fragment href that drifts from what todo/views.py emits is a silently dead control.
def _hrefs_in(relative_path):
    """Return {href: action} for one template."""
    found = {}
    for raw in ELEMENT.findall((TEMPLATE_ROOT / relative_path).read_text()):
        attributes = dict(ATTRIBUTE.findall(raw))
        for name, value in attributes.items():
            if name == "href":
                found[value] = attributes.get("action")
    return found


def test_the_home_control_returns_to_the_root_route_instead_of_pushing_a_copy():
    # `href="/hv/dashboard/"` collapses to the dynamic route name `card`, which never
    # matches the DECLARED root route, so the first Home tap pushes a second dashboard
    # and Back from Home shows Home again. Measured against the real StackRouter in
    # mobile/__tests__/navigation-contract.test.tsx.
    for template in ("fragments/bottom_navigation.xml", "fragments/side_menu.xml"):
        hrefs = _hrefs_in(template)
        assert hrefs.get("#root-route") == "navigate", (
            f"{template} has no Home control that truncates the stack: {hrefs}"
        )
        assert "/hv/dashboard/" not in hrefs, (
            f"{template} still opens the dashboard as a pushed card"
        )


def test_every_side_menu_link_also_closes_the_menu(user):
    # The side menu is a full-bleed overlay hosted by dashboard.xml alone, and NOTHING
    # in the client dismisses it on navigation: AnimatedSideMenu only closes on its own
    # x or scrim. Home is the obvious case (StackRouter NAVIGATE to the focused route
    # returns that same route, StackRouter.js:242-244, so nothing is even pushed), but
    # the other three are worse: they push a card over a dashboard that keeps the
    # overlay in its document, and the pop back never refetches (hv-doc.tsx:178-193),
    # so the scrim and the panel come back covering the whole bottom navigation.
    # Ordering is safe: getBehaviorElements unshifts the element itself
    # (services/dom/helpers.ts:8-18), so the navigate runs first and the replace is
    # queued against the dashboard route's own onUpdate, which survives the push.
    client = Client()
    client.force_login(user)

    root = ElementTree.fromstring(client.get("/hv/menu/").content)

    links = [
        view
        for view in root.iter(f"{{{HV}}}view")
        if "side-menu-link" in (view.attrib.get("style") or "").split()
    ]
    assert len(links) == 5, f"expected the five menu destinations, found {len(links)}"
    for link in links:
        close = link.find("./hv:behavior[@action='replace']", NS)
        assert close is not None, (
            f"{link.attrib['href']} would leave the menu open over the screen"
        )
        assert close.attrib["target"] == "side-menu-host"
        assert close.attrib["href"] == "/hv/menu/close/"


def test_every_fragment_href_names_a_route_the_server_actually_emits(user):
    # The literal in the template is coupled to todo/views.py. Ask the server for the
    # ids it can emit rather than restating them here, so the two cannot drift.
    anonymous = Client()
    signed_in = Client()
    signed_in.force_login(user)
    emitted = {
        route.attrib["id"]
        for client in (anonymous, signed_in)
        for route in ElementTree.fromstring(client.get("/hv/").content).findall(
            "./hv:navigator/hv:nav-route", NS
        )
    }
    # cleanHrefFragment strips the leading '#' before the dispatch is built.
    fragments = {
        href.lstrip("#") for _, href, _, _ in _scan_hrefs() if href.startswith("#")
    }
    assert fragments, "no fragment href found, so this guard is dead"
    assert fragments <= emitted, (
        f"these fragment hrefs name routes /hv/ never declares, so the control does "
        f"nothing at all when tapped: {sorted(fragments - emitted)}"
    )


# A form is opened with `navigate`, which getRouteId (:211-220) resolves to the
# dynamic `card` route: presentation 'card', the default horizontal push, and
# gestureEnabled on iOS (hv-navigator/index.tsx:187-212). `new` instead resolves to
# `modal`, and a modal route can only be dismissed by `close` -- which is what gave
# the forms their bottom-sheet presentation. Pinned client-side in
# mobile/__tests__/navigation-contract.test.tsx.
FORM_HREF = re.compile(r"^/hv/(tasks|categories)/(new/|\{\}/edit/)")


def test_every_task_and_category_form_opens_as_a_card():
    offenders = sorted(
        {
            f"{attribute}={href!r} action={action}"
            for attribute, href, _, action in _scan_hrefs()
            if action in DOCUMENT_ACTIONS and FORM_HREF.match(href)
            if action != "navigate"
        }
    )
    assert not offenders, (
        "these hrefs open a form as a bottom-sheet `modal`, which only action=close "
        "can dismiss, and close is a silent no-op everywhere else: "
        f"{offenders}"
    )


# on-event listeners are registered by HyperRef alone (hyper-ref.tsx:61, :133-157) and
# hv-element only wraps a component in HyperRef when it opts in with supportsHyperRef
# (components/hv-element/utils.tsx:16). HvList never sets it, so a listener parked on a
# <list> is silent dead markup -- it must live on an ancestor <view> instead. Pinned
# from the client side in mobile/__tests__/navigation-contract.test.tsx.
# The <list ...> branch has to swallow the whole start tag, not just the name: a
# self-closing `<list id="task-list" />` opens and closes in one token, and counting
# it as an opener would strand depth above zero and blame every later behavior in
# the file.
LIST_BOUNDARY = re.compile(r"</list\b|<list\b[^>]*>|<behavior\b[^>]*>", re.S)
COMMENT = re.compile(r"<!--.*?-->", re.S)


def parked_on_a_list(markup):
    """Return every on-event behavior nested inside a <list> in one template."""
    offenders, depth = [], 0
    for match in LIST_BOUNDARY.finditer(COMMENT.sub("", markup)):
        raw = match.group()
        if raw.startswith("</list"):
            depth -= 1
        elif raw.startswith("<list"):
            depth += 0 if raw.endswith("/>") else 1
        elif depth and dict(ATTRIBUTE.findall(raw)).get("trigger") == "on-event":
            offenders.append(raw)
    return offenders


def test_no_on_event_listener_is_parked_on_a_list_where_it_cannot_fire():
    offenders = [
        f"{path.name}: {raw}"
        for path in sorted(TEMPLATE_ROOT.rglob("*.xml"))
        for raw in parked_on_a_list(path.read_text())
    ]
    assert not offenders, (
        "these on-event listeners sit inside a <list>, which never registers them, "
        f"so the refresh they promise never happens: {offenders}"
    )


def test_the_list_guard_counts_a_self_closing_list_as_balanced():
    # No template ships an empty <list/> today, so the guard is green by luck rather
    # than by arithmetic: the first one added would make it blame innocent markup.
    listener = '<behavior trigger="on-event" action="reload" />'

    assert parked_on_a_list(f'<view><list id="task-list" />{listener}</view>') == []
    assert parked_on_a_list(f'<view><list id="task-list">{listener}</list></view>') == [
        listener
    ]


# `swipe-action` is DATA, not a component: SwipeRow reads those children off the
# element and filters them out of the content it renders. Everything else in the
# app namespace must be a registered component, because an unregistered tag is
# skipped with nothing but a Logging.info (services/render/index.tsx:71-85) -- the
# same silent nothing an unknown action name produces.
DATA_ONLY_ELEMENTS = {"swipe-action"}
MOBILE_ROOT = TEMPLATE_ROOT.parents[1] / "mobile"
APP_NAMESPACE = "https://hypertodo.app/components"


def _registered_local_names() -> set[str]:
    """Return the app-namespace tags App.tsx actually hands to Hyperview."""
    app = (MOBILE_ROOT / "App.tsx").read_text()
    # Either shape: the JSX literal, or the module-level const App.tsx hoisted the
    # array into so a theme re-render does not fail Hyperview's shallow prop compare.
    listed = re.search(r"components\s*=\s*\{?\[(.*?)\]", app, re.S)
    assert listed, "App.tsx no longer passes a components array"
    imports = dict(re.findall(r'import\s+(\w+)\s+from\s+"(\./[\w/.-]+)"', app))

    names = set()
    for identifier in (part.strip() for part in listed.group(1).split(",")):
        path = imports.get(identifier)
        assert path, f"{identifier} is registered but never imported"
        source = (MOBILE_ROOT / f"{path}.tsx").read_text()
        if APP_NAMESPACE in source:
            names.update(re.findall(r'localName:\s*"([\w-]+)"', source))
    return names


def test_no_template_ships_a_custom_element_the_client_cannot_render():
    used = {
        match.group(1)
        for path in sorted(TEMPLATE_ROOT.rglob("*.xml"))
        for match in re.finditer(r"<app:([\w-]+)", path.read_text())
    }
    assert used, "no custom element found, so this guard is dead"

    unknown = used - _registered_local_names() - DATA_ONLY_ELEMENTS
    assert not unknown, (
        "these tags reach the client as nothing at all, with only an info log to "
        f"say so: {sorted(unknown)}"
    )
