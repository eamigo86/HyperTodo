"""Language resolution, catalog integrity, and marked-string coverage."""

import gettext
import re
from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from tests.test_forms_ui import assert_hxml
from todo.models import Category, Profile, Task

pytestmark = pytest.mark.django_db
LOCALE = Path(settings.BASE_DIR) / "locale/es/LC_MESSAGES"


def body(response):
    """Return the decoded body of an HXML response."""
    assert_hxml(response)
    return response.content.decode()


def test_every_offered_language_is_one_django_can_actually_activate():
    # Two independent lists of the shipped locales. Adding FRENCH to Profile.Language
    # alone is a silent no-op: the endpoint accepts "fr" and says "Language updated.",
    # but ProfileLanguageMiddleware only activates what is in settings.LANGUAGES, so
    # the app stays English and the switcher shows French as not-current forever.
    assert set(Profile.Language.values) == set(dict(settings.LANGUAGES))


def test_a_stored_preference_beats_the_accept_language_header(user):
    # The whole point of storing it. Django 6.1's get_language_from_request
    # resolves cookie -> Accept-Language -> LANGUAGE_CODE and has no channel for a
    # per-account preference, so without the override middleware the header wins.
    Profile.objects.create(user=user, language=Profile.Language.SPANISH)
    client = Client()
    client.force_login(user)

    assert "Tareas" in body(
        client.get(reverse("todo:tasks"), headers={"accept-language": "en-US,en;q=0.9"})
    )


def test_an_account_with_no_stated_preference_follows_the_header(user):
    client = Client()
    client.force_login(user)

    assert "Tareas" in body(
        client.get(reverse("todo:tasks"), headers={"accept-language": "es-ES,es;q=0.9"})
    )
    assert "Tasks" in body(
        client.get(reverse("todo:tasks"), headers={"accept-language": "en-US"})
    )


def test_the_current_language_on_the_request_is_the_one_that_was_activated(user):
    # LocaleMiddleware set request.LANGUAGE_CODE from the header before the
    # override ran. Leaving it stale renders the WRONG option as current while
    # every other string on the screen is right, which is the hardest kind of bug
    # to notice. Read through the rendered selector rather than the attribute.
    Profile.objects.create(user=user, language=Profile.Language.SPANISH)
    client = Client()
    client.force_login(user)

    # The drawer, not Settings: the switcher moved there when Settings became one
    # real form with one Save button.
    root = assert_hxml(
        client.get(reverse("todo:menu"), headers={"accept-language": "en-US"})
    )
    # By href, because the chip carries no id: an id would give the wrapper
    # contentDescription="language-option-es" on Android and TalkBack would speak
    # the slug instead of the label under it.
    current = root.findall(".//*[@href='/hv/preferences/?language=es']")

    assert current, "the Spanish option is missing from the switcher"
    assert "preference-option-current" in current[0].attrib["style"].split()


def test_the_compiled_catalog_agrees_with_its_source_and_carries_no_fuzzy_entry():
    # The .mo is committed so no gate needs msgfmt. The price of a committed
    # binary is staleness, and this is what stops it: gettext SKIPS entries marked
    # fuzzy at runtime and hands back the msgid, so a .po that reads fully
    # translated can ship an English UI.
    source = (LOCALE / "django.po").read_text()

    assert "#, fuzzy" not in source.replace('"Content-Type', "").split("\n\n", 1)[1]

    compiled = gettext.translation("django", str(LOCALE.parents[1]), languages=["es"])
    entries = {k: v for k, v in compiled._catalog.items() if isinstance(k, str) and k}
    for msgid, msgstr in _po_entries(source).items():
        assert entries.get(msgid) == msgstr, msgid


def _po_entries(source):
    """Parse msgid/msgstr pairs out of a .po without a gettext toolchain."""
    entries, msgid, msgstr, target = {}, None, None, None
    for line in source.splitlines() + [""]:
        line = line.strip()
        if line.startswith("msgid "):
            if msgid:
                entries[msgid] = msgstr
            msgid, msgstr, target = _unquote(line[6:]), "", "id"
        elif line.startswith("msgstr "):
            msgstr, target = _unquote(line[7:]), "str"
        elif line.startswith('"'):
            if target == "id":
                msgid += _unquote(line)
            elif target == "str":
                msgstr += _unquote(line)
        elif not line and msgid:
            entries[msgid] = msgstr
            msgid, msgstr, target = None, None, None
    entries.pop("", None)
    return {k: v for k, v in entries.items() if v}


def _unquote(raw):
    """Decode one quoted .po string fragment.

    Hand-rolled rather than via unicode_escape, which round-trips through
    latin-1 and would mangle every accented character in the catalog.
    """
    body = raw.strip()
    body = body[1:-1] if body.startswith('"') and body.endswith('"') else body
    return body.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")


def test_every_marked_string_has_a_non_empty_spanish_translation():
    # The guard against a half-finished catalog. A missing msgstr makes gettext
    # return the msgid, so the app renders English with every gate green.
    translated = _po_entries((LOCALE / "django.po").read_text())
    root = Path(settings.BASE_DIR)
    marked = set()
    for path in (root / "hyperview").rglob("*.xml"):
        source = path.read_text()
        marked |= set(re.findall(r'{%\s*translate\s+"([^"]+)"', source))
        # `{% include ... with header_title=_("Tasks") %}` is a marked string too,
        # and it is how every screen header gets its title.
        marked |= set(re.findall(r'\b_\(\s*"([^"]+)"\s*\)', source))
    for path in (root / "todo").glob("*.py"):
        marked |= set(re.findall(r'\b_\(\s*"([^"]+)"\s*\)', path.read_text()))

    missing = sorted(m for m in marked if m not in translated)

    assert not missing, missing


# The English copy is the msgid, so the Spanish catalog is the only place this can
# go wrong, and nothing in the suite reads a translated string back off a screen.
DEVICE_REJECTED = "This device is no longer recognised. Sign in to enable it again."


def test_a_translated_error_is_shown_once_and_not_twice(user):
    # A rejected device token renders its refusal into the login panel's error card.
    # A msgstr that concatenates two copies of the sentence ships a paragraph where
    # the design has one line, and every gate stays green because no test had ever
    # looked at a translated string's CONTENT.
    Profile.objects.create(user=user, language=Profile.Language.SPANISH)
    client = Client()
    client.force_login(user)

    root = assert_hxml(
        client.post(reverse("todo:biometric-login"), {"biometric_token": "stale"}),
        status=401,
    )
    shown = root.findall(".//*[@id='biometric-error']/*")[0].text

    assert shown.count("dispositivo") == 1, shown


def test_a_plural_string_is_translated_for_every_count_and_not_only_for_one(user):
    # The catalog header shipped `nplurals=3` while every entry supplies two forms,
    # so gettext resolved n=2 to index 2, missed, and fell back to the ENGLISH
    # plural. Only n == 1 was ever right. Nothing else here would notice: the .po
    # parser above skips msgstr[0]/msgstr[1] blocks, and the marked-string scan only
    # reads {% translate %}, never {% blocktranslate count %}.
    Profile.objects.create(user=user, language=Profile.Language.SPANISH)
    category = Category.objects.create(
        user=user, name="Trabajo", color=Category.Color.MINT
    )
    for index in range(2):
        Task.objects.create(user=user, title=f"T{index}", category=category)
    client = Client()
    client.force_login(user)

    assert "2 tareas" in body(client.get(reverse("todo:categories")))


def test_no_translation_is_wildly_longer_than_the_string_it_translates():
    # Spanish runs about 1.2-1.3x the length of English and tops out at 1.55x in
    # this catalog. Anything near double a sentence-length msgid is not a
    # translation, it is a paste that ran twice. The 30-character floor is what
    # keeps legitimate short expansions ("Sign in" -> "Iniciar sesion", 2.0x) out.
    entries = _po_entries((LOCALE / "django.po").read_text())

    bloated = {
        msgid: msgstr
        for msgid, msgstr in entries.items()
        if len(msgid) > 30 and len(msgstr) / len(msgid) > 1.8
    }

    assert not bloated, bloated
