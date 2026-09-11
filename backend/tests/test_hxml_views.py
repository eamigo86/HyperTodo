"""HTTP contract tests for server-driven Hyperview screens."""

import re
from datetime import timedelta
from pathlib import Path
from xml.etree import ElementTree

import pytest
from dj_hyperview import HyperviewFragmentTemplateResponse
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.template.defaultfilters import date as date_filter
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from tests.test_forms_ui import contrast_ratio, read_png_icon, style_by_id
from todo import theme as theme_tokens
from todo.context_processors import THEME_COOKIE
from todo.middleware import THEME_HEADER
from todo.models import Category, Task
from todo.views import MIN_SWIPE_ACTIONS_VERSION, _supports_swipe_actions

pytestmark = pytest.mark.django_db
MEDIA_TYPE = "application/vnd.hyperview+xml"
FRAGMENT_MEDIA_TYPE = "application/vnd.hyperview_fragment+xml"
NS = {
    "hv": "https://hyperview.org/hyperview",
    "app": "https://hypertodo.app/components",
}


def assert_hxml(response, *, status=200, media_type=None):
    """Assert a response is parseable UTF-8 Hyperview XML."""
    assert response.status_code == status
    if media_type is None:
        media_type = (
            FRAGMENT_MEDIA_TYPE
            if isinstance(response, HyperviewFragmentTemplateResponse)
            else MEDIA_TYPE
        )
    assert response.headers["Content-Type"] == f"{media_type}; charset=utf-8"
    return ElementTree.fromstring(response.content)


def csrf_client():
    """Create a client that enforces Django CSRF checks."""
    return Client(enforce_csrf_checks=True)


def token_from(response):
    """Extract the CSRF value embedded for Hyperview forms."""
    root = ElementTree.fromstring(response.content)
    field = root.find(".//hv:text-field[@name='csrfmiddlewaretoken']", NS)
    assert field is not None
    return field.attrib["value"]


def assert_transition(response, transition_id, *, action, href=None, status=200):
    """Assert an HXML fragment contains the expected load transition.

    href=None means the action takes no href: close and back act on the stack,
    not on a url (services/navigator/navigator.ts:98-106).
    """
    root = assert_hxml(response, status=status)
    assert root.tag == f"{{{NS['hv']}}}view"
    assert root.attrib["id"] == transition_id
    behavior = root.find(f"./hv:behavior[@action='{action}']", NS)
    assert behavior is not None
    assert behavior.attrib["trigger"] == "load"
    assert behavior.attrib.get("href") == href
    return root


def announced_event(root):
    """Return the event name a fragment dispatches on load, or None."""
    behavior = root.find("./hv:behavior[@action='dispatch-event']", NS)
    if behavior is None:
        return None
    assert behavior.attrib["trigger"] == "load"
    return behavior.attrib["event-name"]


def assert_snackbar(root, message, *, tone="success"):
    """Assert an HXML response publishes one global snackbar notice."""
    behavior = root.find("./hv:behavior[@action='show-snackbar']", NS)
    assert behavior is not None
    assert behavior.attrib == {
        "trigger": "load",
        "action": "show-snackbar",
        "message": message,
        "tone": tone,
        "once": "true",
    }


def test_root_initializes_stack_navigator_for_guest_and_user(user):
    # The id is the same in both sessions and only the href moves. `#root-route` in
    # bottom_navigation.xml and side_menu.xml dispatches CommonActions.navigate
    # against this literal name, and StackRouter returns null for a name that is not
    # in routeNames (StackRouter.js:224-227) with no warning and no visual feedback.
    # A session-dependent id would make the Home tab silently dead after a sign-in.
    client = Client()

    def route_of(response):
        navigator = assert_hxml(response).find(
            ".//hv:navigator[@id='root-navigator']", NS
        )
        assert navigator is not None
        assert navigator.attrib["type"] == "stack"
        routes = navigator.findall("./hv:nav-route", NS)
        assert len(routes) == 1
        assert routes[0].attrib["selected"] == "true"
        return routes[0]

    anonymous = route_of(client.get(reverse("todo:root")))
    assert anonymous.attrib["id"] == "root-route"
    assert anonymous.attrib["href"] == "/hv/login/"

    client.force_login(user)
    authenticated = route_of(client.get(reverse("todo:root")))
    assert authenticated.attrib["id"] == "root-route"
    assert authenticated.attrib["href"] == "/hv/dashboard/"


@pytest.mark.parametrize("route_name", ["tasks", "categories"])
def test_mutable_hxml_lists_disable_the_native_http_cache(user, route_name):
    """Require fresh mutable list data for navigation and fragment refreshes."""
    client = Client()
    client.force_login(user)

    document = client.get(reverse(f"todo:{route_name}"))
    fragment = client.get(reverse(f"todo:{route_name}"), {"fragment": "list"})

    for response in (document, fragment):
        assert_hxml(response)
        cache_control = response.headers["Cache-Control"]
        directives = {directive.strip() for directive in cache_control.split(",")}
        assert {"private", "no-store"} <= directives


def test_login_screen_uses_secure_credentials_and_fragment_submission():
    response = Client().get(reverse("todo:login"))
    root = assert_hxml(response)

    screen_style = root.find(".//hv:style[@id='login-body']", NS)
    error_style = root.find(".//hv:style[@id='error-text']", NS)
    username = root.find(".//hv:text-field[@name='username']", NS)
    password = root.find(".//hv:text-field[@name='password']", NS)
    submit = root.find(".//hv:view[@id='login-submit']", NS)

    assert screen_style is not None
    assert screen_style.attrib["flex"] == "1"
    assert error_style is not None
    assert error_style.attrib["color"] == "#B42318"
    assert username is not None
    assert username.attrib["text-content-type"] == "username"
    assert password is not None
    assert password.attrib["secure-text"] == "true"
    assert password.attrib["text-content-type"] == "password"
    assert "secure-text-entry" not in password.attrib
    assert submit is not None
    assert submit.attrib["action"] == "replace"
    assert submit.attrib["target"] == "login-panel"
    visible_text = "".join(root.itertext())
    assert "PLAN WITH INTENTION" not in visible_text
    hero_mark = root.find(".//hv:text[@style='hero-mark-check']", NS)
    assert hero_mark is not None
    assert hero_mark.text == "✓"


def test_login_requires_csrf_and_returns_direct_hxml(user):
    client = csrf_client()
    response = client.get(reverse("todo:login"))
    token = token_from(response)
    rejected = client.post(
        reverse("todo:login"),
        {"username": "ada", "password": "wrong", "csrfmiddlewaretoken": token},
    )
    rejected_root = assert_hxml(rejected, status=422)
    assert rejected_root.tag == f"{{{NS['hv']}}}view"
    assert rejected_root.attrib["id"] == "login-panel"
    error = rejected_root.find(".//hv:view[@id='login-error']/hv:text", NS)
    assert error is not None
    assert error.attrib["style"] == "error-text"
    # The panel renders the form's own error now, so an empty submit no longer
    # claims the credentials were wrong. views.py adds this exact string.
    assert error.text == "The username or password is incorrect."
    username = rejected_root.find(".//hv:text-field[@name='username']", NS)
    assert username is not None
    assert username.attrib["value"] == "ada"
    accepted = client.post(
        reverse("todo:login"),
        {"username": "ada", "password": "correct-horse", "csrfmiddlewaretoken": token},
    )
    root = assert_hxml(accepted)
    assert root.tag == f"{{{NS['hv']}}}view"
    assert root.attrib["id"] == "login-transition"
    # `reload /hv/dashboard/`, not `navigate` and not `reload /hv/`. This fragment
    # replaced the login sheet, so navigating away left an emptied login screen alive
    # at index 0 of the stack, one iOS swipe-back from the dashboard. Reloading a
    # SCREEN url repoints this route instead; reloading /hv/ would hand a navigator
    # document to a screen route, which HvDoc cannot merge and so renders as a stack
    # nested inside this route, one level deeper on every login (hv-doc.tsx:120-131).
    transition = root.find("./hv:behavior[@action='reload']", NS)
    assert transition is not None
    assert transition.attrib == {
        "trigger": "load",
        "href": "/hv/dashboard/",
        "action": "reload",
    }
    assert accepted.status_code != 302
    assert client.session["_auth_user_id"] == str(user.pk)


def test_login_post_without_csrf_is_hxml_403(user):
    response = csrf_client().post(
        reverse("todo:login"), {"username": "ada", "password": "correct-horse"}
    )
    assert_hxml(response, status=403)


def test_anonymous_private_route_returns_session_expired_hxml():
    response = Client().get(reverse("todo:tasks"))
    root = assert_hxml(response, status=401)
    assert root.find(".//hv:screen[@id='session-expired-screen']", NS) is not None


def test_task_form_has_back_action_visible_categories_and_time_keypad(user):
    client = Client()
    client.force_login(user)
    Category.objects.create(user=user, name="Work", color=Category.Color.LAVENDER)

    root = assert_hxml(client.get(reverse("todo:task-new")))
    back = root.find(".//hv:view[@id='task-back']", NS)
    due_date = root.find(".//hv:date-field[@name='due_date']", NS)
    due_time = root.find(".//hv:text-field[@name='due_time']", NS)
    category = root.find(".//hv:picker-field[@name='category']", NS)

    assert back is not None
    assert back.attrib["action"] == "back"
    assert due_date is not None
    assert due_date.attrib["field-style"] == "field"
    assert due_date.attrib["placeholder"] == "Select due date"
    assert due_date.attrib["modal-style"] == "date-modal"
    assert due_date.attrib["modal-overlay-style"] == "date-modal-overlay"
    assert due_date.attrib["modal-text-style"] == "date-modal-action"
    modal = root.find(".//hv:style[@id='date-modal']", NS)
    overlay = root.find(".//hv:style[@id='date-modal-overlay']", NS)
    assert modal is not None
    assert modal.attrib["backgroundColor"] == "#FFFFFF"
    assert overlay is not None
    assert overlay.attrib["backgroundColor"] == "#161A35"
    assert due_time is not None
    assert due_time.attrib["keyboard-type"] == "number-pad"
    assert due_time.attrib["mask"] == "99:99"
    assert category is not None
    labels = [node.attrib["label"] for node in category.findall("./hv:picker-item", NS)]
    assert labels == ["No category", "Work"]


def test_navigation_buttons_use_symbol_only(user):
    client = Client()
    client.force_login(user)

    for route in (reverse("todo:task-new"), reverse("todo:tasks")):
        root = assert_hxml(client.get(route))
        back = root.find(".//hv:view[@action='back']", NS)
        assert back is not None
        chevron = back.find("./hv:text[@style='back-chevron']", NS)
        label = back.find("./hv:text[@style='back-label']", NS)
        assert chevron is not None
        assert chevron.text == "‹"
        assert label is not None
        assert label.text == "Back"


def freeze_local(monkeypatch, *, hour=12):
    """Freeze timezone.now at a local hour of the current day.

    Patching the shared django.utils.timezone.now freezes auto_now_add too.
    """
    now = timezone.localtime().replace(hour=hour, minute=0, second=0, microsecond=0)
    monkeypatch.setattr("django.utils.timezone.now", lambda: now)
    return now


def dashboard_root(user):
    """Render the dashboard screen for one user."""
    client = Client()
    client.force_login(user)
    return assert_hxml(client.get(reverse("todo:dashboard")))


def text_of(root, node_id):
    """Return the concatenated text of one identified node."""
    node = root.find(f".//hv:*[@id='{node_id}']", NS)
    assert node is not None, node_id
    return "".join(node.itertext())


@pytest.mark.parametrize(
    ("hour", "greeting"),
    [
        (8, "Good morning"),
        (11, "Good morning"),
        (12, "Good afternoon"),
        (13, "Good afternoon"),
        (17, "Good afternoon"),
        (18, "Good evening"),
        (20, "Good evening"),
    ],
)
def test_dashboard_hero_greets_the_user_by_local_hour(
    user, monkeypatch, hour, greeting
):
    freeze_local(monkeypatch, hour=hour)

    assert greeting in text_of(dashboard_root(user), "dashboard-hero")


def test_dashboard_hero_shows_initials_and_today_progress(user, monkeypatch):
    now = freeze_local(monkeypatch)
    user.first_name = "Ada"
    user.last_name = "Lovelace"
    user.save(update_fields=("first_name", "last_name"))
    Task.objects.create(user=user, title="Open", due_at=now.replace(hour=23))
    Task.objects.create(
        user=user, title="Closed", due_at=now.replace(hour=9), completed_at=now
    )

    root = dashboard_root(user)
    hero = root.find(".//hv:view[@id='dashboard-hero']", NS)
    progress = root.find(".//hv:view[@id='dashboard-progress']", NS)

    assert hero is not None
    assert "AL" in "".join(hero.itertext())
    assert "Ada" in "".join(hero.itertext())
    assert text_of(root, "dashboard-progress-label") == "1 of 2 done today"
    assert progress is not None
    fill = progress.find("./hv:view", NS)
    assert "progress-5" in fill.attrib["style"].split()
    bucket = root.find(".//hv:style[@id='progress-5']", NS)
    assert bucket is not None
    assert bucket.attrib["width"] == "50%"
    # The retired hero-icon stays retired, and so does the disclosure chevron: the
    # avatar disc is the menu trigger on its own, so the hero ships no images at all.
    assert [image.attrib["style"] for image in hero.findall(".//hv:image", NS)] == []
    assert root.find(".//hv:style[@id='hero-icon']", NS) is None


def test_dashboard_hero_falls_back_to_username_initials(user, monkeypatch):
    freeze_local(monkeypatch)

    hero_text = text_of(dashboard_root(user), "dashboard-hero")

    assert "AD" in hero_text
    assert "ada" in hero_text
    assert "0 of 0 done today" in hero_text


def test_dashboard_hero_caption_dates_the_day_and_rates_momentum(user, monkeypatch):
    now = freeze_local(monkeypatch)
    today_label = date_filter(timezone.localdate(now), "l, M j")

    idle_caption = text_of(dashboard_root(user), "dashboard-hero")
    Task.objects.create(user=user, title="Open", due_at=now.replace(hour=23))
    Task.objects.create(user=user, title="Also open", due_at=now.replace(hour=22))
    behind_caption = text_of(dashboard_root(user), "dashboard-hero")

    assert f"{today_label} · you're on track" in idle_caption
    assert f"{today_label} · let's get moving" in behind_caption


def test_dashboard_tiles_render_labels_and_filtered_destinations(user):
    client = Client()
    client.force_login(user)
    root = assert_hxml(client.get(reverse("todo:dashboard")))

    expected = {
        "dashboard-today": ("Today", "/hv/tasks/?status=today"),
        "dashboard-scheduled": ("Scheduled", "/hv/tasks/?status=scheduled"),
        "dashboard-all": ("All", "/hv/tasks/?status=all"),
        "dashboard-overdue": ("Overdue", "/hv/tasks/?status=overdue"),
    }
    for tile_id, (label, href) in expected.items():
        tile = root.find(f".//hv:view[@id='{tile_id}']", NS)
        assert tile is not None
        assert tile.attrib["href"] == href
        assert tile.attrib["action"] == "navigate"
        assert label in "".join(tile.itertext())


def test_dashboard_stat_cards_share_one_horizontal_row(user, monkeypatch):
    now = freeze_local(monkeypatch)
    Task.objects.create(user=user, title="Due today", due_at=now.replace(hour=23))
    Task.objects.create(user=user, title="Late", due_at=now - timedelta(days=1))
    Task.objects.create(user=user, title="Later", due_at=now + timedelta(days=2))
    Task.objects.create(user=user, title="Done", completed_at=now)

    root = dashboard_root(user)
    row = root.find(".//hv:view[@id='dashboard-stats']", NS)

    assert row is not None
    assert row.attrib["scroll"] == "true"
    assert row.attrib["scroll-orientation"] == "horizontal"
    assert row.attrib["shows-scroll-indicator"] == "false"
    assert row.attrib["content-container-style"] == "stat-row-content"
    assert [child.attrib["id"] for child in row.findall("./hv:view", NS)] == [
        "dashboard-all",
        "dashboard-today",
        "dashboard-overdue",
        "dashboard-scheduled",
    ]
    row_style = root.find(".//hv:style[@id='stat-row']", NS)
    content_style = root.find(".//hv:style[@id='stat-row-content']", NS)
    card_style = root.find(".//hv:style[@id='stat-card']", NS)
    icon_style = root.find(".//hv:style[@id='stat-icon']", NS)
    assert row_style is not None
    assert row_style.attrib["marginTop"] == "-34"
    assert "flexDirection" not in row_style.attrib
    assert content_style is not None
    assert content_style.attrib["flexDirection"] == "row"
    assert content_style.attrib["gap"] == "12"
    assert content_style.attrib["paddingHorizontal"] == "24"
    assert card_style is not None
    assert card_style.attrib["width"] == "132"
    assert card_style.attrib["borderRadius"] == "16"
    assert card_style.attrib["borderColor"] == "#E9ECF5"
    assert card_style.attrib["backgroundColor"] == "#FFFFFF"
    assert icon_style is not None
    assert icon_style.attrib == {"id": "stat-icon", "height": "16", "width": "16"}

    icons = {
        "dashboard-today": "sun.png",
        "dashboard-overdue": "alert.png",
        "dashboard-scheduled": "calendar.png",
        "dashboard-all": "list.png",
    }
    for card_id, icon in icons.items():
        card = row.find(f"./hv:view[@id='{card_id}']", NS)
        image = card.find(f".//hv:image[@style='{icon_style.attrib['id']}']", NS)
        assert image is not None, card_id
        assert image.attrib["source"].endswith(f"/todo/icons/{icon}")

    label = (now + timedelta(days=2)).strftime("%a")
    assert "+1 done last 7 days" in text_of(root, "dashboard-today")
    assert "needs attention" in text_of(root, "dashboard-overdue")
    assert f"next: {label}" in text_of(root, "dashboard-scheduled")
    assert "4 total" in text_of(root, "dashboard-all")


def test_dashboard_overdue_card_appears_only_when_work_is_late(user, monkeypatch):
    now = freeze_local(monkeypatch)

    quiet = dashboard_root(user)
    Task.objects.create(user=user, title="Late", due_at=now - timedelta(days=1))
    Task.objects.create(user=user, title="Later", due_at=now - timedelta(days=2))
    alerted = dashboard_root(user)
    card = alerted.find(".//hv:view[@id='dashboard-overdue-card']", NS)

    assert quiet.find(".//hv:view[@id='dashboard-overdue-card']", NS) is None
    assert card is not None
    assert "2 overdue" in "".join(card.itertext())
    review = card.find(".//hv:view[@href='/hv/tasks/?status=overdue']", NS)
    assert review is not None
    assert review.attrib["action"] == "navigate"
    assert "Review" in "".join(review.itertext())


def test_dashboard_up_next_rows_open_edit_and_toggle_the_content_fragment(
    user, monkeypatch
):
    now = freeze_local(monkeypatch)
    work = Category.objects.create(
        user=user, name="Work", color=Category.Color.LAVENDER
    )
    task = Task.objects.create(
        user=user, category=work, title="Ship it", due_at=now.replace(hour=17)
    )

    root = dashboard_root(user)
    section = root.find(".//hv:view[@id='dashboard-up-next']", NS)
    see_all = section.find(".//hv:view[@href='/hv/tasks/?status=active']", NS)
    row = section.find(f".//hv:view[@id='dashboard-task-{task.pk}']", NS)
    toggle = section.find(f".//hv:view[@id='dashboard-toggle-{task.pk}']", NS)

    assert "Up next" in "".join(section.itertext())
    assert see_all is not None
    assert see_all.attrib["action"] == "navigate"
    assert "See all" in "".join(see_all.itertext())
    assert row is not None
    assert row.attrib["href"] == f"/hv/tasks/{task.pk}/edit/"
    # `navigate`, not `new`: the form's transition ends in action="back", which pops
    # the focused route whatever its presentation (navigator.ts:33-77). `navigate`
    # resolves to the dynamic `card` route, so the form slides in from the right and
    # keeps the iOS swipe-back gesture that the modal presentation suppressed.
    assert row.attrib["action"] == "navigate"
    assert "Ship it" in "".join(row.itertext())
    assert "17:00 · Work" in "".join(row.itertext())
    assert row.find(".//hv:image[@style='row-chevron']", NS) is not None
    assert toggle is not None
    assert toggle.attrib["href"] == f"/hv/tasks/{task.pk}/toggle/?panel=dashboard"
    assert toggle.attrib["verb"] == "post"
    assert toggle.attrib["action"] == "replace"
    assert toggle.attrib["target"] == "dashboard-content"
    assert toggle.attrib["href-style"] == "toggle-hit-area"
    hit_area = root.find(".//hv:style[@id='toggle-hit-area']", NS)
    assert hit_area is not None
    assert hit_area.attrib["height"] == "44"
    assert hit_area.attrib["width"] == "44"
    assert hit_area.attrib["marginRight"] == "12"
    assert "marginRight" not in root.find(".//hv:style[@id='toggle']", NS).attrib
    form = section.find(".//hv:form", NS)
    assert form is not None
    assert form.find("./hv:text-field[@name='csrfmiddlewaretoken']", NS) is not None


def test_dashboard_up_next_lists_only_open_work(user, monkeypatch):
    now = freeze_local(monkeypatch)
    empty = dashboard_root(user)
    done = Task.objects.create(
        user=user, title="Archived", due_at=now.replace(hour=9), completed_at=now
    )
    open_task = Task.objects.create(
        user=user, title="Still open", due_at=now.replace(hour=18)
    )
    filled = dashboard_root(user)
    up_next = text_of(filled, "dashboard-up-next")

    assert "Nothing due next" in text_of(empty, "dashboard-up-next")
    assert "Still open" in up_next
    assert "Archived" not in up_next
    assert filled.find(f".//hv:view[@id='dashboard-task-{done.pk}']", NS) is None
    assert (
        filled.find(f".//hv:view[@id='dashboard-task-{open_task.pk}']", NS) is not None
    )


def test_dashboard_week_card_scales_bars_and_marks_today(user, monkeypatch):
    now = freeze_local(monkeypatch)
    for index in range(2):
        Task.objects.create(user=user, title=f"Today {index}", completed_at=now)
    Task.objects.create(
        user=user, title="Yesterday", completed_at=now - timedelta(days=1)
    )

    root = dashboard_root(user)
    week = root.find(".//hv:view[@id='dashboard-week']", NS)
    bars = [week.find(f".//hv:view[@id='dashboard-bar-{i}']", NS) for i in range(1, 8)]

    assert "Last 7 days" in "".join(week.itertext())
    assert "3 done · 2-day streak" in "".join(week.itertext())
    assert all(bar is not None for bar in bars)
    assert "bar-8" in bars[6].attrib["style"].split()
    assert "bar-today" in bars[6].attrib["style"].split()
    assert "bar-4" in bars[5].attrib["style"].split()
    assert "bar-idle" in bars[0].attrib["style"].split()
    assert "bar-today" not in bars[0].attrib["style"].split()

    track = root.find(".//hv:style[@id='bar-track']", NS)
    assert track.attrib["alignItems"] == "flex-end"
    assert track.attrib["height"] == "52"
    assert root.find(".//hv:style[@id='bar-8']", NS).attrib["height"] == "48"
    assert root.find(".//hv:style[@id='bar-4']", NS).attrib["height"] == "24"
    assert root.find(".//hv:style[@id='bar-1']", NS).attrib["height"] == "6"
    bar_style = root.find(".//hv:style[@id='bar']", NS)
    assert bar_style.attrib["backgroundColor"] == "#AEBBFA"
    assert (
        root.find(".//hv:style[@id='bar-today']", NS).attrib["backgroundColor"]
        == "#278CFF"
    )
    assert (
        root.find(".//hv:style[@id='bar-idle']", NS).attrib["backgroundColor"]
        == "#E9ECF5"
    )

    labels = week.findall(".//hv:text[@style='bar-label']", NS)
    today_label = week.find(".//hv:text[@style='bar-label bar-label-today']", NS)
    assert len(labels) == 6
    assert today_label is not None
    assert today_label.text == "MTWTFSS"[timezone.localdate(now).weekday()]


def test_dashboard_category_chips_filter_the_task_list(user, monkeypatch):
    freeze_local(monkeypatch)
    work = Category.objects.create(
        user=user, name="Work", color=Category.Color.LAVENDER
    )
    admin = Category.objects.create(user=user, name="Admin", color=Category.Color.MINT)
    Task.objects.create(user=user, category=work, title="Open")

    root = dashboard_root(user)
    section = root.find(".//hv:view[@id='dashboard-categories']", NS)
    chips = section.findall("./hv:view", NS)

    assert section.attrib["scroll"] == "true"
    assert section.attrib["scroll-orientation"] == "horizontal"
    assert section.attrib["content-container-style"] == "chip-row-content"
    chip_content = root.find(".//hv:style[@id='chip-row-content']", NS)
    assert chip_content is not None
    assert chip_content.attrib["flexDirection"] == "row"
    assert chip_content.attrib["gap"] == "8"
    assert chip_content.attrib["paddingHorizontal"] == "24"
    assert "flexDirection" not in root.find(".//hv:style[@id='chip-row']", NS).attrib
    assert [chip.attrib["href"] for chip in chips] == [
        f"/hv/tasks/?category={admin.pk}",
        f"/hv/tasks/?category={work.pk}",
    ]
    assert all(chip.attrib["action"] == "navigate" for chip in chips)
    # Every chip is a live navigate target, so it owes the 44pt floor the identical
    # chip on the tasks screen already meets. paddingVertical="9" around 13px text
    # drew about 34pt.
    assert int(root.find(".//hv:style[@id='chip']", NS).attrib["minHeight"]) >= 44
    assert "Admin · 0" in "".join(chips[0].itertext())
    assert "Work · 1" in "".join(chips[1].itertext())
    assert "mint" in chips[0].attrib["style"]
    assert "lavender" in chips[1].attrib["style"]


def test_dashboard_hides_the_category_strip_without_categories(user, monkeypatch):
    freeze_local(monkeypatch)

    root = dashboard_root(user)

    assert root.find(".//hv:view[@id='dashboard-categories']", NS) is None


def test_bottom_navigation_sits_on_the_canvas_colour(user):
    client = Client()
    client.force_login(user)

    for route in ("todo:dashboard", "todo:tasks", "todo:categories"):
        root = assert_hxml(client.get(reverse(route)))
        style = root.find(".//hv:style[@id='bottom-navigation-style']", NS)
        assert style is not None, route
        assert style.attrib["backgroundColor"] == "#F7F8FC"
        assert style.attrib["borderTopWidth"] == "1"
        assert style.attrib["borderTopColor"] == "#E9ECF5"


def test_dashboard_delegates_task_creation_to_the_tab_bar(user, monkeypatch):
    freeze_local(monkeypatch)

    root = dashboard_root(user)

    assert "+ Add task" not in "".join(root.itertext())
    assert root.find(".//hv:style[@id='primary']", NS) is None
    assert root.find(".//hv:view[@id='nav-add-task']", NS) is not None


def test_dashboard_hero_escapes_user_supplied_names(db, monkeypatch):
    freeze_local(monkeypatch)
    hostile = get_user_model().objects.create_user(
        username='<ada> & "co"', password="correct-horse"
    )

    hero = text_of(dashboard_root(hostile), "dashboard-hero")

    assert '<ada> & "co"' in hero


def test_dashboard_stat_cards_report_a_quiet_day(user, monkeypatch):
    freeze_local(monkeypatch)

    root = dashboard_root(user)
    today_card = root.find(".//hv:view[@id='dashboard-today']", NS)

    assert "all clear" in text_of(root, "dashboard-overdue")
    assert "nothing planned" in text_of(root, "dashboard-scheduled")
    assert today_card.find("./hv:text[@style='stat-note']", NS).text == (
        "nothing done yet"
    )
    assert today_card.find("./hv:text[@style='stat-note stat-note-good']", NS) is None


def test_secondary_screens_use_centered_blue_destination_headers(user):
    client = Client()
    client.force_login(user)

    routes = {
        reverse("todo:tasks"): ("task-list-back", "Tasks"),
        reverse("todo:categories"): ("category-list-back", "Categories"),
        reverse("todo:task-new"): ("task-back", "New task"),
        reverse("todo:category-new"): ("category-back", "New category"),
    }
    for route, (back_id, title) in routes.items():
        root = assert_hxml(client.get(route))
        header = root.find(".//hv:view[@id='screen-header']", NS)
        header_style = root.find(".//hv:style[@id='screen-header-style']", NS)
        back = root.find(f".//hv:view[@id='{back_id}']", NS)
        heading = root.find(".//hv:text[@style='screen-header-title']", NS)

        assert header is not None
        assert header_style is not None
        assert header_style.attrib["backgroundColor"] == "#278CFF"
        assert header_style.attrib["height"] == "44"
        assert back is not None
        assert back.attrib["action"] == "back"
        chevron = back.find("./hv:text[@style='back-chevron']", NS)
        label = back.find("./hv:text[@style='back-label']", NS)
        assert chevron is not None
        assert chevron.text == "‹"
        assert label is not None
        assert label.text == "Back"
        back_style = root.find(".//hv:style[@id='back-button']", NS)
        title_slot = root.find(".//hv:view[@style='screen-header-title-slot']", NS)
        spacer = root.find(".//hv:view[@style='screen-header-spacer']", NS)
        spacer_style = root.find(".//hv:style[@id='screen-header-spacer']", NS)
        assert back_style is not None
        assert back_style.attrib["width"] == "84"
        assert "position" not in back_style.attrib
        assert title_slot is not None
        assert spacer is not None
        assert spacer_style is not None
        assert spacer_style.attrib["width"] == back_style.attrib["width"]
        assert heading is not None
        assert heading.text == title


def test_task_screen_scrolls_and_makes_dashboard_filter_visible(user, monkeypatch):
    now = freeze_local(monkeypatch)
    today_due = timezone.localtime(now).replace(
        hour=23, minute=59, second=59, microsecond=0
    )
    Task.objects.create(user=user, title="Due today", due_at=today_due)
    Task.objects.create(user=user, title="Due later", due_at=now + timedelta(days=3))
    Task.objects.create(user=user, title="Past due", due_at=now - timedelta(days=1))
    client = Client()
    client.force_login(user)

    expected = {
        "today": ("Due today", {"Due later", "Past due"}),
        "scheduled": ("Due later", {"Due today", "Past due"}),
        "overdue": ("Past due", {"Due today", "Due later"}),
    }
    for status_filter, (included, excluded) in expected.items():
        root = assert_hxml(client.get(reverse("todo:tasks"), {"status": status_filter}))
        content = root.find(".//hv:view[@id='screen-content']", NS)
        task_list = root.find(".//hv:list[@id='task-list']", NS)
        selected = root.find(f".//hv:view[@id='filter-{status_filter}']", NS)
        summary = root.find(".//hv:text[@id='filter-summary']", NS)
        visible_text = "".join(root.itertext())

        assert content is not None
        assert "scroll" not in content.attrib
        assert task_list is not None
        assert task_list.attrib["style"] == "task-list-style"
        assert selected is not None
        assert "chip-active" in selected.attrib["style"]
        assert summary is not None
        assert status_filter.title() in (summary.text or "")
        assert included in visible_text
        assert excluded.isdisjoint(visible_text)


def test_category_form_has_back_navigation_and_selectable_color_options(user):
    client = Client()
    client.force_login(user)
    root = assert_hxml(client.get(reverse("todo:category-new")))

    back = root.find(".//hv:view[@id='category-back']", NS)
    color = root.find(".//hv:select-single[@name='color']", NS)
    submit = root.find(".//hv:view[@id='category-submit']", NS)

    assert back is not None
    assert back.attrib["action"] == "back"
    chevron = back.find("./hv:text[@style='back-chevron']", NS)
    label = back.find("./hv:text[@style='back-label']", NS)
    assert chevron is not None
    assert chevron.text == "‹"
    assert label is not None
    assert label.text == "Back"
    assert color is not None
    labels = [node.text for node in color.findall("./hv:option/hv:text", NS)]
    assert labels == ["Lavender", "Yellow", "Mint", "Pink", "Green"]
    assert submit is not None
    assert submit.attrib["action"] == "replace"
    assert submit.attrib["target"] == "category-form-panel"


# test_the_menu_chevron_ships_in_the_colour_it_renders_in is gone with its subject:
# the hero draws no chevron and chevron-down.png no longer ships, so there is no
# artefact left to decode. What it protected -- that the side-menu trigger clears 3:1
# against the hero band -- is now covered by test_settings.py's
# test_the_dashboard_avatar_survives_its_own_press_state, which checks the disc
# against the band AND the initials against the disc, at rest and pressed.


def test_the_stat_icons_are_dark_enough_for_the_badge_they_sit_in(user, monkeypatch):
    # stat-icon sets no tintColor either, so the export colour is the render
    # colour. Both sides of this ratio come off the shipped artefacts: the glyph
    # from the file, the fill from the screen's own stylesheet.
    freeze_local(monkeypatch)
    root = dashboard_root(user)
    row = root.find(".//hv:view[@id='dashboard-stats']", NS)

    for card in row.findall("./hv:view", NS):
        badge = card.find("./hv:view", NS)
        image = badge.find("./hv:image", NS)
        tones = [name for name in badge.attrib["style"].split() if name != "stat-badge"]
        assert len(tones) == 1, badge.attrib["style"]
        fill = root.find(f".//hv:style[@id='{tones[0]}']", NS).attrib["backgroundColor"]
        source = image.attrib["source"].rsplit("/", 1)[-1]
        icon = read_png_icon(finders.find(f"todo/icons/{source}"))

        assert contrast_ratio(icon.colour, fill) >= 3, (
            f"{card.attrib['id']}: {icon.colour} on {fill}"
        )


# test_the_nav_icons_are_baked_in_the_colours_the_nav_labels_declare is gone with
# its subject: home-active.png and its three twins were deleted when the glyphs
# moved to tintColor, and a baked colour is no longer what renders. The tie it
# made -- glyph colour equals the colour of the word under it -- is now made
# style to style, in BOTH palettes, by
# tests/test_theme_icons.py, test_the_nav_glyph_is_tinted_the_colour_the_nav_label
# _declares, which reads the tint the style declares instead of the file's pixels.


def test_task_toggle_from_the_dashboard_returns_the_content_fragment(user, monkeypatch):
    now = freeze_local(monkeypatch)
    task = Task.objects.create(user=user, title="Ship it", due_at=now.replace(hour=17))
    work = Category.objects.create(
        user=user, name="Work", color=Category.Color.LAVENDER
    )
    Task.objects.create(
        user=user, category=work, title="Next up", due_at=now + timedelta(days=3)
    )
    client = csrf_client()
    client.force_login(user)
    screen_response = client.get(reverse("todo:dashboard"))
    screen = assert_hxml(screen_response)
    token = token_from(screen_response)

    response = client.post(
        f"{reverse('todo:task-toggle', args=(task.pk,))}?panel=dashboard",
        {"csrfmiddlewaretoken": token},
    )
    root = assert_hxml(response, media_type=FRAGMENT_MEDIA_TYPE)
    task.refresh_from_db()

    assert root.tag == f"{{{NS['hv']}}}view"
    assert root.attrib["id"] == "dashboard-content"
    assert root.find(".//hv:screen", NS) is None
    assert response.headers["Content-Type"] == (f"{FRAGMENT_MEDIA_TYPE}; charset=utf-8")
    assert task.is_completed
    assert "1 of 1 done today" in "".join(root.itertext())
    assert root.find(f".//hv:view[@id='dashboard-task-{task.pk}']", NS) is None
    assert "1 done · 1-day streak" in "".join(root.itertext())

    # `.//hv:style` also matches a <style> nested in a <modifier>, which has no id
    # and turns this guard into a KeyError instead of a style assertion.
    defined = {
        style.attrib["id"]
        for style in screen.findall("./hv:screen/hv:styles/hv:style", NS)
    }
    used = {
        style_id
        for node in root.iter()
        for name, value in node.attrib.items()
        if name.endswith("style")
        for style_id in value.split()
    }
    assert used
    assert used <= defined


def test_task_create_edit_toggle_delete_flow_uses_hxml_and_csrf(user):
    client = csrf_client()
    client.force_login(user)
    form_response = client.get(reverse("todo:task-new"))
    form_root = assert_hxml(form_response)
    submit = form_root.find(".//hv:view[@id='task-submit']", NS)
    assert submit is not None
    assert submit.attrib["action"] == "replace"
    assert submit.attrib["target"] == "task-form-panel"
    token = token_from(form_response)
    created = client.post(
        reverse("todo:task-new"),
        {
            "title": "Write XML",
            "notes": "Safely",
            "category": "",
            "due_date": "2026-09-07",
            "due_time": "09:15",
            "csrfmiddlewaretoken": token,
        },
    )
    # `back`, not `navigate`: this fragment replaced the whole form panel, so the form
    # screen is empty and has to be popped rather than left in the stack behind a
    # freshly pushed task list.
    created_root = assert_transition(
        created,
        "task-transition",
        action="back",
        status=201,
    )
    assert_snackbar(created_root, "Task created.")
    task = Task.objects.get(user=user)

    edit_response = client.get(reverse("todo:task-edit", args=(task.pk,)))
    edit_token = token_from(edit_response)
    updated = client.post(
        reverse("todo:task-edit", args=(task.pk,)),
        {
            "title": "Ship XML",
            "notes": "",
            "category": "",
            "due_date": "",
            "due_time": "",
            "csrfmiddlewaretoken": edit_token,
        },
    )
    updated_root = assert_transition(updated, "task-transition", action="back")
    assert_snackbar(updated_root, "Task updated.")
    task.refresh_from_db()
    assert task.title == "Ship XML"

    toggled = client.post(
        reverse("todo:task-toggle", args=(task.pk,)),
        {"csrfmiddlewaretoken": edit_token},
    )
    toggled_root = assert_transition(
        toggled, "task-list-transition", action="dispatch-event"
    )
    assert announced_event(toggled_root) == "tasks-changed"
    assert_snackbar(toggled_root, "Task completed.")
    task.refresh_from_db()
    assert task.completed_at is not None

    deleted = client.post(
        reverse("todo:task-delete", args=(task.pk,)),
        {"csrfmiddlewaretoken": edit_token},
    )
    deleted_root = assert_transition(
        deleted, "task-list-transition", action="dispatch-event"
    )
    assert_snackbar(deleted_root, "Task deleted.")
    assert not Task.objects.filter(pk=task.pk).exists()


def test_invalid_task_form_returns_422_hxml(user):
    client = csrf_client()
    client.force_login(user)
    token = token_from(client.get(reverse("todo:task-new")))
    response = client.post(
        reverse("todo:task-new"),
        {"title": "", "due_time": "09:00", "csrfmiddlewaretoken": token},
    )
    root = assert_hxml(response, status=422)
    assert root.tag == f"{{{NS['hv']}}}view"
    assert root.attrib["id"] == "task-form-panel"
    # Selected by style and document order: an id on a <text> becomes the Android
    # accessible name (services/index.ts:161 then :81-84), so these error nodes
    # carry none. Title is the first field on the form and due_time the last.
    summary = root.find(".//hv:view[@style='error-card']/hv:text", NS)
    title_error, due_time_error = root.findall(".//hv:text[@style='field-error']", NS)
    title = root.find(".//hv:text-field[@name='title']", NS)
    due_time = root.find(".//hv:text-field[@name='due_time']", NS)

    assert summary is not None
    assert summary.text == "Review the fields marked in red."
    assert title_error is not None
    assert title_error.text == "This field is required."
    assert due_time_error is not None
    assert due_time_error.text == "A due date is required when a time is set."
    assert title is not None
    assert "field-invalid" in title.attrib["style"]
    assert due_time is not None
    assert "field-invalid" in due_time.attrib["style"]
    assert_snackbar(root, "Please review the highlighted task details.", tone="error")


def test_category_crud_and_cross_user_resources_are_hidden(user, other_user):
    client = csrf_client()
    client.force_login(user)
    token = token_from(client.get(reverse("todo:category-new")))
    created = client.post(
        reverse("todo:category-new"),
        {"name": "Work", "color": "lavender", "csrfmiddlewaretoken": token},
    )
    created_root = assert_hxml(created, status=201)
    assert created_root.tag == f"{{{NS['hv']}}}view"
    assert created_root.attrib["id"] == "category-transition"
    behaviors = created_root.findall("./hv:behavior", NS)
    assert [behavior.attrib for behavior in behaviors] == [
        {
            "trigger": "load",
            "action": "show-snackbar",
            "message": "Category created.",
            "tone": "success",
            "once": "true",
        },
        {
            "trigger": "load",
            "action": "dispatch-event",
            "event-name": "categories-changed",
            "once": "true",
        },
        {"trigger": "load", "action": "back"},
    ]
    category = Category.objects.get(user=user)

    edit = client.post(
        reverse("todo:category-edit", args=(category.pk,)),
        {"name": "Focus", "color": "green", "csrfmiddlewaretoken": token},
    )
    edit_root = assert_hxml(edit)
    assert edit_root.attrib["id"] == "category-transition"
    assert_snackbar(edit_root, "Category updated.")
    category.refresh_from_db()
    assert category.name == "Focus"

    client.force_login(other_user)
    assert_hxml(
        client.get(reverse("todo:category-edit", args=(category.pk,))), status=404
    )
    assert_hxml(
        client.post(
            reverse("todo:category-delete", args=(category.pk,)),
            {"csrfmiddlewaretoken": token},
        ),
        status=404,
    )


def test_filters_reject_invalid_values_and_hide_foreign_categories(user, other_user):
    client = Client()
    client.force_login(user)
    task_screen = assert_hxml(client.get(reverse("todo:tasks")))
    filter_actions = task_screen.findall(".//hv:view[@style='chip']", NS)
    assert filter_actions
    assert all(item.attrib["action"] == "reload" for item in filter_actions)
    assert_hxml(client.get(reverse("todo:tasks"), {"status": "unknown"}), status=400)
    foreign = Category.objects.create(
        user=other_user, name="Secret", color=Category.Color.PINK
    )
    assert_hxml(client.get(reverse("todo:tasks"), {"category": foreign.pk}), status=404)


def test_primary_screens_share_server_driven_navigation(user):
    client = Client()
    client.force_login(user)

    expected_active = {
        reverse("todo:dashboard"): "nav-dashboard",
        reverse("todo:tasks"): "nav-tasks",
        reverse("todo:categories"): "nav-categories",
    }
    for route, active_id in expected_active.items():
        root = assert_hxml(client.get(route))
        content = root.find(".//hv:view[@id='screen-content']", NS)
        bottom = root.find(".//hv:view[@id='bottom-navigation']", NS)
        drawer_host = root.find(".//hv:view[@id='side-menu-host']", NS)

        assert content is not None
        if route == reverse("todo:dashboard"):
            assert content.attrib["scroll"] == "true"
        else:
            assert "scroll" not in content.attrib
            assert root.find(".//hv:list", NS) is not None
        assert bottom is not None
        # The side menu now opens from the dashboard hero avatar only, so only the
        # dashboard still hosts it. tests/test_settings.py owns that trigger.
        if route == reverse("todo:dashboard"):
            assert drawer_host is not None
            assert len(drawer_host) == 0

        destinations = {
            item.attrib["id"]: (item.attrib["href"], item.attrib["action"])
            for item in bottom.findall("./hv:view", NS)
            if item.attrib["id"].startswith("nav-")
        }
        assert destinations == {
            # A fragment href, not a url: getRouteId returns the fragment name
            # (services/navigator/helpers.ts:211-218) so this dispatches
            # navigate('root-route'), which StackRouter truncates the stack back to.
            # `/hv/dashboard/` would collapse to the dynamic name `card`, never match
            # the declared root route, and push a second dashboard behind Home.
            "nav-dashboard": ("#root-route", "navigate"),
            "nav-tasks": ("/hv/tasks/", "navigate"),
            "nav-add-task": ("/hv/tasks/new/", "navigate"),
            "nav-categories": ("/hv/categories/", "navigate"),
            "nav-settings": ("/hv/settings/", "navigate"),
        }
        active = root.find(f".//hv:view[@id='{active_id}']", NS)
        assert active is not None
        assert "nav-active" in active.attrib["style"]
        assert active.attrib["href-style"] == "nav-hit-area"
        active_icon = active.find("./hv:image", NS)
        active_label = active.find("./hv:text", NS)
        assert active_icon is not None
        assert "nav-icon-active" in active_icon.attrib["style"].split()
        assert active_label is not None
        assert "nav-label-active" in active_label.attrib["style"]

        nav_style = root.find(".//hv:style[@id='nav-item']", NS)
        active_style = root.find(".//hv:style[@id='nav-active']", NS)
        add_style = root.find(".//hv:style[@id='nav-add']", NS)
        assert nav_style is not None
        assert nav_style.attrib["height"] == "52"
        assert nav_style.attrib["width"] == "64"
        assert active_style is not None
        assert "backgroundColor" not in active_style.attrib
        assert add_style is not None
        assert add_style.attrib["height"] == "48"
        assert "marginTop" not in add_style.attrib


def test_side_menu_is_loaded_and_closed_through_hxml_requests(user):
    client = Client()
    client.force_login(user)

    opened = assert_hxml(client.get(reverse("todo:menu"), {"active": "tasks"}))
    assert opened.tag == f"{{{NS['app']}}}side-menu"
    assert opened.attrib == {
        "id": "side-menu-host",
        "style": "side-menu",
        "close-href": "/hv/menu/close/",
        "animation-duration": "220",
        # A percentage of the window, not points: supportsTablet is false and the
        # orientation is locked portrait (app.config.ts:61,85), so the only variable
        # is phone width, and the client's 286pt default is 89% of a 320pt screen but
        # only 67% of a 430pt one. parsePanelWidth reads this
        # (AnimatedSideMenu.tsx:30-35) and keeps 286 only when it is missing.
        "panel-width": "80",
    }
    logout_action = opened.find(".//hv:view[@id='side-menu-logout']", NS)
    active_link = opened.find(".//hv:view[@href='/hv/tasks/']", NS)
    assert logout_action is not None
    assert logout_action.attrib["action"] == "replace"
    assert logout_action.attrib["target"] == "logout-panel"
    assert active_link is not None
    assert "side-menu-link-active" in active_link.attrib["style"]

    # Every destination carries its own glyph, and only the row you are standing on
    # draws the active file. The icons are DECORATIVE: no alt, so Image leaves
    # `accessible` unset on iOS and sets no contentDescription on Android
    # (Image.ios.js:171,184, Image.android.js:262-263), and no id, which on Android
    # would overwrite any label with the slug (services/index.ts:84,161). The row's
    # own <text> is therefore the single announcement.
    rows = [
        view
        for view in opened.iter(f"{{{NS['hv']}}}view")
        if "side-menu-link" in (view.attrib.get("style") or "").split()
    ]
    assert len(rows) == 5
    for row in rows:
        images = row.findall("./hv:image", NS)
        assert len(images) == 1, row.attrib["href"]
        assert len(row.findall("./hv:text", NS)) == 1, row.attrib["href"]
        assert not {"alt", "id"} & set(images[0].attrib), row.attrib["href"]
        active = "side-menu-link-active" in row.attrib["style"].split()
        assert (
            "side-menu-icon-active" in images[0].attrib["style"].split()
        ) is active, row.attrib["href"]

    header = opened.find(".//hv:view[@style='side-menu-header']", NS)
    assert header is not None
    assert header.find(".//hv:text[@style='side-menu-name']", NS) is not None
    assert header.find(".//hv:text[@style='side-menu-email']", NS) is not None

    sign_out = opened.find(".//hv:view[@id='side-menu-logout']", NS)
    sign_out_icon = sign_out.find("./hv:image", NS)
    assert sign_out_icon is not None
    assert sign_out_icon.attrib["source"].endswith("/logout.png")
    # The footer chrome lives OUTSIDE the replace target, because
    # fragments/logout_transition.xml answers with a bare unstyled <view
    # id="logout-panel"> and would otherwise drop the divider mid-sign-out.
    panel = opened.find(".//hv:view[@id='logout-panel']", NS)
    assert "style" not in panel.attrib
    assert opened.find(".//hv:view[@style='side-menu-footer']", NS) is not None
    about_link = opened.find(".//hv:view[@href='/hv/about/']", NS)
    assert about_link is not None
    assert about_link.find("./hv:text", NS).text == "About"
    dashboard = assert_hxml(client.get(reverse("todo:dashboard")))
    preferences_style = dashboard.find(".//hv:style[@id='side-menu-preferences']", NS)
    assert preferences_style is not None
    assert preferences_style.attrib["paddingBottom"] == "20"
    edge_opener = dashboard.find(".//app:edge-menu-opener", NS)
    assert edge_opener is not None
    assert edge_opener.attrib == {
        "id": "dashboard-edge-menu",
        "style": "edge-menu-opener",
        "href": "/hv/menu/?active=dashboard",
        "action": "replace",
        "target": "side-menu-host",
    }
    assert dashboard.find(".//hv:style[@id='edge-menu-opener']", NS) is not None

    closed = assert_hxml(client.get(reverse("todo:menu-close")))
    assert closed.attrib == {"id": "side-menu-host"}
    assert len(closed) == 0


def test_category_swipe_cards_use_fill_safe_name_ink(user):
    category = Category.objects.create(user=user, name="Pastel", color="mint")
    client = Client(headers={"x-app-version": "1.2.0"})
    client.force_login(user)
    client.cookies[THEME_COOKIE] = "dark"

    root = assert_hxml(client.get(reverse("todo:categories")))
    row = root.find(f".//app:swipe-row[@id='category-swipe-{category.pk}']", NS)
    name = row.find("./hv:view/hv:text", NS)
    style = root.find(".//hv:style[@id='name-on-fill']", NS)

    assert name is not None
    assert name.attrib["style"] == "name-on-fill"
    assert style is not None
    assert style.attrib["color"] == "#161A35"


def test_about_is_an_authenticated_document_linked_only_from_the_side_menu(user):
    anonymous = Client().get(reverse("todo:about"))
    assert_hxml(anonymous, status=401)

    client = Client(headers={"x-app-version": "1.2.0"})
    client.force_login(user)
    root = assert_hxml(client.get(reverse("todo:about")))
    screen = root.find("./hv:screen", NS)

    assert screen is not None
    assert screen.attrib["id"] == "about-screen"
    assert root.find(".//hv:text[@id='about-app-version']", NS).text == (
        "HyperTodo 1.2.0"
    )
    assert root.find(".//hv:text[@id='about-package-version']", NS).text == (
        "dj-hyperview 0.1.0b1"
    )
    technology_names = {
        item.text for item in root.findall(".//hv:text[@style='technology-name']", NS)
    }
    assert {"Django", "dj-hyperview", "Hyperview", "Expo"} <= technology_names
    assert root.find(".//hv:text[@id='about-copyright']", NS) is not None

    for route in (
        reverse("todo:dashboard"),
        reverse("todo:tasks"),
        reverse("todo:categories"),
        reverse("todo:settings"),
    ):
        page = assert_hxml(client.get(route))
        assert page.find(".//hv:view[@href='/hv/about/']", NS) is None


def test_task_cards_expose_swipe_actions_instead_of_tiny_links(user):
    task = Task.objects.create(user=user, title="Swipe me")
    client = Client()
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:tasks")))
    row = root.find(".//app:swipe-row", NS)

    assert row is not None
    assert row.attrib == {
        "id": f"task-swipe-{task.pk}",
        "style": "swipe-row",
        "edit-href": f"/hv/tasks/{task.pk}/edit/",
        "toggle-href": f"/hv/tasks/{task.pk}/toggle/",
        "delete-href": f"/hv/tasks/{task.pk}/delete/",
        "completed": "false",
    }
    assert root.find(".//hv:view[@style='actions']", NS) is None
    card = row.find("./hv:view", NS)
    title = row.find(".//hv:text[@style='task-title']", NS)
    assert card is not None
    assert card.attrib["style"] == "task"
    assert title is not None
    assert title.attrib["numberOfLines"] == "1"
    assert title.attrib["ellipsizeMode"] == "tail"
    assert (
        root.find(".//hv:form//hv:text-field[@name='csrfmiddlewaretoken']", NS)
        is not None
    )


def test_task_list_supports_refresh_and_infinite_scroll(user):
    for index in range(21):
        Task.objects.create(user=user, title=f"Task {index:02d}")
    client = Client()
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:tasks")))
    task_list = root.find(".//hv:list[@id='task-list']", NS)
    assert task_list is not None
    assert task_list.attrib["trigger"] == "refresh"
    assert len(task_list.findall("./hv:item", NS)) == 20
    refresh = task_list.find("./hv:behavior[@trigger='refresh']", NS)
    assert refresh is not None
    assert refresh.attrib["action"] == "replace"
    assert refresh.attrib["target"] == "task-list"
    load_more = task_list.find(".//hv:behavior[@trigger='visible']", NS)
    assert load_more is not None
    assert load_more.attrib["action"] == "append"
    assert load_more.attrib["target"] == "task-list"

    next_page = assert_hxml(
        client.get(reverse("todo:tasks"), {"page": 2, "fragment": "items"})
    )
    assert next_page.tag == f"{{{NS['hv']}}}items"
    assert len(next_page.findall("./hv:item", NS)) == 1

    refreshed = assert_hxml(client.get(reverse("todo:tasks"), {"fragment": "list"}))
    assert refreshed.tag == f"{{{NS['hv']}}}list"
    assert refreshed.attrib["id"] == "task-list"


def test_category_list_refreshes_after_mutation_and_paginates(user):
    for index in range(21):
        Category.objects.create(
            user=user, name=f"Category {index:02d}", color=Category.Color.MINT
        )
    client = Client()
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:categories")))
    category_list = root.find(".//hv:list[@id='category-list']", NS)
    assert category_list is not None
    assert category_list.attrib["trigger"] == "refresh"
    assert len(category_list.findall("./hv:item", NS)) == 20
    refresh = category_list.find("./hv:behavior[@trigger='refresh']", NS)
    # The listener lives on the screen, not on the <list>: HvList never sets
    # supportsHyperRef (components/hv-element/utils.tsx:16), so an on-event behavior
    # parked on it is never registered, and `replace target="category-list"` would
    # destroy it along with the list it is meant to refresh.
    changed = root.find(".//hv:behavior[@trigger='on-event']", NS)
    load_more = category_list.find(".//hv:behavior[@trigger='visible']", NS)
    assert refresh is not None
    assert refresh.attrib["action"] == "replace"
    assert refresh.attrib["target"] == "category-list"
    assert category_list.find("./hv:behavior[@trigger='on-event']", NS) is None
    assert changed is not None
    assert changed.attrib["event-name"] == "categories-changed"
    assert changed.attrib["action"] == "replace"
    assert load_more is not None
    assert load_more.attrib["action"] == "append"

    next_page = assert_hxml(
        client.get(reverse("todo:categories"), {"page": 2, "fragment": "items"})
    )
    assert next_page.tag == f"{{{NS['hv']}}}items"
    assert len(next_page.findall("./hv:item", NS)) == 1


def test_list_pagination_rejects_invalid_page_and_fragment(user):
    client = Client()
    client.force_login(user)

    for route in (reverse("todo:tasks"), reverse("todo:categories")):
        assert_hxml(client.get(route, {"page": "nope"}), status=400)
        assert_hxml(client.get(route, {"page": 2}), status=400)
        assert_hxml(client.get(route, {"fragment": "unknown"}), status=400)


def test_logout_is_post_only_csrf_protected_and_direct_hxml(user):
    client = csrf_client()
    client.force_login(user)
    token = token_from(client.get(reverse("todo:menu")))
    assert client.get(reverse("todo:logout")).status_code == 405
    response = client.post(reverse("todo:logout"), {"csrfmiddlewaretoken": token})
    # A screen url, not /hv/: see the login transition above. Signing out has to
    # replace this route's document, not nest a navigator inside it.
    assert_transition(response, "logout-panel", action="reload", href="/hv/login/")
    assert "_auth_user_id" not in client.session


def test_private_document_routes_send_an_expired_session_to_the_sign_in_screen(user):
    # These are reached with reload/navigate/new/push, so the 401 goes through
    # loadDocument and may — must — be a whole screen.
    task = Task.objects.create(user=user, title="Private")
    category = Category.objects.create(
        user=user, name="Private", color=Category.Color.PINK
    )
    routes = [
        reverse("todo:dashboard"),
        reverse("todo:tasks"),
        reverse("todo:task-new"),
        reverse("todo:task-edit", args=(task.pk,)),
        reverse("todo:categories"),
        reverse("todo:category-new"),
        reverse("todo:category-edit", args=(category.pk,)),
        reverse("todo:settings"),
    ]
    for route in routes:
        root = assert_hxml(Client().get(route), status=401)
        assert (
            root.find(".//hv:screen[@id='session-expired-screen']", NS) is not None
        ), f"{route} stopped routing an expired session to the sign-in screen"


def test_private_fragment_routes_answer_an_expired_session_with_a_recoverable_fragment(
    user,
):
    # These land inside a screen through loadElement, which rejects doc/screen/body,
    # so the 401 owes a bare fragment that can still get the user out of the hole.
    task = Task.objects.create(user=user, title="Private")
    category = Category.objects.create(
        user=user, name="Private", color=Category.Color.PINK
    )
    routes = [
        reverse("todo:menu"),
        reverse("todo:menu-close"),
        reverse("todo:task-toggle", args=(task.pk,)),
        reverse("todo:task-delete", args=(task.pk,)),
        reverse("todo:category-delete", args=(category.pk,)),
        f"{reverse('todo:tasks')}?status=all&fragment=list",
        f"{reverse('todo:categories')}?fragment=list",
    ]
    for route in routes:
        root = assert_hxml(Client().get(route), status=401)
        for forbidden in ("doc", "navigator", "screen", "body"):
            assert root.find(f".//hv:{forbidden}", NS) is None, f"{route}: {forbidden}"
        assert root.find("./hv:behavior[@action='reload']", NS) is not None, (
            f"{route} lost the only control that gets the user off a dead screen"
        )


def test_endpoints_reject_unsupported_methods_as_hxml(user):
    task = Task.objects.create(user=user, title="Private")
    category = Category.objects.create(
        user=user, name="Private", color=Category.Color.PINK
    )
    client = Client()
    client.force_login(user)
    calls = [
        ("put", reverse("todo:login")),
        ("post", reverse("todo:dashboard")),
        ("post", reverse("todo:menu")),
        ("post", reverse("todo:menu-close")),
        ("post", reverse("todo:tasks")),
        ("put", reverse("todo:task-new")),
        ("put", reverse("todo:task-edit", args=(task.pk,))),
        ("get", reverse("todo:task-toggle", args=(task.pk,))),
        ("get", reverse("todo:task-delete", args=(task.pk,))),
        ("post", reverse("todo:categories")),
        ("put", reverse("todo:category-new")),
        ("put", reverse("todo:settings")),
        ("put", reverse("todo:category-edit", args=(category.pk,))),
        ("get", reverse("todo:category-delete", args=(category.pk,))),
        ("post", reverse("todo:source-probe")),
    ]
    for method, route in calls:
        assert_hxml(getattr(client, method)(route), status=405)


def test_task_and_category_get_screens_and_invalid_edits(user):
    task = Task.objects.create(user=user, title="Private")
    category = Category.objects.create(
        user=user, name="Private", color=Category.Color.PINK
    )
    client = csrf_client()
    client.force_login(user)
    assert_hxml(client.get(reverse("todo:tasks"), {"category": category.pk}))
    assert_hxml(client.get(reverse("todo:categories")))

    task_form = client.get(reverse("todo:task-edit", args=(task.pk,)))
    token = token_from(task_form)
    assert_hxml(
        client.post(
            reverse("todo:task-edit", args=(task.pk,)),
            {"title": "", "csrfmiddlewaretoken": token},
        ),
        status=422,
    )
    category_form = client.get(reverse("todo:category-edit", args=(category.pk,)))
    token = token_from(category_form)
    invalid_category = client.post(
        reverse("todo:category-edit", args=(category.pk,)),
        {"name": "", "color": "pink", "csrfmiddlewaretoken": token},
    )
    invalid_root = assert_hxml(invalid_category, status=422)
    assert invalid_root.tag == f"{{{NS['hv']}}}view"
    assert invalid_root.attrib["id"] == "category-form-panel"
    assert_snackbar(
        invalid_root,
        "Please review the highlighted category details.",
        tone="error",
    )


def test_category_delete_succeeds_and_task_cross_user_is_hidden(user, other_user):
    task = Task.objects.create(user=user, title="Private")
    category = Category.objects.create(
        user=user, name="Private", color=Category.Color.PINK
    )
    client = csrf_client()
    client.force_login(user)
    token = token_from(client.get(reverse("todo:menu")))
    deleted = client.post(
        reverse("todo:category-delete", args=(category.pk,)),
        {"csrfmiddlewaretoken": token},
    )
    deleted_root = assert_transition(
        deleted,
        "category-list-transition",
        action="dispatch-event",
    )
    assert announced_event(deleted_root) == "categories-changed"
    assert_snackbar(deleted_root, "Category deleted.")
    client.force_login(other_user)
    assert_hxml(client.get(reverse("todo:task-edit", args=(task.pk,))), status=404)


def test_user_content_is_xml_escaped(user):
    Task.objects.create(user=user, title='Use <xml> & "quotes"')
    client = Client()
    client.force_login(user)
    response = client.get(reverse("todo:tasks"))
    root = assert_hxml(response)
    titles = [node.text for node in root.findall(".//hv:text", NS)]
    assert 'Use <xml> & "quotes"' in titles


def nav_behaviors(root):
    """Return every navigation behavior a transition fragment will run."""
    return [
        behavior
        for behavior in root.findall("./hv:behavior", NS)
        if behavior.attrib.get("action")
        in {"navigate", "new", "push", "reload", "close", "back"}
    ]


def test_a_successful_login_repoints_the_login_route_at_the_dashboard(user):
    # The POST is a `replace target="login-panel"`, so its response empties the login
    # screen. Navigating away from that emptied screen left it alive underneath the
    # dashboard, and the iOS swipe-back gesture on a `card` route walked straight back
    # onto the blank white sheet. Reloading swaps the login route's own document, and
    # the href names the dashboard SCREEN: /hv/ answers with the root navigator
    # document, which HvDoc cannot merge into a screen route and instead renders as a
    # nested stack inside it (hv-doc.tsx:120-131), one level deeper on every login.
    client = Client()

    response = client.post(
        reverse("todo:login"),
        {"username": "ada", "password": "correct-horse"},
        headers={"accept": f"application/xml, {FRAGMENT_MEDIA_TYPE}"},
    )

    root = assert_hxml(response)
    navigation = nav_behaviors(root)
    assert [behavior.attrib["action"] for behavior in navigation] == ["reload"]
    assert navigation[0].attrib["href"] == "/hv/dashboard/"

    # The route the reload repoints is still the only one the navigator declares, so
    # the dashboard replaces the login screen rather than stacking on top of it.
    routes = assert_hxml(client.get(reverse("todo:root"))).findall(
        "./hv:navigator/hv:nav-route", NS
    )
    assert [route.attrib["id"] for route in routes] == ["root-route"]
    assert routes[0].attrib["href"] == "/hv/dashboard/"


def test_saving_a_task_pops_the_emptied_form_and_announces_the_change(user):
    task = Task.objects.create(user=user, title="Water the plants")
    client = Client()
    client.force_login(user)

    response = client.post(
        reverse("todo:task-edit", args=[task.pk]),
        {"title": "Water the ferns"},
        headers={"accept": f"application/xml, {FRAGMENT_MEDIA_TYPE}"},
    )

    root = assert_hxml(response)
    assert [behavior.attrib["action"] for behavior in nav_behaviors(root)] == ["back"]
    announce = root.find("./hv:behavior[@action='dispatch-event']", NS)
    assert announce is not None
    assert announce.attrib["event-name"] == "tasks-changed"
    assert announce.attrib["trigger"] == "load"


def test_the_screens_behind_a_task_form_refresh_when_it_announces_a_change(user):
    # `close` pops the form without touching the screen underneath, and HvDoc only
    # refetches when its url changes (hv-doc.tsx:178-194). Without these listeners the
    # user lands back on a list that still shows the old title.
    client = Client()
    client.force_login(user)

    tasks = assert_hxml(client.get(reverse("todo:tasks")))
    listener = tasks.find(".//hv:behavior[@event-name='tasks-changed']", NS)
    assert listener is not None
    assert listener.attrib["trigger"] == "on-event"
    assert listener.attrib["action"] == "replace"
    assert listener.attrib["target"] == "task-list"
    assert tasks.find(".//hv:list/hv:behavior[@event-name='tasks-changed']", NS) is None

    dashboard = assert_hxml(client.get(reverse("todo:dashboard")))
    hook = dashboard.find(".//hv:behavior[@event-name='tasks-changed']", NS)
    assert hook is not None
    assert hook.attrib["trigger"] == "on-event"
    assert hook.attrib["action"] == "reload"


def test_a_swipe_toggle_refreshes_the_list_without_dropping_the_filter(user):
    # The swipe row posts the toggle action as a `replace` of the row itself
    # (mobile/src/components/SwipeRow.tsx:116-126), so the response is the only
    # thing that can refresh anything. A `reload href="/hv/tasks/"` here re-requested
    # the list with NO query string, and task_list defaults status to "all" with no
    # category, so the filter the user was looking at vanished under them and the
    # dashboard behind the stack was never refreshed at all.
    task = Task.objects.create(user=user, title="Renew the domain")
    client = Client()
    client.force_login(user)

    toggled = client.post(reverse("todo:task-toggle", args=(task.pk,)))

    root = assert_transition(toggled, "task-list-transition", action="dispatch-event")
    assert nav_behaviors(root) == [], (
        "an href-bearing navigation here re-requests the list with no filter on it"
    )
    assert announced_event(root) == "tasks-changed"

    # ...and the listener that hears it carries the filter the screen was showing.
    filtered = assert_hxml(client.get(f"{reverse('todo:tasks')}?status=overdue"))
    listener = filtered.find(".//hv:behavior[@event-name='tasks-changed']", NS)
    assert "status=overdue" in listener.attrib["href"]


def test_signing_in_or_out_makes_every_parked_screen_refetch(user):
    # `reload` dispatches nothing to the navigator (hyperview.tsx:70-133): it swaps
    # the CURRENT route's document and nothing else. Reached from session_expired
    # inside a pushed route, the previous session's screens stay mounted below with
    # their rendered documents, because HvDoc only refetches when its url changes
    # (hv-doc.tsx:178-194) -- one iOS swipe-back from another account's data.
    client = Client()
    client.force_login(user)

    for name in ("dashboard", "tasks", "categories", "settings"):
        root = assert_hxml(client.get(reverse(f"todo:{name}")))
        listener = root.find(".//hv:behavior[@event-name='session-changed']", NS)
        assert listener is not None, f"{name} keeps the old session's data on screen"
        assert listener.attrib["trigger"] == "on-event"
        assert listener.attrib["action"] == "reload"
        # href-less, so each screen re-requests its OWN url, filters included.
        assert "href" not in listener.attrib

    for label, response in (
        ("logout", client.post(reverse("todo:logout"))),
        (
            "login",
            Client().post(
                reverse("todo:login"),
                {"username": "ada", "password": "correct-horse"},
                headers={"accept": f"application/xml, {FRAGMENT_MEDIA_TYPE}"},
            ),
        ),
    ):
        announce = assert_hxml(response).find(
            "./hv:behavior[@action='dispatch-event']", NS
        )
        assert announce is not None, f"{label} leaves the parked screens stale"
        assert announce.attrib["event-name"] == "session-changed"
        assert announce.attrib["trigger"] == "load"


@pytest.mark.parametrize(
    ("email", "expected"),
    [("ada@example.com", "ada@example.com"), ("", "@menu-user")],
)
def test_the_side_menu_identity_line_always_renders(email, expected):
    # The line has to be unconditional or the header changes height between two
    # accounts. `@username` is the fallback rather than a bare username, which would
    # visually duplicate the name line whenever get_full_name is empty; it carries
    # exactly what "Signed in as {{ username }}" carried before.
    user = get_user_model().objects.create_user(username="menu-user", password="x")
    user.email = email
    user.save(update_fields=("email",))
    client = Client()
    client.force_login(user)

    opened = assert_hxml(client.get(reverse("todo:menu")))

    assert opened.find(".//hv:text[@style='side-menu-email']", NS).text == expected
    name = opened.find(".//hv:text[@style='side-menu-name']", NS)
    assert name.text == "menu-user"
    for line in (name, opened.find(".//hv:text[@style='side-menu-email']", NS)):
        assert line.attrib["numberOfLines"] == "1"
        assert line.attrib["ellipsizeMode"] == "tail"


# test_the_side_menu_glyphs_stay_visible_on_every_row_state is gone from HERE with
# its subject: side-menu-icon declares a tintColor, which RCTImageView applies after
# decoding, so the baked pixels this version read are dead data. Re-baking the
# glyphs at #FFFFFF failed it while changing nothing on screen, and a tint drifting
# to an invisible colour would have kept it green. The live version of the same
# contract, reading the TINT and in both palettes, is
# tests/test_theme_icons.py, test_the_side_menu_glyphs_stay_visible_on_every_row
# _state.


def test_the_side_menu_header_ink_clears_the_fill_it_is_drawn_on(user):
    # This used to assert a hardcoded "#FFFFFF" against the header fill and never
    # looked at side-menu-name, side-menu-email or side-menu-initials at all, so
    # every colour it claimed to protect could be changed with the suite green.
    # 16/700 and 13/400 are both normal text under WCAG, and 20/700 is only large
    # because it is 20px, so the whole block is held to 4.5:1.
    client = Client()
    client.force_login(user)
    screen = assert_hxml(client.get(reverse("todo:dashboard")))

    def declared(style_id, attribute):
        node = screen.find(f".//hv:styles/hv:style[@id='{style_id}']", NS)
        assert node is not None, f"missing style {style_id}"
        return node.attrib[attribute]

    for ink_id, fill_id in (
        ("side-menu-name", "side-menu-header"),
        ("side-menu-email", "side-menu-header"),
        ("side-menu-initials", "side-menu-avatar"),
    ):
        ink = declared(ink_id, "color")
        fill = declared(fill_id, "backgroundColor")
        assert int(declared(ink_id, "fontSize")) < 24
        assert contrast_ratio(ink, fill) >= 4.5, f"{ink_id}: {ink} on {fill}"


def test_every_side_menu_row_announces_itself_as_a_control(user):
    # A <view> cannot carry a server-set role: HvView builds its props from an
    # allowlist and never copies element attributes, and HyperRef's TouchableOpacity
    # is accessible={false}, so the inner <text> is the node a screen reader lands
    # on. Without a role it is announced as static text and neither VoiceOver nor
    # TalkBack offers to activate it. `button`, not `link`: Android only sets
    # isClickable for BUTTON (ReactAccessibilityDelegate.kt:654-665), and the
    # dashboard trigger already proves the value works on both platforms.
    client = Client()
    client.force_login(user)

    opened = assert_hxml(client.get(reverse("todo:menu")))

    labels = [
        node
        for node in opened.iter(f"{{{NS['hv']}}}text")
        if (node.attrib.get("style") or "")
        in ("side-menu-link-text", "side-menu-logout-text")
    ]
    assert len(labels) == 6, [label.text for label in labels]
    for label in labels:
        assert label.attrib.get("accessibilityRole") == "button", label.text
        # createProps spreads the id-derived test props LAST, so an id here would
        # overwrite the announcement with a slug on Android.
        assert "id" not in label.attrib, label.text


@pytest.mark.parametrize(
    ("announced", "supported"),
    [
        (None, False),  # no header at all
        ("", False),
        ("0.9.9", False),
        ("1.0.0", False),
        ("1.0.9", False),
        ("1.1.0", True),
        ("1.1", True),  # a two-part version is 1.1.0
        ("1.1.0-rc1", True),  # built from the 1.1.0 source, so it has the component
        ("2.0.3", True),
        ("nightly", False),
        ("x" * 64, False),  # longer than APP_VERSION_PATTERN allows, so "unknown"
    ],
)
def test_the_swipe_action_capability_is_gated_on_the_announced_client_version(
    rf, announced, supported
):
    # A backend deploy reaches EVERY installed binary at once -- there is no release
    # ordering that protects a user who never updates, and dj-hyperview can publish
    # templates straight from the database (tests/test_template_sources.py:31-36).
    # Only the CATEGORY list still asks: the pre-1.1.0 component was task-shaped and
    # drew a fixed Edit/Complete/Delete triad off three row attributes, so a category
    # served through it shows a Complete button with no toggle-href behind it, and
    # that component returned silently on a missing href -- a control that looks
    # alive and does nothing. The task row needs no gate at all, because it carries
    # both component generations' shapes at once (hyperview/partials/task_items.xml);
    # the replacement component is mobile/src/components/SwipeRow.tsx.
    headers = {} if announced is None else {"HTTP_X_APP_VERSION": announced}

    assert _supports_swipe_actions(rf.get("/hv/tasks/", **headers)) is supported


def test_the_shipped_client_version_can_actually_open_the_capability_gate():
    # The gate is only as good as the version bump. Leave app.config.ts behind and
    # _supports_swipe_actions answers False for every real client forever, so a
    # successful deploy changes nothing at all -- the silent no-op the version
    # header exists to prevent, one level up.
    config = (Path(__file__).resolve().parents[2] / "mobile/app.config.ts").read_text()
    declared = re.search(r'version:\s*"([0-9]+(?:\.[0-9]+)*)"', config)

    assert declared is not None, "no version literal in mobile/app.config.ts"
    shipped = tuple((list(map(int, declared.group(1).split("."))) + [0, 0, 0])[:3])
    assert shipped >= MIN_SWIPE_ACTIONS_VERSION, (
        f"the client announces {declared.group(1)}, below the "
        f"{'.'.join(map(str, MIN_SWIPE_ACTIONS_VERSION))} the gate requires"
    )


@pytest.mark.parametrize("completed", [False, True])
def test_a_task_row_declares_the_same_actions_the_component_used_to_hardcode(
    user, completed
):
    # The Complete/Reopen split moves to the server, which already knows
    # task.is_completed, so the client loses both ternaries. The `completed`
    # attribute stays for the pre-1.1.0 shape asserted below; 1.1.0 and later never
    # read it. No version header here on purpose: the row is now one document that
    # both component generations drive, so its shape cannot depend on one.
    task = Task.objects.create(user=user, title="Swipe me")
    if completed:
        task.completed_at = timezone.now()
        task.save(update_fields=("completed_at",))
    client = Client()
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:tasks")))
    row = root.find(".//app:swipe-row", NS)
    actions = row.findall("./app:swipe-action", NS)

    assert row.attrib["id"] == f"task-swipe-{task.pk}"
    assert row.attrib["style"] == "swipe-row"
    assert [action.attrib["label"] for action in actions] == [
        "Edit",
        "Reopen" if completed else "Complete",
        "Delete",
    ]
    assert [action.attrib["href"] for action in actions] == [
        f"/hv/tasks/{task.pk}/edit/",
        f"/hv/tasks/{task.pk}/toggle/",
        f"/hv/tasks/{task.pk}/delete/",
    ]
    assert [action.attrib["action"] for action in actions] == [
        "navigate",
        "replace",
        "replace",
    ]
    assert [action.attrib["verb"] for action in actions] == ["get", "post", "post"]
    assert actions[2].attrib["confirm-title"] == "Delete task?"
    assert actions[2].attrib["confirm-body"] == "This action cannot be undone."
    assert row.find("./hv:view[@style='task']", NS) is not None


def test_a_task_row_carries_both_action_shapes_whatever_version_arrives(user):
    # The row used to change shape on X-App-Version, and the unknown bucket served
    # the pre-1.1.0 attributes. A 1.1.0 binary behind a proxy that strips the header
    # therefore got a row it cannot drive: SwipeRow reads app:swipe-action CHILDREN
    # (mobile/src/components/SwipeRow.tsx:52-88), finds none, and renders content
    # with an empty action tray. Both shapes ride together now, because each
    # generation ignores the other's -- an unregistered element renders as nothing
    # (hyperview/src/services/render/index.tsx:71-85) and an attribute nobody reads
    # is inert -- so no header can produce a row with dead controls.
    task = Task.objects.create(user=user, title="Swipe me")
    rendered = {}
    for announced in (None, "1.0.0", "1.1.0", "nonsense"):
        client = Client(
            **({} if announced is None else {"headers": {"x-app-version": announced}})
        )
        client.force_login(user)
        listed = assert_hxml(client.get(reverse("todo:tasks")))
        row = listed.find(".//app:swipe-row", NS)
        rendered[announced] = ElementTree.tostring(row, encoding="unicode")

    assert len(set(rendered.values())) == 1, (
        "the task row still changes shape with the announced version"
    )
    row = ElementTree.fromstring(rendered[None])
    assert row.attrib["edit-href"] == f"/hv/tasks/{task.pk}/edit/"
    assert row.attrib["toggle-href"] == f"/hv/tasks/{task.pk}/toggle/"
    assert row.attrib["delete-href"] == f"/hv/tasks/{task.pk}/delete/"
    assert row.attrib["completed"] == "false"
    assert len(row.findall("./app:swipe-action", NS)) == 3


@pytest.mark.parametrize(
    ("route", "varies"),
    [
        # category_items.xml still picks its markup off the header, so a shared cache
        # that keys only on the url can hand one generation the other's body.
        ("todo:categories", True),
        # settings.xml prints the announced version into the document.
        ("todo:settings", True),
        # The task row carries both shapes, so its body is version-independent and
        # owes no cache split. Delete this row the day it branches again.
        ("todo:tasks", False),
    ],
)
def test_bodies_that_move_with_the_client_version_declare_it_in_vary(
    client, user, route, varies
):
    client.force_login(user)

    response = client.get(reverse(route), headers={"x-app-version": "1.1.0"})

    announced = {
        field.strip().lower() for field in response.headers.get("Vary", "").split(",")
    }
    assert ("x-app-version" in announced) is varies, response.headers.get("Vary")


# The native shell paints four surfaces the server can never reach: both safe-area
# insets, the splash overlay and the two full-screen failure states. Without a
# channel it hardcodes light, so a dark screen sits on a #F7F8FC strip. One
# response header is the whole channel; the client half is mobile/src/theme.ts.
@pytest.mark.parametrize(
    ("fixture", "expected"), [("light_user", "light"), ("dark_user", "dark")]
)
def test_every_response_names_the_palette_it_was_painted_with(
    client, request, fixture, expected
):
    client.force_login(request.getfixturevalue(fixture))

    response = client.get(reverse("todo:dashboard"))

    assert response.headers[THEME_HEADER] == expected


@pytest.mark.parametrize(
    ("cookie", "expected"),
    [
        # The signed-out screens have no profile to read, so the cookie the
        # preference write leaves behind is their only channel -- the same
        # fallback todo/context_processors.py already implements for the body.
        ("dark", "dark"),
        ("chartreuse", "light"),
        ("", "light"),
    ],
)
def test_the_signed_out_screens_answer_from_the_cookie_like_their_bodies_do(
    cookie, expected
):
    client = Client()
    if cookie:
        client.cookies[THEME_COOKIE] = cookie

    response = client.get(reverse("todo:login"))

    assert response.headers[THEME_HEADER] == expected


def test_the_header_can_never_disagree_with_the_stylesheet_it_shipped_with(
    client, dark_user
):
    # Django renders a TemplateResponse inside BaseHandler._get_response, i.e.
    # before the response unwinds back through the middleware chain. Asserting the
    # header against the body PINS that ordering instead of assuming it: a header
    # resolved from a different profile read than the context processor used would
    # hand the shell a palette the document does not actually use.
    client.force_login(dark_user)

    response = client.get(reverse("todo:dashboard"))

    painted = theme_tokens.THEMES[response.headers[THEME_HEADER]]
    root = ElementTree.fromstring(response.content)
    navigation = style_by_id(root, "bottom-navigation-style")
    assert navigation.attrib["backgroundColor"] == painted["canvas"]
