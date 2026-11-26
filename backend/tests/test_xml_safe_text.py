"""Characters XML 1.0 forbids are refused on input and healed in stored rows.

dj-hyperview validates the final document and rejects it whole when one such
character reaches it, so a single stored control character used to turn every
screen that listed it into a permanent 500.
"""

import importlib
from types import SimpleNamespace
from xml.etree.ElementTree import Element

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import connection
from django.http import HttpResponse
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from tests.test_hxml_views import NS, assert_hxml
from todo.forms import CategoryForm, ProfileForm, TaskForm
from todo.models import Category, Task
from todo.validators import scrub_xml, xml_safe_text

pytestmark = pytest.mark.django_db

# Written as escapes on purpose: a literal copy of these characters would be
# invisible, or be mangled by an editor.
FFFD = "\N{REPLACEMENT CHARACTER}"
FORBIDDEN = [
    "\x00",
    "\x01",
    "\x08",
    "\x0b",
    "\x0c",
    "\x0e",
    "\x1f",
    "\U0000d800",
    "\U0000dfff",
    "\U0000fffe",
    "\U0000ffff",
]
ALLOWED = [
    "plain",
    "tab\tnewline\ncarriage\rreturn",
    "caf\xe9 ni\xf1o",
    "emoji \U0001f600 and \U00010000",
    f"\U0000d7ff\U0000e000{FFFD}",
]
MESSAGE = "Remove control characters."


@pytest.mark.parametrize("value", ALLOWED)
def test_the_validator_accepts_everything_xml_can_carry(value: str) -> None:
    """The validator accepts everything XML can carry.

    Args:
        value: Text XML can carry.
    """
    xml_safe_text(value)


@pytest.mark.parametrize("character", FORBIDDEN)
def test_the_validator_rejects_each_forbidden_character(character: str) -> None:
    """The validator rejects each forbidden character.

    Args:
        character: One character XML cannot carry.
    """
    with pytest.raises(ValidationError) as caught:
        xml_safe_text(f"Buy{character}milk")

    assert caught.value.code == "xml_chars"
    assert caught.value.messages == [MESSAGE]


def test_scrubbing_replaces_only_what_xml_forbids() -> None:
    """Scrubbing replaces only what XML forbids."""
    dirty = "a\x01b\U0000d800c\U0000ffff\td\n"

    assert scrub_xml(dirty) == f"a{FFFD}b{FFFD}c{FFFD}\td\n"
    assert scrub_xml("clean \xe9") == "clean \xe9"


def test_the_models_refuse_forbidden_characters_and_overlong_notes(
    user: AbstractUser,
) -> None:
    """The models refuse forbidden characters and overlong notes.

    Args:
        user: Signed-in user who owns the data in this test.
    """
    task = Task(user=user, title="Buy\x01milk", notes="a\x0bb")
    category = Category(user=user, name="Work\x02", color=Category.Color.MINT)

    with pytest.raises(ValidationError) as task_errors:
        task.full_clean()
    with pytest.raises(ValidationError) as category_errors:
        category.full_clean()

    for errors, field in (
        (task_errors, "title"),
        (task_errors, "notes"),
        (category_errors, "name"),
    ):
        assert [e.code for e in errors.value.error_dict[field]] == ["xml_chars"]
    assert Task._meta.get_field("notes").max_length == 10_000


def test_the_forms_report_the_error_on_the_offending_field(user: AbstractUser) -> None:
    """The forms report the error on the offending field.

    Args:
        user: Signed-in user who owns the data in this test.
    """
    category = CategoryForm({"name": "a\x01", "color": "mint"}, user=user)
    task = TaskForm({"title": "a\x01", "notes": "b\x0cc"}, user=user)
    profile = ProfileForm(
        {
            "first_name": "a\x01",
            "last_name": "b\U0000fffe",
            # Django accepts control characters inside a quoted local part.
            "email": '"a\x01b"@example.com',
        },
        instance=user,
    )

    for form, fields in (
        (category, ["name"]),
        (task, ["title", "notes"]),
        (profile, ["first_name", "last_name", "email"]),
    ):
        assert not form.is_valid()
        assert sorted(form.errors) == sorted(fields)
        for field in fields:
            assert form.errors.as_data()[field][0].code == "xml_chars"


def test_overlong_notes_are_refused_by_the_form(user: AbstractUser) -> None:
    """Overlong notes are refused by the form.

    Args:
        user: Signed-in user who owns the data in this test.
    """
    assert TaskForm({"title": "ok", "notes": "n" * 10_000}, user=user).is_valid()

    form = TaskForm({"title": "ok", "notes": "n" * 10_001}, user=user)

    assert not form.is_valid()
    assert list(form.errors) == ["notes"]


def _errors(root: Element) -> list[str | None]:
    return [node.text for node in root.findall(".//hv:text[@style='field-error']", NS)]


def _value(root: Element, name: str) -> str:
    return root.find(f".//hv:text-field[@name='{name}']", NS).attrib["value"]


def test_a_task_with_control_characters_is_refused_and_the_screens_survive(
    user: AbstractUser,
) -> None:
    """A task with control characters is refused and the screens survive.

    Args:
        user: Signed-in user who owns the data in this test.
    """
    client = Client()
    client.force_login(user)

    response = client.post(
        reverse("todo:task-new"), {"title": "Buy\x01milk", "notes": "a\x0bb"}
    )
    root = assert_hxml(response, status=422)

    assert root.attrib["id"] == "task-form-panel"
    assert _errors(root) == [MESSAGE, MESSAGE]
    # The refusal echoes the submission, so the echo has to be XML-safe too.
    assert _value(root, "title") == f"Buy{FFFD}milk"
    assert _value(root, "notes") == f"a{FFFD}b"
    assert not Task.objects.exists()
    assert_hxml(client.get(reverse("todo:tasks")))
    assert_hxml(client.get(reverse("todo:dashboard")))


def test_editing_a_task_with_control_characters_keeps_the_stored_title(
    user: AbstractUser,
) -> None:
    """Editing a task with control characters keeps the stored title.

    Args:
        user: Signed-in user who owns the data in this test.
    """
    client = Client()
    client.force_login(user)
    task = Task.objects.create(user=user, title="Original")

    response = client.post(
        reverse("todo:task-edit", args=(task.pk,)), {"title": "Edited\x01"}
    )

    assert_hxml(response, status=422)
    task.refresh_from_db()
    assert task.title == "Original"


def test_notes_beyond_the_limit_answer_422_with_a_field_error(
    user: AbstractUser,
) -> None:
    """Notes beyond the limit answer 422 with a field error.

    Args:
        user: Signed-in user who owns the data in this test.
    """
    client = Client()
    client.force_login(user)

    response = client.post(
        reverse("todo:task-new"), {"title": "Long", "notes": "n" * 10_001}
    )
    root = assert_hxml(response, status=422)

    assert len(_errors(root)) == 1
    assert not Task.objects.exists()


def test_a_category_with_control_characters_is_refused(user: AbstractUser) -> None:
    """A category with control characters is refused.

    Args:
        user: Signed-in user who owns the data in this test.
    """
    client = Client()
    client.force_login(user)

    response = client.post(
        reverse("todo:category-new"), {"name": "Work\x01", "color": "mint"}
    )
    root = assert_hxml(response, status=422)

    assert _errors(root) == [MESSAGE]
    assert _value(root, "name") == f"Work{FFFD}"
    assert not Category.objects.exists()
    assert_hxml(client.get(reverse("todo:categories")))


def test_a_rejected_color_choice_never_echoes_raw_control_characters(
    user: AbstractUser,
) -> None:
    """A rejected color choice never echoes raw control characters.

    Args:
        user: Signed-in user who owns the data in this test.
    """
    client = Client()
    client.force_login(user)

    response = client.post(
        reverse("todo:category-new"), {"name": "Work", "color": "mint\x01"}
    )
    root = assert_hxml(response, status=422)

    assert FFFD in "".join(_errors(root))


def test_profile_names_with_control_characters_leave_settings_usable(
    user: AbstractUser,
) -> None:
    """Profile names with control characters leave settings usable.

    Args:
        user: Signed-in user who owns the data in this test.
    """
    client = Client()
    client.force_login(user)

    response = client.post(
        reverse("todo:settings"),
        {
            "first_name": "Ada\x01",
            "last_name": "Love\U0000fffe",
            "email": '"a\x01"@x.io',
        },
    )
    root = assert_hxml(response, status=422)

    assert root.attrib["id"] == "settings-form-panel"
    assert _errors(root) == [MESSAGE, MESSAGE, MESSAGE]
    assert _value(root, "first_name") == f"Ada{FFFD}"
    user.refresh_from_db()
    assert (user.first_name, user.last_name, user.email) == ("", "", "")
    assert_hxml(client.get(reverse("todo:settings")))
    assert_hxml(client.get(reverse("todo:dashboard")))


def test_a_username_with_control_characters_cannot_break_the_login_panel() -> None:
    """A username with control characters cannot break the login panel."""
    root = assert_hxml(
        Client().post(reverse("todo:login"), {"username": "a\x01b", "password": "x"}),
        status=422,
    )

    assert root.attrib["id"] == "login-panel"
    assert _value(root, "username") == f"a{FFFD}b"


def test_a_row_stored_before_the_validators_still_opens_its_edit_screen(
    user: AbstractUser, other_user: AbstractUser
) -> None:
    """A row stored before the validators still opens its edit screen.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
    """
    # The task screen also lists its owner's categories, which only the data
    # migration can heal, so the two poisoned rows belong to different owners.
    task = Task.objects.create(user=user, title="Buy\x01milk", notes="a\x0bb")
    category = Category.objects.create(
        user=other_user, name="Work\x02", color=Category.Color.MINT
    )
    client = Client()

    client.force_login(user)
    task_root = assert_hxml(client.get(reverse("todo:task-edit", args=(task.pk,))))
    client.force_login(other_user)
    category_root = assert_hxml(
        client.get(reverse("todo:category-edit", args=(category.pk,)))
    )

    assert _value(task_root, "title") == f"Buy{FFFD}milk"
    assert _value(task_root, "notes") == f"a{FFFD}b"
    assert _value(category_root, "name") == f"Work{FFFD}"


# --- data migration ---------------------------------------------------------


def _run_cleaning() -> None:
    migration = importlib.import_module("todo.migrations.0005_clean_xml_illegal_text")
    migration.clean_xml_text(apps, SimpleNamespace(connection=connection))


def test_the_data_migration_heals_every_poisoned_column(
    user: AbstractUser, other_user: AbstractUser
) -> None:
    """The data migration heals every poisoned column.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
    """
    get_user_model().objects.filter(pk=user.pk).update(
        first_name="Ada\x01", last_name="\U0000fffeLove", email='"a\x01"@x.io'
    )
    task = Task.objects.create(user=user, title="Buy\x01milk", notes="a\x0bb\x0c")
    clean = Task.objects.create(user=user, title="Fine", notes="Fine too")
    category = Category.objects.create(
        user=user, name="Work\x02", color=Category.Color.MINT
    )

    _run_cleaning()

    user.refresh_from_db()
    assert (user.first_name, user.last_name, user.email) == (
        f"Ada{FFFD}",
        f"{FFFD}Love",
        f'"a{FFFD}"@x.io',
    )
    task.refresh_from_db()
    assert (task.title, task.notes) == (f"Buy{FFFD}milk", f"a{FFFD}b{FFFD}")
    category.refresh_from_db()
    assert category.name == f"Work{FFFD}"
    clean.refresh_from_db()
    assert (clean.title, clean.notes) == ("Fine", "Fine too")
    other_user.refresh_from_db()
    assert other_user.first_name == ""


def test_the_data_migration_numbers_categories_that_now_collide(
    user: AbstractUser, other_user: AbstractUser
) -> None:
    """The data migration numbers categories that now collide.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
    """
    first = Category.objects.create(user=user, name="a\x01b", color="mint")
    second = Category.objects.create(user=user, name="a\x02b", color="pink")
    existing = Category.objects.create(user=user, name=f"A{FFFD}B", color="green")
    foreign = Category.objects.create(user=other_user, name="a\x03b", color="mint")

    _run_cleaning()

    names = {category.pk: category.name for category in Category.objects.all()}
    assert names[existing.pk] == f"A{FFFD}B"
    assert names[foreign.pk] == f"a{FFFD}b"
    assert {names[first.pk], names[second.pk]} == {
        f"a{FFFD}b (2)",
        f"a{FFFD}b (3)",
    }
    owned = Category.objects.filter(user=user).values_list("name", flat=True)
    assert len({name.lower() for name in owned}) == 3


def test_the_data_migration_can_run_twice(user: AbstractUser) -> None:
    """The data migration can run twice.

    Args:
        user: Signed-in user who owns the data in this test.
    """
    Task.objects.create(user=user, title="Buy\x01milk")

    _run_cleaning()
    _run_cleaning()

    assert Task.objects.get().title == f"Buy{FFFD}milk"


def test_the_data_migration_reads_each_table_in_primary_key_chunks(
    user: AbstractUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The data migration reads each table in primary-key chunks.

    Args:
        user: Signed-in user who owns the data in this test.
        monkeypatch: Patches the code under test for this test.
    """
    migration = importlib.import_module("todo.migrations.0005_clean_xml_illegal_text")
    monkeypatch.setattr(migration, "CHUNK", 2)
    poisoned = {0, 1, 2, 5, 6}
    tasks = [
        Task.objects.create(
            user=user, title=f"Task {n}\x01" if n in poisoned else f"Task {n}"
        )
        for n in range(7)
    ]

    with CaptureQueriesContext(connection) as captured:
        _run_cleaning()

    # Rows on both sides of every chunk boundary are healed...
    assert [Task.objects.get(pk=task.pk).title for task in tasks] == [
        f"Task {n}{FFFD}" if n in poisoned else f"Task {n}" for n in range(7)
    ]
    # ...and no read ever asks for more than one chunk of them.
    reads = [
        query["sql"]
        for query in captured
        if query["sql"].startswith("SELECT") and 'FROM "todo_task"' in query["sql"]
    ]
    assert len(reads) > 1
    assert all("LIMIT 2" in sql for sql in reads)


# --- Django admin -----------------------------------------------------------


@pytest.fixture
def admin_session(client: Client) -> Client:
    """Sign the client in as a superuser and return it.

    Args:
        client: Client that requests the screens under test.

    Returns:
        The client, signed in as a superuser.
    """
    root = get_user_model().objects.create_superuser(
        "root", "root@example.com", "correct-horse"
    )
    client.force_login(root)
    return client


def _change_user(client: Client, target: AbstractUser, **fields: str) -> HttpResponse:
    joined = timezone.localtime(target.date_joined)
    data = {
        "username": target.username,
        "first_name": target.first_name,
        "last_name": target.last_name,
        "email": target.email,
        "is_active": "on",
        "date_joined_0": joined.strftime("%Y-%m-%d"),
        "date_joined_1": joined.strftime("%H:%M:%S"),
        **fields,
    }
    return client.post(reverse("admin:auth_user_change", args=(target.pk,)), data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("first_name", "Ada\x01"),
        ("last_name", "\U0000fffeLovelace"),
        # Django accepts control characters inside a quoted local part.
        ("email", '"a\x0b"@example.com'),
    ],
)
def test_the_admin_user_form_refuses_what_a_document_cannot_carry(
    admin_session: Client, user: AbstractUser, field: str, value: str
) -> None:
    """The admin user form refuses what a document cannot carry.

    Args:
        admin_session: Client signed in as a superuser.
        user: Signed-in user who owns the data in this test.
        field: Name of the user field the admin form is given a bad value for.
        value: Text a document cannot carry.
    """
    response = _change_user(admin_session, user, **{field: value})

    assert response.status_code == 200
    assert MESSAGE in response.content.decode()
    user.refresh_from_db()
    assert getattr(user, field) == ""


def test_the_admin_user_form_still_saves_ordinary_text(
    admin_session: Client, user: AbstractUser
) -> None:
    """The admin user form still saves ordinary text.

    Args:
        admin_session: Client signed in as a superuser.
        user: Signed-in user who owns the data in this test.
    """
    response = _change_user(
        admin_session,
        user,
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
    )

    assert response.status_code == 302
    user.refresh_from_db()
    assert (user.first_name, user.last_name, user.email) == (
        "Ada",
        "Lovelace",
        "ada@example.com",
    )
