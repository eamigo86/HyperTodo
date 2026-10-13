"""Characters XML 1.0 forbids are refused on input and healed in stored rows.

dj-hyperview validates the final document and rejects it whole when one such
character reaches it, so a single stored control character used to turn every
screen that listed it into a permanent 500.
"""

import importlib
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client
from django.urls import reverse

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
def test_the_validator_accepts_everything_xml_can_carry(value):
    xml_safe_text(value)


@pytest.mark.parametrize("character", FORBIDDEN)
def test_the_validator_rejects_each_forbidden_character(character):
    with pytest.raises(ValidationError) as caught:
        xml_safe_text(f"Buy{character}milk")

    assert caught.value.code == "xml_chars"
    assert caught.value.messages == [MESSAGE]


def test_scrubbing_replaces_only_what_xml_forbids():
    dirty = "a\x01b\U0000d800c\U0000ffff\td\n"

    assert scrub_xml(dirty) == f"a{FFFD}b{FFFD}c{FFFD}\td\n"
    assert scrub_xml("clean \xe9") == "clean \xe9"


def test_the_models_refuse_forbidden_characters_and_overlong_notes(user):
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


def test_the_forms_report_the_error_on_the_offending_field(user):
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


def test_overlong_notes_are_refused_by_the_form(user):
    assert TaskForm({"title": "ok", "notes": "n" * 10_000}, user=user).is_valid()

    form = TaskForm({"title": "ok", "notes": "n" * 10_001}, user=user)

    assert not form.is_valid()
    assert list(form.errors) == ["notes"]


def _errors(root):
    return [node.text for node in root.findall(".//hv:text[@style='field-error']", NS)]


def _value(root, name):
    return root.find(f".//hv:text-field[@name='{name}']", NS).attrib["value"]


def test_a_task_with_control_characters_is_refused_and_the_screens_survive(user):
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


def test_editing_a_task_with_control_characters_keeps_the_stored_title(user):
    client = Client()
    client.force_login(user)
    task = Task.objects.create(user=user, title="Original")

    response = client.post(
        reverse("todo:task-edit", args=(task.pk,)), {"title": "Edited\x01"}
    )

    assert_hxml(response, status=422)
    task.refresh_from_db()
    assert task.title == "Original"


def test_notes_beyond_the_limit_answer_422_with_a_field_error(user):
    client = Client()
    client.force_login(user)

    response = client.post(
        reverse("todo:task-new"), {"title": "Long", "notes": "n" * 10_001}
    )
    root = assert_hxml(response, status=422)

    assert len(_errors(root)) == 1
    assert not Task.objects.exists()


def test_a_category_with_control_characters_is_refused(user):
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


def test_a_rejected_color_choice_never_echoes_raw_control_characters(user):
    client = Client()
    client.force_login(user)

    response = client.post(
        reverse("todo:category-new"), {"name": "Work", "color": "mint\x01"}
    )
    root = assert_hxml(response, status=422)

    assert FFFD in "".join(_errors(root))


def test_profile_names_with_control_characters_leave_settings_usable(user):
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


def test_a_username_with_control_characters_cannot_break_the_login_panel():
    root = assert_hxml(
        Client().post(reverse("todo:login"), {"username": "a\x01b", "password": "x"}),
        status=422,
    )

    assert root.attrib["id"] == "login-panel"
    assert _value(root, "username") == f"a{FFFD}b"


def test_a_row_stored_before_the_validators_still_opens_its_edit_screen(
    user, other_user
):
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


def _run_cleaning():
    migration = importlib.import_module("todo.migrations.0005_clean_xml_illegal_text")
    migration.clean_xml_text(apps, SimpleNamespace(connection=connection))


def test_the_data_migration_heals_every_poisoned_column(user, other_user):
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


def test_the_data_migration_numbers_categories_that_now_collide(user, other_user):
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


def test_the_data_migration_can_run_twice(user):
    Task.objects.create(user=user, title="Buy\x01milk")

    _run_cleaning()
    _run_cleaning()

    assert Task.objects.get().title == f"Buy{FFFD}milk"
