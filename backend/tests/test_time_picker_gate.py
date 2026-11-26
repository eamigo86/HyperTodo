"""The native time-picker is served only to the binaries that register it.

HyperTodo 1.3.0 added the app:time-picker component. A 1.2.1 binary has no such
component, and Hyperview renders an element nobody registered as nothing, so the "Due
time" label would sit over an empty row and the person could neither set nor change a
time. Those clients keep the text field the form used before the picker.
"""

import re
from pathlib import Path
from xml.etree.ElementTree import Element

import pytest
from dj_hyperview.validation import validate_fragment_hxml, validate_hxml
from django.contrib.auth.models import AbstractUser
from django.http import HttpResponse
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from tests.test_hxml_views import NS, assert_hxml, csrf_client, token_from
from tests.test_user_timezone import create_deadline, screen_values, stored_deadline
from todo.views import MIN_TIME_PICKER_VERSION, _supports_time_picker

pytestmark = pytest.mark.django_db

PICKER_CLIENTS = ["1.3.0", "1.3", "1.3.0-rc1", "1.3.1", "1.4.0", "2.0.0"]
LEGACY_CLIENTS = [None, "", "1.0.0", "1.2.1", "1.2.99", "nightly", "x" * 64]


@pytest.mark.parametrize(
    ("announced", "supported"),
    [
        (None, False),
        ("", False),
        ("1.2.1", False),
        ("1.2.99", False),
        ("1.3", True),  # a two-part version is 1.3.0
        ("1.3.0", True),
        ("1.3.0-rc1", True),  # built from the 1.3.0 source, so it has the component
        ("1.4.0", True),
        ("2.0.0", True),
        ("nightly", False),
        ("x" * 64, False),  # longer than APP_VERSION_PATTERN allows, so "unknown"
    ],
)
def test_the_time_picker_capability_is_gated_on_the_announced_client_version(
    rf: RequestFactory, announced: str | None, supported: bool
) -> None:
    """The time-picker capability is gated on the announced client version.

    Args:
        rf: Factory that builds the requests under test.
        announced: Client version the request announces, or None for no header.
        supported: Whether the capability is expected to be advertised.
    """
    headers = {} if announced is None else {"HTTP_X_APP_VERSION": announced}

    assert _supports_time_picker(rf.get("/hv/tasks/new/", **headers)) is supported


def test_the_time_picker_gate_opens_at_the_release_that_registered_the_component() -> (
    None
):
    """The time-picker gate opens at the release that registered the component."""
    assert MIN_TIME_PICKER_VERSION == (1, 3, 0)


def test_the_shipped_client_version_can_actually_open_the_time_picker_gate() -> None:
    """The shipped client version can actually open the time-picker gate."""
    # Leave app.config.ts behind and every real client is served the legacy field
    # forever, so a successful deploy would change nothing for the people who have
    # the picker.
    config = (Path(__file__).resolve().parents[2] / "mobile/app.config.ts").read_text()
    declared = re.search(r'version:\s*"([0-9]+(?:\.[0-9]+)*)"', config)

    assert declared is not None, "no version literal in mobile/app.config.ts"
    shipped = tuple((list(map(int, declared.group(1).split("."))) + [0, 0, 0])[:3])
    assert shipped >= MIN_TIME_PICKER_VERSION


def announce(version: str | None) -> dict[str, str]:
    """Return the request headers a client of this version sends.

    Args:
        version: Client version announced in the request header, or None for no header.

    Returns:
        Headers that announce the version, empty when there is none.
    """
    return {} if version is None else {"x-app-version": version}


def assert_time_field(root: Element, *, picker: bool) -> None:
    """Assert which of the two markups the form carries for the due time.

    Args:
        root: Rendered form document.
        picker: Whether the form is expected to carry the time picker markup.
    """
    pickers = root.findall(".//app:time-picker", NS)
    [field] = root.findall(".//hv:text-field[@name='due_time']", NS)
    if picker:
        assert len(pickers) == 1
        assert field.attrib["hide"] == "true"
        assert "mask" not in field.attrib
        return
    assert pickers == []
    assert "hide" not in field.attrib
    assert field.attrib["mask"] == "99:99"
    assert field.attrib["keyboard-type"] == "number-pad"
    assert field.attrib["placeholder"] == "HH:MM"
    assert field.attrib["accessibilityLabel"] == "Due time"


def signed_in_client(user: AbstractUser) -> Client:
    """Return a CSRF-enforcing client signed in as the user.

    Args:
        user: Signed-in user who owns the data in this test.

    Returns:
        Client with CSRF checks that is signed in as the user.
    """
    client = csrf_client()
    client.force_login(user)
    return client


def refused_post(
    client: Client, route: str, version: str | None, **kwargs: object
) -> HttpResponse:
    """Post a task form the server refuses, so it answers 422 with the panel.

    Args:
        client: Client that requests the screens under test.
        route: Route name of the screen under test.
        version: Client version announced in the request header, or None for no header.
        **kwargs: Keyword arguments given to reverse to build the form URL.

    Returns:
        The 422 response the refused post produced.
    """
    token = token_from(client.get(reverse(route, **kwargs)))
    return client.post(
        reverse(route, **kwargs),
        {"title": "", "due_time": "09:00", "csrfmiddlewaretoken": token},
        headers=announce(version),
    )


@pytest.mark.parametrize(
    ("version", "picker"),
    [(v, True) for v in PICKER_CLIENTS] + [(v, False) for v in LEGACY_CLIENTS],
)
@pytest.mark.parametrize("route", ["todo:task-new", "todo:task-edit"])
def test_the_due_time_control_follows_the_announced_client_version(
    user: AbstractUser, route: str, version: str | None, picker: bool
) -> None:
    """The due time control follows the announced client version.

    Args:
        user: Signed-in user who owns the data in this test.
        route: Route name of the screen under test.
        version: Client version announced in the request header, or None for no header.
        picker: Whether the form is expected to carry the time picker markup.
    """
    task = create_deadline(user, "2026-06-10", "09:30")[1]
    kwargs = {"args": (task.pk,)} if route == "todo:task-edit" else {}
    client = signed_in_client(user)

    response = client.get(reverse(route, **kwargs), headers=announce(version))

    assert_time_field(assert_hxml(response), picker=picker)


@pytest.mark.parametrize("version", ["1.3.0", "1.2.1", None])
def test_both_markups_validate_against_the_app_schema(
    user: AbstractUser, version: str | None
) -> None:
    """Both markups validate against the app schema.

    Args:
        user: Signed-in user who owns the data in this test.
        version: Client version announced in the request header, or None for no header.
    """
    client = signed_in_client(user)

    screen = client.get(reverse("todo:task-new"), headers=announce(version))
    refused = refused_post(client, "todo:task-new", version)

    validate_hxml(screen.content.decode())
    validate_fragment_hxml(refused.content.decode())
    assert refused.status_code == 422


@pytest.mark.parametrize("version", PICKER_CLIENTS[:1] + LEGACY_CLIENTS[:3])
@pytest.mark.parametrize("route", ["todo:task-new", "todo:task-edit"])
def test_the_task_form_answers_every_request_with_vary_on_the_version(
    user: AbstractUser, route: str, version: str | None
) -> None:
    """The task form answers every request with Vary on the version.

    Args:
        user: Signed-in user who owns the data in this test.
        route: Route name of the screen under test.
        version: Client version announced in the request header, or None for no header.
    """
    task = create_deadline(user, "2026-06-10", "09:30")[1]
    kwargs = {"args": (task.pk,)} if route == "todo:task-edit" else {}
    client = signed_in_client(user)

    screen = client.get(reverse(route, **kwargs), headers=announce(version))
    refused = refused_post(client, route, version, **kwargs)

    assert refused.status_code == 422
    for response in (screen, refused):
        varies = {field.strip().lower() for field in response["Vary"].split(",")}
        assert "x-app-version" in varies, response["Vary"]


@pytest.mark.parametrize("version", ["1.3.0", "1.2.1"])
def test_a_refused_form_keeps_the_time_that_was_posted_in_either_markup(
    user: AbstractUser, version: str | None
) -> None:
    """A refused form keeps the time that was posted in either markup.

    Args:
        user: Signed-in user who owns the data in this test.
        version: Client version announced in the request header, or None for no header.
    """
    client = signed_in_client(user)

    root = assert_hxml(refused_post(client, "todo:task-new", version), status=422)

    assert_time_field(root, picker=version == "1.3.0")
    [field] = root.findall(".//hv:text-field[@name='due_time']", NS)
    assert field.attrib["value"] == "09:00"
    owner = root.find(".//app:time-picker", NS) if version == "1.3.0" else field
    assert "field-invalid" in (owner.attrib.get("field-style") or owner.attrib["style"])


@pytest.mark.parametrize("version", ["1.3.0", "1.2.1"])
def test_either_markup_posts_the_time_as_hh_mm(
    user: AbstractUser, version: str | None
) -> None:
    """Either markup posts the time as HH:MM.

    Args:
        user: Signed-in user who owns the data in this test.
        version: Client version announced in the request header, or None for no header.
    """
    # The legacy control is a masked text field, so it posts what was typed, "14:45";
    # the picker's hidden child posts the same shape. The form reads both alike.
    client, task = create_deadline(user, "2026-06-10", "09:30")
    values = screen_values(
        client.get(
            reverse("todo:task-edit", args=(task.pk,)), headers=announce(version)
        )
    )
    assert values["due_time"] == "09:30"

    response = client.post(
        reverse("todo:task-edit", args=(task.pk,)),
        {**values, "due_time": "14:45"},
        headers=announce(version),
    )

    assert_hxml(response)
    due_at, all_day = stored_deadline(task)
    assert timezone.localtime(due_at).strftime("%H:%M") == "14:45"
    assert all_day is False


@pytest.mark.parametrize("version", ["1.3.0", "1.2.1", None])
def test_a_title_only_save_keeps_the_stored_deadline_for_every_client(
    user: AbstractUser, version: str | None
) -> None:
    """A title-only save keeps the stored deadline for every client.

    Args:
        user: Signed-in user who owns the data in this test.
        version: Client version announced in the request header, or None for no header.
    """
    client, task = create_deadline(user, "2026-06-10", "09:30")
    before = stored_deadline(task)
    values = screen_values(
        client.get(
            reverse("todo:task-edit", args=(task.pk,)), headers=announce(version)
        )
    )

    response = client.post(
        reverse("todo:task-edit", args=(task.pk,)),
        {**values, "title": "Pay rent on time"},
        headers=announce(version),
    )

    assert_hxml(response)
    task.refresh_from_db()
    assert task.title == "Pay rent on time"
    assert stored_deadline(task) == before
