"""HTTP contract tests for server-driven Hyperview screens."""

from datetime import timedelta
from xml.etree import ElementTree

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from todo.models import Category, Task

pytestmark = pytest.mark.django_db
MEDIA_TYPE = "application/vnd.hyperview+xml"
NS = {
    "hv": "https://hyperview.org/hyperview",
    "app": "https://hypertodo.app/components",
}


def assert_hxml(response, *, status=200):
    """Assert a response is parseable UTF-8 Hyperview XML."""
    assert response.status_code == status
    assert response.headers["Content-Type"] == f"{MEDIA_TYPE}; charset=utf-8"
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
    dashboard_route = dashboard_root.find(
        ".//hv:nav-route[@id='dashboard-route']", NS
    )
    assert dashboard_route is not None
    assert dashboard_route.attrib["href"] == "/hv/dashboard/"
    assert dashboard_route.attrib["selected"] == "true"


def test_login_screen_uses_secure_credentials_and_fragment_submission():
    response = Client().get(reverse("todo:login"))
    root = assert_hxml(response)

    screen_style = root.find(".//hv:style[@id='screen']", NS)
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
    assert "✓" not in visible_text


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
        assert "".join(back.itertext()).strip() == "<"


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



def test_dashboard_counters_share_one_ordered_row(user):
    client = Client()
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:dashboard")))
    row = root.find(".//hv:view[@id='dashboard-counters']", NS)

    assert row is not None
    assert [child.attrib["id"] for child in row.findall("./hv:view", NS)] == [
        "dashboard-all",
        "dashboard-today",
        "dashboard-scheduled",
        "dashboard-overdue",
    ]
    row_style = root.find(".//hv:style[@id='counter-row']", NS)
    tile_style = root.find(".//hv:style[@id='tile']", NS)
    hit_area_style = root.find(".//hv:style[@id='tile-hit-area']", NS)
    assert row_style is not None
    assert row_style.attrib["flexDirection"] == "row"
    assert row_style.attrib["gap"] == "7"
    assert tile_style is not None
    assert tile_style.attrib["width"] == "100%"
    assert hit_area_style is not None
    assert hit_area_style.attrib == {
        "id": "tile-hit-area",
        "flexBasis": "0",
        "flexGrow": "1",
        "flexShrink": "1",
    }
    assert all(
        child.attrib["href-style"] == "tile-hit-area"
        for child in row.findall("./hv:view", NS)
    )
    labels = row.findall("./hv:view/hv:text[@style='tile-label']", NS)
    assert len(labels) == 4
    assert all(label.attrib["adjustsFontSizeToFit"] == "true" for label in labels)
    assert all(label.attrib["numberOfLines"] == "1" for label in labels)
    label_style = root.find(".//hv:style[@id='tile-label']", NS)
    assert label_style is not None
    assert label_style.attrib["fontSize"] == "14"


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
        assert header_style.attrib["height"] == "58"
        assert header_style.attrib["justifyContent"] == "center"
        assert back is not None
        assert back.attrib["action"] == "back"
        assert "".join(back.itertext()).strip() == "<"
        back_style = root.find(".//hv:style[@id='back-button']", NS)
        title_slot = root.find(".//hv:view[@style='screen-header-title-slot']", NS)
        spacer = root.find(".//hv:view[@style='screen-header-spacer']", NS)
        spacer_style = root.find(".//hv:style[@id='screen-header-spacer']", NS)
        assert back_style is not None
        assert back_style.attrib["width"] == "52"
        assert "position" not in back_style.attrib
        assert title_slot is not None
        assert spacer is not None
        assert spacer_style is not None
        assert spacer_style.attrib["width"] == back_style.attrib["width"]
        assert heading is not None
        assert heading.text == title

def test_task_screen_scrolls_and_makes_dashboard_filter_visible(user, monkeypatch):
    now = timezone.localtime().replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    monkeypatch.setattr("todo.selectors.timezone.now", lambda: now)
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
        root = assert_hxml(
            client.get(reverse("todo:tasks"), {"status": status_filter})
        )
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
    assert "".join(back.itertext()).strip() == "<"
    assert color is not None
    labels = [node.text for node in color.findall("./hv:option/hv:text", NS)]
    assert labels == ["Lavender", "Yellow", "Mint", "Pink", "Green"]
    assert submit is not None
    assert submit.attrib["action"] == "replace"
    assert submit.attrib["target"] == "category-form-panel"



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
    assert (
        root.find(
            ".//hv:form//hv:text-field[@name='csrfmiddlewaretoken']", NS
        )
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

    refreshed = assert_hxml(
        client.get(reverse("todo:tasks"), {"fragment": "list"})
    )
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
