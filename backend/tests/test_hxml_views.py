"""HTTP contract tests for server-driven Hyperview screens."""

from datetime import timedelta
from xml.etree import ElementTree

import pytest
from django.contrib.auth import get_user_model
from django.template.defaultfilters import date as date_filter
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from todo.models import Category, Task

pytestmark = pytest.mark.django_db
MEDIA_TYPE = "application/vnd.hyperview+xml"
FRAGMENT_MEDIA_TYPE = "application/vnd.hyperview_fragment+xml"
NS = {
    "hv": "https://hyperview.org/hyperview",
    "app": "https://hypertodo.app/components",
}


def assert_hxml(response, *, status=200, media_type=MEDIA_TYPE):
    """Assert a response is parseable UTF-8 Hyperview XML."""
    assert response.status_code == status
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


def assert_transition(response, transition_id, *, action, href, status=200):
    """Assert an HXML fragment contains the expected load transition."""
    root = assert_hxml(response, status=status)
    assert root.tag == f"{{{NS['hv']}}}view"
    assert root.attrib["id"] == transition_id
    behavior = root.find(f"./hv:behavior[@action='{action}']", NS)
    assert behavior is not None
    assert behavior.attrib["trigger"] == "load"
    assert behavior.attrib["href"] == href
    return root


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
    client = Client()
    login_response = client.get(reverse("todo:root"))
    login_root = assert_hxml(login_response)
    navigator = login_root.find(".//hv:navigator[@id='root-navigator']", NS)
    assert navigator is not None
    assert navigator.attrib["type"] == "stack"
    login_route = navigator.find("./hv:nav-route[@id='login-route']", NS)
    assert login_route is not None
    assert login_route.attrib["href"] == "/hv/login/"
    assert login_route.attrib["selected"] == "true"

    client.force_login(user)
    dashboard_response = client.get(reverse("todo:root"))
    dashboard_root = assert_hxml(dashboard_response)
    dashboard_route = dashboard_root.find(".//hv:nav-route[@id='dashboard-route']", NS)
    assert dashboard_route is not None
    assert dashboard_route.attrib["href"] == "/hv/dashboard/"
    assert dashboard_route.attrib["selected"] == "true"


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
    error = rejected_root.find(".//hv:text[@id='form-errors']", NS)
    assert error is not None
    assert error.attrib["style"] == "error-text"
    assert error.text == "Invalid username or password. Please try again."
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
    transition = root.find("./hv:behavior", NS)
    assert transition is not None
    assert transition.attrib == {
        "trigger": "load",
        "href": "/hv/dashboard/",
        "action": "navigate",
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
    category = root.find(".//hv:select-single[@name='category']", NS)

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
    labels = [node.text for node in category.findall("./hv:option/hv:text", NS)]
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
    assert hero.find(".//hv:image", NS) is None
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
        style = root.find(".//hv:style[@id='bottom-navigation']", NS)
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
        header_style = root.find(".//hv:style[@id='screen-header']", NS)
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
        assert task_list.attrib["style"] == "task-list"
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

    defined = {style.attrib["id"] for style in screen.findall(".//hv:style", NS)}
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
    created_root = assert_transition(
        created,
        "task-transition",
        action="navigate",
        href="/hv/tasks/",
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
    updated_root = assert_transition(
        updated, "task-transition", action="navigate", href="/hv/tasks/"
    )
    assert_snackbar(updated_root, "Task updated.")
    task.refresh_from_db()
    assert task.title == "Ship XML"

    toggled = client.post(
        reverse("todo:task-toggle", args=(task.pk,)),
        {"csrfmiddlewaretoken": edit_token},
    )
    toggled_root = assert_transition(
        toggled, "task-list-transition", action="reload", href="/hv/tasks/"
    )
    assert_snackbar(toggled_root, "Task completed.")
    task.refresh_from_db()
    assert task.completed_at is not None

    deleted = client.post(
        reverse("todo:task-delete", args=(task.pk,)),
        {"csrfmiddlewaretoken": edit_token},
    )
    deleted_root = assert_transition(
        deleted, "task-list-transition", action="reload", href="/hv/tasks/"
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
    summary = root.find(".//hv:text[@id='form-errors']", NS)
    title_error = root.find(".//hv:text[@id='title-error']", NS)
    due_time_error = root.find(".//hv:text[@id='due-time-error']", NS)
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
        {"trigger": "load", "action": "close", "delay": "350"},
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
        open_menu = root.find(".//hv:view[@id='open-side-menu']", NS)

        assert content is not None
        if route == reverse("todo:dashboard"):
            assert content.attrib["scroll"] == "true"
        else:
            assert "scroll" not in content.attrib
            assert root.find(".//hv:list", NS) is not None
        assert bottom is not None
        assert drawer_host is not None
        assert len(drawer_host) == 0
        assert open_menu is not None
        active_nav = {
            "nav-dashboard": "dashboard",
            "nav-tasks": "tasks",
            "nav-categories": "categories",
        }[active_id]
        assert open_menu.attrib["href"] == f"/hv/menu/?active={active_nav}"
        assert open_menu.attrib["action"] == "replace"
        assert open_menu.attrib["target"] == "side-menu-host"

        destinations = {
            item.attrib["id"]: (item.attrib["href"], item.attrib["action"])
            for item in bottom.findall("./hv:view", NS)
            if item.attrib["id"].startswith("nav-")
        }
        assert destinations == {
            "nav-dashboard": ("/hv/dashboard/", "navigate"),
            "nav-tasks": ("/hv/tasks/", "navigate"),
            "nav-add-task": ("/hv/tasks/new/", "new"),
            "nav-categories": ("/hv/categories/", "navigate"),
        }
        active = root.find(f".//hv:view[@id='{active_id}']", NS)
        assert active is not None
        assert "nav-active" in active.attrib["style"]
        assert active.attrib["href-style"] == "nav-hit-area"
        active_icon = active.find("./hv:image", NS)
        active_label = active.find("./hv:text", NS)
        assert active_icon is not None
        assert active_icon.attrib["source"].endswith("-active.png")
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
    }
    logout_action = opened.find(".//hv:view[@id='side-menu-logout']", NS)
    active_link = opened.find(".//hv:view[@href='/hv/tasks/']", NS)
    assert logout_action is not None
    assert logout_action.attrib["action"] == "replace"
    assert logout_action.attrib["target"] == "logout-panel"
    assert active_link is not None
    assert "side-menu-link-active" in active_link.attrib["style"]

    closed = assert_hxml(client.get(reverse("todo:menu-close")))
    assert closed.attrib == {"id": "side-menu-host"}
    assert len(closed) == 0


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
    changed = category_list.find("./hv:behavior[@trigger='on-event']", NS)
    load_more = category_list.find(".//hv:behavior[@trigger='visible']", NS)
    assert refresh is not None
    assert refresh.attrib["action"] == "replace"
    assert refresh.attrib["target"] == "category-list"
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
    assert_transition(response, "logout-panel", action="reload", href="/hv/")
    assert "_auth_user_id" not in client.session


def test_all_private_endpoints_return_direct_session_expired_hxml(user):
    task = Task.objects.create(user=user, title="Private")
    category = Category.objects.create(
        user=user, name="Private", color=Category.Color.PINK
    )
    routes = [
        reverse("todo:dashboard"),
        reverse("todo:menu"),
        reverse("todo:menu-close"),
        reverse("todo:tasks"),
        reverse("todo:task-new"),
        reverse("todo:task-edit", args=(task.pk,)),
        reverse("todo:task-toggle", args=(task.pk,)),
        reverse("todo:task-delete", args=(task.pk,)),
        reverse("todo:categories"),
        reverse("todo:category-new"),
        reverse("todo:category-edit", args=(category.pk,)),
        reverse("todo:category-delete", args=(category.pk,)),
    ]
    for route in routes:
        assert_hxml(Client().get(route), status=401)


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
        action="reload",
        href="/hv/categories/",
    )
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
