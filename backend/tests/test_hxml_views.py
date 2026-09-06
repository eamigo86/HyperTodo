"""HTTP contract tests for server-driven Hyperview screens."""

from xml.etree import ElementTree

import pytest
from django.test import Client
from django.urls import reverse

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


def test_task_create_edit_toggle_delete_flow_uses_hxml_and_csrf(user):
    client = csrf_client()
    client.force_login(user)
    form_response = client.get(reverse("todo:task-new"))
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
    assert_hxml(created, status=201)
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
    assert_hxml(updated)
    task.refresh_from_db()
    assert task.title == "Ship XML"

    toggled = client.post(
        reverse("todo:task-toggle", args=(task.pk,)),
        {"csrfmiddlewaretoken": edit_token},
    )
    assert_hxml(toggled)
    task.refresh_from_db()
    assert task.completed_at is not None

    deleted = client.post(
        reverse("todo:task-delete", args=(task.pk,)),
        {"csrfmiddlewaretoken": edit_token},
    )
    assert_hxml(deleted)
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
    assert root.find(".//hv:text[@id='form-errors']", NS) is not None


def test_category_crud_and_cross_user_resources_are_hidden(user, other_user):
    client = csrf_client()
    client.force_login(user)
    token = token_from(client.get(reverse("todo:category-new")))
    created = client.post(
        reverse("todo:category-new"),
        {"name": "Work", "color": "lavender", "csrfmiddlewaretoken": token},
    )
    assert_hxml(created, status=201)
    category = Category.objects.get(user=user)

    edit = client.post(
        reverse("todo:category-edit", args=(category.pk,)),
        {"name": "Focus", "color": "green", "csrfmiddlewaretoken": token},
    )
    assert_hxml(edit)
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
    assert_hxml(client.get(reverse("todo:tasks"), {"status": "unknown"}), status=400)
    foreign = Category.objects.create(
        user=other_user, name="Secret", color=Category.Color.PINK
    )
    assert_hxml(client.get(reverse("todo:tasks"), {"category": foreign.pk}), status=404)


def test_logout_is_post_only_csrf_protected_and_direct_hxml(user):
    client = csrf_client()
    client.force_login(user)
    token = token_from(client.get(reverse("todo:dashboard")))
    assert client.get(reverse("todo:logout")).status_code == 405
    response = client.post(reverse("todo:logout"), {"csrfmiddlewaretoken": token})
    root = assert_hxml(response)
    assert root.find(".//hv:screen[@id='login-screen']", NS) is not None


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
    assert_hxml(
        client.post(
            reverse("todo:category-edit", args=(category.pk,)),
            {"name": "", "color": "pink", "csrfmiddlewaretoken": token},
        ),
        status=422,
    )


def test_category_delete_succeeds_and_task_cross_user_is_hidden(user, other_user):
    task = Task.objects.create(user=user, title="Private")
    category = Category.objects.create(
        user=user, name="Private", color=Category.Color.PINK
    )
    client = csrf_client()
    client.force_login(user)
    token = token_from(client.get(reverse("todo:dashboard")))
    assert_hxml(
        client.post(
            reverse("todo:category-delete", args=(category.pk,)),
            {"csrfmiddlewaretoken": token},
        )
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
