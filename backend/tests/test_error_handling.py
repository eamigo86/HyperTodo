"""Failures a form cannot foresee, and how the Hyperview client is told about them.

A 5xx or an HTML page is a response the client cannot parse (HvDoc throws on both),
so each of these has to come back as a refusal in the shape the action can load.
"""

from types import SimpleNamespace

import pytest
from django.http import HttpResponse
from django.test import Client, RequestFactory
from django.urls import get_resolver
from django.utils import translation

from tests.test_forms_ui import NS, assert_hxml, csrf_client, token_from
from tests.test_fragment_contract import assert_bare_fragment, assert_document
from todo import views
from todo.forms import TaskForm
from todo.models import Category, Task
from todo.services import create_task
from todo.session_contract import (
    CLIENT_CONTRACT,
    CLIENT_CONTRACT_HEADER,
    EXPECTED_SESSION_HEADER,
    SESSION_BINDING_HEADER,
)

pytestmark = pytest.mark.django_db
FRAGMENT_ACCEPT = "application/xml, application/vnd.hyperview_fragment+xml"
NOT_FOUND = "The requested item was not found."
UNAVAILABLE = "We could not complete that request. Try again in a moment."


def field_error(root):
    """Return the text of the first field error on a refused form panel."""
    node = root.find(".//hv:text[@style='field-error']", NS)
    assert node is not None
    return node.text


# --- a parallel write gets in between a form's check and the write ---------------


def race(monkeypatch, service, before):
    """Run a callback the instant a view calls a service, like a parallel request."""
    real = getattr(views, service)

    def wrapper(**kwargs):
        before(**kwargs)
        return real(**kwargs)

    monkeypatch.setattr(views, service, wrapper)


def without_validation(monkeypatch, model):
    """Skip full_clean so the database constraint is the one that answers."""
    monkeypatch.setattr(model, "full_clean", lambda self, *args, **kwargs: None)


@pytest.mark.parametrize("failure", ["validation", "integrity"])
def test_a_duplicate_category_created_in_parallel_is_a_422_and_not_a_500(
    user, monkeypatch, failure
):
    # clean_name looks the name up and the service writes it later, so a double tap
    # or two devices can both pass the lookup. The service then raises
    # ValidationError (full_clean sees the row) or IntegrityError (the constraint does).
    client = csrf_client()
    client.force_login(user)
    token = token_from(client.get("/hv/categories/new/"))
    race(
        monkeypatch,
        "create_category",
        lambda *, user, name, color: Category.objects.create(
            user=user, name=name, color=Category.Color.MINT
        ),
    )
    if failure == "integrity":
        without_validation(monkeypatch, Category)

    response = client.post(
        "/hv/categories/new/",
        {"name": "Work", "color": "pink", "csrfmiddlewaretoken": token},
    )

    root = assert_hxml(response, status=422)
    assert field_error(root) == "A category with this name already exists."
    assert Category.objects.filter(user=user).count() == 1


@pytest.mark.parametrize("failure", ["validation", "integrity"])
def test_a_rename_that_collides_in_parallel_is_a_422_and_not_a_500(
    user, monkeypatch, failure
):
    home = Category.objects.create(user=user, name="Home", color=Category.Color.MINT)
    client = csrf_client()
    client.force_login(user)
    token = token_from(client.get(f"/hv/categories/{home.pk}/edit/"))
    race(
        monkeypatch,
        "update_category",
        lambda *, user, category_id, name, color: Category.objects.create(
            user=user, name=name, color=Category.Color.PINK
        ),
    )
    if failure == "integrity":
        without_validation(monkeypatch, Category)

    response = client.post(
        f"/hv/categories/{home.pk}/edit/",
        {"name": "Work", "color": "mint", "csrfmiddlewaretoken": token},
    )

    root = assert_hxml(response, status=422)
    assert field_error(root) == "A category with this name already exists."
    home.refresh_from_db()
    assert home.name == "Home"


@pytest.mark.parametrize("route", ["new", "edit"])
def test_a_category_deleted_in_parallel_is_a_422_on_the_task_form(
    user, monkeypatch, route
):
    work = Category.objects.create(user=user, name="Work", color=Category.Color.MINT)
    task = Task.objects.create(user=user, title="Old")
    client = csrf_client()
    client.force_login(user)
    url = "/hv/tasks/new/" if route == "new" else f"/hv/tasks/{task.pk}/edit/"
    token = token_from(client.get(url))
    race(
        monkeypatch,
        "create_task" if route == "new" else "update_task",
        lambda **_: Category.objects.filter(pk=work.pk).delete(),
    )

    response = client.post(
        url,
        {"title": "Ship", "category": str(work.pk), "csrfmiddlewaretoken": token},
    )

    root = assert_hxml(response, status=422)
    assert field_error(root).startswith("Select a valid choice.")
    assert not Task.objects.filter(title="Ship").exists()


# --- dates the database cannot hold ---------------------------------------------


@pytest.mark.parametrize(
    "due_date", ["0001-01-01", "1999-12-31", "2101-01-01", "9999-12-31"]
)
def test_a_due_date_outside_the_supported_years_is_a_field_error(user, due_date):
    form = TaskForm(
        {"title": "Plan", "due_date": due_date, "due_time": "23:59"}, user=user
    )

    assert not form.is_valid()
    assert form.errors["due_date"] == ["Choose a due date between 2000 and 2100."]
    # The date WAS given, so it must not also be reported as missing under the time.
    assert "due_time" not in form.errors


def test_the_due_date_range_is_stated_in_the_users_language(user):
    form = TaskForm({"title": "Plan", "due_date": "9999-12-31"}, user=user)

    with translation.override("es"):
        assert form.errors["due_date"] == ["Elige una fecha límite entre 2000 y 2100."]


@pytest.mark.parametrize("due_time", ["23:59", ""], ids=["timed", "all-day"])
@pytest.mark.parametrize("due_date", ["2000-01-01", "2100-12-31"])
def test_the_first_and_last_supported_days_can_be_stored(user, due_date, due_time):
    form = TaskForm(
        {"title": "Plan", "due_date": due_date, "due_time": due_time}, user=user
    )

    assert form.is_valid(), form.errors
    task = create_task(
        user=user,
        title="Plan",
        notes="",
        category=None,
        due_at=form.cleaned_data["due_at"],
        due_all_day=form.cleaned_data["due_all_day"],
    )
    task.refresh_from_db()
    assert task.due_at == form.cleaned_data["due_at"]


def test_the_overflowing_date_from_the_audit_answers_422_and_not_500(user):
    # 9999-12-31 23:59 overflows when it is converted to UTC for the database, which
    # no handler turned into anything but a plain HTML 500.
    client = csrf_client()
    client.force_login(user)
    token = token_from(client.get("/hv/tasks/new/"))

    response = client.post(
        "/hv/tasks/new/",
        {
            "title": "Plan",
            "due_date": "9999-12-31",
            "due_time": "23:59",
            "csrfmiddlewaretoken": token,
        },
    )

    root = assert_hxml(response, status=422)
    assert field_error(root) == "Choose a due date between 2000 and 2100."
    assert not Task.objects.exists()


# --- errors outside any view -----------------------------------------------------


def test_the_error_handlers_are_the_hyperview_aware_ones():
    resolver = get_resolver()

    assert resolver.resolve_error_handler(404) is views.not_found
    assert resolver.resolve_error_handler(500) is views.server_error


def test_an_unknown_hyperview_route_gets_an_hxml_document():
    response = Client().get("/hv/nothing-here/")

    assert response.status_code == 404
    assert_document(response, "unknown route, document load")
    root = assert_hxml(response, status=404)
    texts = {node.text for node in root.iter() if node.text}
    assert NOT_FOUND in texts
    # No session: the way out is the login screen, as for every anonymous refusal.
    way_out = root.find(".//hv:view[@action='reload']", NS)
    assert way_out.attrib["href"] == "/hv/login/"


def test_an_unknown_hyperview_route_gets_a_bare_fragment_for_a_fragment_load(user):
    client = Client()
    client.force_login(user)

    response = client.get("/hv/nothing-here/", headers={"accept": FRAGMENT_ACCEPT})

    assert response.status_code == 404
    assert_bare_fragment(response, "unknown route, fragment load")


def test_a_modern_client_gets_the_hxml_404_with_its_session_binding(user):
    # The mobile app always negotiates the realtime contract, which adds a realtime
    # boundary to the error screen and a binding to the response. The handler has to
    # build the same answer for it, or the unknown-route fix would only work for old
    # clients.
    client = Client()
    client.force_login(user)
    contract = {CLIENT_CONTRACT_HEADER: CLIENT_CONTRACT}
    binding = client.get("/hv/session-state/", headers=contract).json()["binding"]

    response = client.get(
        "/hv/nothing-here/", headers={**contract, EXPECTED_SESSION_HEADER: binding}
    )

    assert response.status_code == 404
    assert_document(response, "unknown route, modern client")
    assert response[SESSION_BINDING_HEADER] == binding
    assert b"app:realtime" in response.content


def test_an_unknown_post_is_a_404_in_hxml_and_not_a_csrf_failure():
    response = Client(enforce_csrf_checks=True).post("/hv/nothing-here/", {"a": "b"})

    assert response.status_code == 404
    assert_document(response, "unknown route, POST")


@pytest.mark.parametrize("path", ["/nothing-here/", "/realtime/nothing-here/"])
def test_an_unknown_route_outside_the_hyperview_api_keeps_djangos_html_page(path):
    response = Client().get(path)

    assert response.status_code == 404
    assert response.headers["Content-Type"].startswith("text/html")
    assert b"hyperview.org" not in response.content


def test_an_unhandled_error_in_a_screen_is_an_hxml_500(user, monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise RuntimeError("database on fire")

    monkeypatch.setattr(views, "dashboard_summary", broken)
    client = Client(raise_request_exception=False)
    client.force_login(user)

    response = client.get("/hv/dashboard/")

    assert response.status_code == 500
    assert_document(response, "unhandled error, document load")
    root = assert_hxml(response, status=500)
    assert UNAVAILABLE in {node.text for node in root.iter() if node.text}
    assert b"database on fire" not in response.content
    # Answering the error is not handling it: Django still logs the traceback.
    logged = [r for r in caplog.records if r.name == "django.request" and r.exc_info]
    assert [record.exc_info[0] for record in logged] == [RuntimeError]


def test_the_hxml_500_speaks_the_language_the_request_asked_for(user, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("database on fire")

    monkeypatch.setattr(views, "dashboard_summary", broken)
    client = Client(raise_request_exception=False)
    client.force_login(user)

    response = client.get("/hv/dashboard/", headers={"accept-language": "es"})

    root = assert_hxml(response, status=500)
    texts = {node.text for node in root.iter() if node.text}
    assert (
        "No pudimos completar esa solicitud. Inténtalo de nuevo en un momento." in texts
    )


def test_an_unhandled_error_in_a_fragment_endpoint_keeps_its_fragment_shape(
    user, monkeypatch
):
    def broken(**kwargs):
        raise RuntimeError("database on fire")

    monkeypatch.setattr(views, "set_preference", broken)
    client = Client(raise_request_exception=False)
    client.force_login(user)

    response = client.post("/hv/preferences/?theme=dark")

    assert response.status_code == 500
    assert_bare_fragment(response, "unhandled error, fragment endpoint")


def test_the_server_error_page_outside_the_hyperview_api_is_djangos_own():
    request = RequestFactory().get("/admin/")

    response = views.server_error(request)

    assert response.status_code == 500
    assert response.headers["Content-Type"].startswith("text/html")
    assert b"hyperview.org" not in response.content


@pytest.mark.parametrize("broken", ["construct", "render"])
def test_a_failing_hxml_error_falls_back_to_djangos_page(monkeypatch, broken):
    # The handler runs when something is already wrong, so it must never be the thing
    # that turns a 404 or a 500 into an unhandled exception.
    def boom(*args, **kwargs):
        raise RuntimeError("the error screen is broken too")

    if broken == "construct":
        monkeypatch.setattr(views, "_error_response", boom)
    else:
        monkeypatch.setattr(
            views,
            "_error_response",
            lambda *a, **k: SimpleNamespace(is_rendered=False, render=boom),
        )
    request = RequestFactory().get("/hv/anything/")

    not_found = views.not_found(request, Exception())
    failed = views.server_error(request)

    assert isinstance(not_found, HttpResponse) and not_found.status_code == 404
    assert isinstance(failed, HttpResponse) and failed.status_code == 500
    assert not_found.headers["Content-Type"].startswith("text/html")
    assert failed.headers["Content-Type"].startswith("text/html")
