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
NS = {"hv": "https://hyperview.org/hyperview"}


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
    behavior = root.find("./hv:behavior", NS)
    assert behavior is not None
    assert behavior.attrib == {"trigger": "load", "href": href, "action": action}
    return root


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


def test_task_screen_scrolls_and_makes_dashboard_filter_visible(user):
    now = timezone.now()
    Task.objects.create(user=user, title="Due today", due_at=now + timedelta(hours=1))
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
        selected = root.find(f".//hv:view[@id='filter-{status_filter}']", NS)
        summary = root.find(".//hv:text[@id='filter-summary']", NS)
        visible_text = "".join(root.itertext())

        assert content is not None
        assert content.attrib["scroll"] == "true"
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


def test_back_control_uses_quiet_bordered_surface(user):
    client = Client()
    client.force_login(user)

    for route in (reverse("todo:tasks"), reverse("todo:category-new")):
        root = assert_hxml(client.get(route))
        style = root.find(".//hv:style[@id='back-button']", NS)
        assert style is not None
        assert style.attrib["backgroundColor"] == "#FFFFFF"
        assert style.attrib["borderColor"] == "#E1E6F0"
        assert style.attrib["borderWidth"] == "1"
        assert style.attrib["height"] == "40"
        assert style.attrib["width"] == "40"


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
    assert_transition(
        created,
        "task-transition",
        action="navigate",
        href="/hv/tasks/",
        status=201,
    )
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
    assert_transition(
        updated, "task-transition", action="navigate", href="/hv/tasks/"
    )
    task.refresh_from_db()
    assert task.title == "Ship XML"

    toggled = client.post(
        reverse("todo:task-toggle", args=(task.pk,)),
        {"csrfmiddlewaretoken": edit_token},
    )
    assert_transition(
        toggled, "task-list-transition", action="reload", href="/hv/tasks/"
    )
    task.refresh_from_db()
    assert task.completed_at is not None

    deleted = client.post(
        reverse("todo:task-delete", args=(task.pk,)),
        {"csrfmiddlewaretoken": edit_token},
    )
    assert_transition(
        deleted, "task-list-transition", action="reload", href="/hv/tasks/"
    )
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
    assert root.find(".//hv:text[@id='form-errors']", NS) is not None


def test_category_crud_and_cross_user_resources_are_hidden(user, other_user):
    client = csrf_client()
    client.force_login(user)
    token = token_from(client.get(reverse("todo:category-new")))
    created = client.post(
        reverse("todo:category-new"),
        {"name": "Work", "color": "lavender", "csrfmiddlewaretoken": token},
    )
    assert_transition(
        created,
        "category-transition",
        action="navigate",
        href="/hv/categories/",
        status=201,
    )
    category = Category.objects.get(user=user)

    edit = client.post(
        reverse("todo:category-edit", args=(category.pk,)),
        {"name": "Focus", "color": "green", "csrfmiddlewaretoken": token},
    )
    assert_transition(
        edit, "category-transition", action="navigate", href="/hv/categories/"
    )
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
        drawer = root.find(".//hv:view[@id='side-menu']", NS)
        open_menu = root.find(".//hv:view[@id='open-side-menu']", NS)
        close_menu = root.find(".//hv:view[@id='close-side-menu']", NS)

        assert content is not None
        assert content.attrib["scroll"] == "true"
        assert bottom is not None
        assert drawer is not None
        assert drawer.attrib["hide"] == "true"
        assert open_menu is not None
        assert open_menu.attrib["action"] == "show"
        assert open_menu.attrib["target"] == "side-menu"
        assert close_menu is not None
        assert close_menu.attrib["action"] == "hide"
        assert close_menu.attrib["target"] == "side-menu"

        destinations = {
            item.attrib["id"]: (item.attrib["href"], item.attrib["action"])
            for item in bottom.findall("./hv:view", NS)
            if "href" in item.attrib
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

        logout_action = root.find(".//hv:view[@id='side-menu-logout']", NS)
        assert logout_action is not None
        assert logout_action.attrib["action"] == "replace"
        assert logout_action.attrib["target"] == "logout-panel"


def test_logout_is_post_only_csrf_protected_and_direct_hxml(user):
    client = csrf_client()
    client.force_login(user)
    token = token_from(client.get(reverse("todo:dashboard")))
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


def test_category_delete_succeeds_and_task_cross_user_is_hidden(user, other_user):
    task = Task.objects.create(user=user, title="Private")
    category = Category.objects.create(
        user=user, name="Private", color=Category.Color.PINK
    )
    client = csrf_client()
    client.force_login(user)
    token = token_from(client.get(reverse("todo:dashboard")))
    deleted = client.post(
        reverse("todo:category-delete", args=(category.pk,)),
        {"csrfmiddlewaretoken": token},
    )
    assert_transition(
        deleted,
        "category-list-transition",
        action="reload",
        href="/hv/categories/",
    )
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
