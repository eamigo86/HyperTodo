"""V2 metadata and bounded full-document loaded-prefix refresh contracts."""

import json
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree as ET

import pytest
from dj_hyperview import validate_hyperview_schema
from django.contrib.auth.models import AbstractUser
from django.http import HttpResponse
from django.test import Client

from tests.test_realtime_changes import FEATURE, module
from tests.test_session_contract import _confirm, _headers
from todo.models import Category, Task

pytestmark = pytest.mark.django_db
NS = {
    "hv": "https://hyperview.org/hyperview",
    "app": "https://hypertodo.app/components",
}


def get(
    client: Client, url: str, *, v2: bool = True
) -> tuple[HttpResponse, ET.Element]:
    """Request a screen with the changes feature headers and parse the answer.

    Args:
        client: Client that requests the screen.
        url: Path of the screen requested.
        v2: Whether the request negotiates the v2 changes feature.

    Returns:
        The response and its parsed document.
    """
    binding, _ = _confirm(client, True)
    headers = {**_headers(binding), "X-HyperTodo-Request-ID": "gate-prefix-1"}
    if v2:
        headers[FEATURE] = "changes-v2"
    response = client.get(url, headers=headers)
    validate_hyperview_schema(response.content.decode())
    return response, ET.fromstring(response.content)


@pytest.mark.parametrize(
    "url,mode",
    [
        ("/hv/dashboard/", "readonly"),
        ("/hv/about/", "readonly"),
        ("/hv/tasks/new/", "form"),
        ("/hv/categories/new/", "form"),
        ("/hv/settings/", "form"),
    ],
)
def test_v2_modes_are_negotiated_and_keep_legacy_metadata(
    client: Client, user: AbstractUser, url: str, mode: str
) -> None:
    """V2 modes are negotiated and keep the legacy metadata.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
        url: Path of the screen requested.
        mode: Realtime mode the screen must declare.
    """
    client.force_login(user)
    response, root = get(client, url)
    assert response.status_code == 200
    boundary = root.find(".//app:realtime", NS)
    assert boundary.attrib["mode"] == mode
    if mode == "form":
        assert (
            json.loads(boundary.attrib["entities"])
            == module().capture_entities("default", [("ui", user.pk)]).payload
        )
    _, legacy = get(client, url, v2=False)
    old = legacy.find(".//app:realtime", NS)
    assert old.attrib["mode"] == "notice" and "entities" not in old.attrib


def test_task_form_entity_and_each_select_option_have_opaque_precision(
    client: Client, user: AbstractUser, other_user: AbstractUser
) -> None:
    """The task form entity and each select option have opaque precision.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
    """
    client.force_login(user)
    one = Category.objects.create(user=user, name="One")
    two = Category.objects.create(user=user, name="Two")
    other = Category.objects.create(user=other_user, name="Private other")
    task = Task.objects.create(user=user, title="Task X", category=one)
    _, root = get(client, f"/hv/tasks/{task.pk}/edit/")
    boundary = root.find(".//app:realtime", NS)
    metadata = json.loads(boundary.attrib["entities"])
    assert (
        metadata
        == module()
        .capture_entities("default", [("tasks", task.pk), ("ui", user.pk)])
        .payload
    )
    options = root.findall(".//hv:picker-item", NS)
    assert {item.get("value") for item in options} == {"", str(one.pk), str(two.pk)}
    assert str(other.pk) not in response_text(root)
    for item in options:
        if not item.get("value"):
            assert "realtime-entity-key" not in item.attrib
            continue
        expected = (
            module()
            .capture_entities("default", [("categories", item.get("value"))])
            .payload
        )
        assert item.get("realtime-entity-key") == expected["items"][0]["key"]
        assert item.get("realtime-entity-epoch") == expected["epoch"]
        assert item.get("value") != item.get("realtime-entity-key")
    _, legacy = get(client, f"/hv/tasks/{task.pk}/edit/", v2=False)
    assert all(
        "realtime-entity-key" not in item.attrib
        for item in legacy.findall(".//hv:picker-item", NS)
    )


def response_text(root: ET.Element) -> str:
    """Serialize a parsed document back to text.

    Args:
        root: Parsed document.

    Returns:
        The document serialized as text.
    """
    return ET.tostring(root, encoding="unicode")


def test_category_edit_has_only_own_category_and_profile_dependencies(
    client: Client, user: AbstractUser
) -> None:
    """A category edit has only its own category and profile dependencies.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
    """
    client.force_login(user)
    category = Category.objects.create(user=user, name="Current")
    Category.objects.create(user=user, name="Other")
    _, root = get(client, f"/hv/categories/{category.pk}/edit/")
    assert (
        json.loads(root.find(".//app:realtime", NS).attrib["entities"])
        == module()
        .capture_entities("default", [("categories", category.pk), ("ui", user.pk)])
        .payload
    )


@pytest.mark.parametrize(
    "endpoint,resource", [("tasks", "tasks"), ("categories", "categories")]
)
def test_prefix_two_is_complete_document_with_markers_and_only_next_page(
    client: Client,
    user: AbstractUser,
    other_user: AbstractUser,
    endpoint: str,
    resource: str,
) -> None:
    """A prefix of two is a complete document with markers and only the next page.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
        endpoint: Name of the list endpoint requested.
        resource: Name of the resource the endpoint lists.
    """
    client.force_login(user)
    if endpoint == "tasks":
        category = Category.objects.create(user=user, name="Current category chip")
        Task.objects.bulk_create(
            [Task(user=user, category=category, title=f"T{n:03}") for n in range(45)]
        )
        Task.objects.create(user=other_user, title="Foreign private task")
        url = f"/hv/tasks/?status=active&category={category.pk}&through_page=2"
    else:
        Category.objects.bulk_create(
            [Category(user=user, name=f"C{n:03}") for n in range(45)]
        )
        Category.objects.create(user=other_user, name="Foreign private category")
        url = "/hv/categories/?through_page=2"
    response, root = get(client, url)
    assert (
        response.status_code == 200
        and root.tag == "{https://hyperview.org/hyperview}doc"
    )
    assert root.find(".//hv:styles", NS) is not None
    list_id = "task-list" if endpoint == "tasks" else "category-list"
    listing = root.find(f".//hv:list[@id='{list_id}']", NS)
    assert listing is not None and len(listing.findall("hv:item", NS)) == 40
    assert [
        item.get("page") for item in listing.findall(".//app:realtime-page", NS)
    ] == ["1", "2"]
    append = listing.findall(".//hv:behavior[@action='append']", NS)
    assert len(append) == 1
    query = parse_qs(urlsplit(append[0].get("href")).query)
    assert query["page"] == ["3"] and "through_page" not in query
    assert "Foreign private" not in response_text(root)
    if endpoint == "tasks":
        assert (
            root.find(".//hv:view[@id='filter-active']", NS).get("style")
            == "chip chip-active"
        )
        assert "Current category chip" in response_text(root)
        assert query["status"] == ["active"] and query["category"] == [str(category.pk)]


@pytest.mark.parametrize(
    "count,pages,items", [(0, ["1"], 1), (3, ["1"], 3), (21, ["1", "2"], 21)]
)
def test_prefix_clamps_deleted_tail_without_false_markers(
    client: Client, user: AbstractUser, count: int, pages: list[str], items: int
) -> None:
    """A prefix clamps a deleted tail without false markers.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
        count: Number of tasks created before the request.
        pages: Page markers the list must carry, in order.
        items: Number of rows the list must hold.
    """
    client.force_login(user)
    Task.objects.bulk_create([Task(user=user, title=f"T{n}") for n in range(count)])
    response, root = get(client, "/hv/tasks/?through_page=3")
    assert response.status_code == 200
    listing = root.find(".//hv:list[@id='task-list']", NS)
    assert len(listing.findall("hv:item", NS)) == items
    assert [
        item.get("page") for item in listing.findall(".//app:realtime-page", NS)
    ] == pages
    assert not listing.findall(".//hv:behavior[@action='append']", NS)


@pytest.mark.parametrize(
    "query",
    [
        "through_page=0",
        "through_page=21",
        "through_page=-1",
        "through_page=1.0",
        "through_page=01",
        "through_page=2&page=1",
        "through_page=2&fragment=items",
        "through_page=1&through_page=2",
    ],
)
def test_invalid_or_ambiguous_prefix_is_rejected(
    client: Client, user: AbstractUser, query: str
) -> None:
    """An invalid or ambiguous prefix is rejected.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
        query: Query string the endpoint must reject.
    """
    client.force_login(user)
    response, _ = get(client, "/hv/tasks/?" + query)
    assert response.status_code == 400


def test_prefix_requires_negotiation_not_a_new_legacy_pagination_semantic(
    client: Client, user: AbstractUser
) -> None:
    """A prefix requires negotiation, not a new legacy pagination semantic.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
    """
    client.force_login(user)
    response, _ = get(client, "/hv/tasks/?through_page=2", v2=False)
    assert response.status_code == 400


def test_prefix_maximum_is_400_rows_not_silent_truncation(
    client: Client, user: AbstractUser
) -> None:
    """The prefix maximum is 400 rows, not a silent truncation.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
    """
    client.force_login(user)
    Task.objects.bulk_create([Task(user=user, title=f"T{n}") for n in range(401)])
    response, root = get(client, "/hv/tasks/?through_page=20")
    assert response.status_code == 200
    listing = root.find(".//hv:list[@id='task-list']", NS)
    assert len(listing.findall("hv:item", NS)) == 400
    assert len(listing.findall(".//app:realtime-page", NS)) == 20
    append = listing.findall(".//hv:behavior[@action='append']", NS)
    assert len(append) == 1 and "page=21" in append[0].get("href")


@pytest.mark.parametrize(
    "editing,v2", [(False, True), (True, True), (False, False), (True, False)]
)
def test_422_panel_preserves_current_category_precision_and_draft(
    client: Client, user: AbstractUser, editing: bool, v2: bool
) -> None:
    """A 422 panel preserves the current category precision and the draft.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
        editing: Whether the panel edits an existing category.
        v2: Whether the request negotiates the v2 changes feature.
    """
    client.force_login(user)
    category = Category.objects.create(user=user, name="Own category")
    task = Task.objects.create(user=user, title="Original", category=category)
    binding, _ = _confirm(client, True)
    headers = {**_headers(binding), "X-HyperTodo-Request-ID": "gate-refused-form"}
    if v2:
        headers[FEATURE] = "changes-v2"
    url = f"/hv/tasks/{task.pk}/edit/" if editing else "/hv/tasks/new/"
    response = client.post(
        url,
        {"title": "", "notes": "Unsubmitted draft", "category": str(category.pk)},
        headers=headers,
    )
    assert response.status_code == 422
    validate_hyperview_schema(response.content.decode())
    root = ET.fromstring(response.content)
    assert root.get("id") == "task-form-panel"
    assert (
        root.find(".//hv:text-field[@name='notes']", NS).get("value")
        == "Unsubmitted draft"
    )
    assert root.find(".//hv:picker-field[@name='category']", NS).get("value") == str(
        category.pk
    )
    option = root.find(f".//hv:picker-item[@value='{category.pk}']", NS)
    if v2:
        metadata = (
            module().capture_entities("default", [("categories", category.pk)]).payload
        )
        assert option.get("realtime-entity-key") == metadata["items"][0]["key"]
        assert option.get("realtime-entity-epoch") == metadata["epoch"]
    else:
        assert "realtime-entity-key" not in option.attrib
        assert "realtime-entity-epoch" not in option.attrib
    task.refresh_from_db()
    assert task.title == "Original"  # Validation did not become a save.
