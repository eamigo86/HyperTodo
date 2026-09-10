"""Permanent consumer contracts for automatic, strict HXML compatibility."""

import hashlib
import json
import re
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from xml.etree import ElementTree

import pytest
from django.conf import settings

from tests.test_preferences import FLAGS, HOSTS, option_of, switcher

ROOT = Path(__file__).resolve().parents[1] / "hyperview"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
MANIFEST = json.loads((FIXTURES / "schema_corpus.json").read_text())
STYLE_HASHES = json.loads((FIXTURES / "schema_style_hashes.json").read_text())
NS = {"hv": "https://hyperview.org/hyperview"}


def test_schema_corpus_manifest_names_every_source():
    assert set(MANIFEST) == {
        str(path.relative_to(ROOT)) for path in ROOT.rglob("*.xml")
    }
    assert {
        kind: sum(row["kind"] == kind for row in MANIFEST.values())
        for kind in ("document", "fragment", "partial")
    } == {
        "document": 12,
        "fragment": 21,
        "partial": 7,
    }


@pytest.mark.parametrize("name", STYLE_HASHES)
def test_screen_owns_its_original_stylesheet(name):
    source = (ROOT / name).read_text()
    stylesheet = re.search(r"<styles>.*?</styles>", source, re.S)[0]
    assert hashlib.sha256(stylesheet.encode()).hexdigest() == STYLE_HASHES[name]
    assert source.count("<styles>") == 1
    assert source.index("<screen") < source.index("<styles>"), name
    assert source.index("</styles>") < source.index("<body"), name


@pytest.mark.django_db
@pytest.mark.parametrize("host", HOSTS)
@pytest.mark.parametrize("language", sorted(FLAGS))
def test_language_decoration_uses_inline_text_without_string_booleans(
    host, language, user
):
    option = option_of(switcher(user, host), language)
    labels = option.findall("./hv:text", NS)
    assert len(labels) == 1
    label = labels[0]
    assert label.attrib["accessibilityRole"] == "button"
    assert label.attrib["accessibilityLabel"]
    content = label.find("./hv:text", NS)
    assert content is not None
    assert content.attrib["accessibilityRole"] == "none"
    flag = content.find("./hv:text[@style='preference-option-flag']", NS)
    assert flag is not None and flag.text == FLAGS[language]
    assert flag.attrib["importantForAccessibility"] == "no"
    for element in option.iter():
        assert (
            not {"accessible", "accessibilityElementsHidden", "hide", "id"}
            & element.attrib.keys()
        )
    assert {"en": "English", "es": "Español"}[language] in "".join(label.itertext())
    assert ElementTree.tostring(label, encoding="unicode")
    assert settings.HYPERVIEW["ADMIN"] == {"EDITOR": True}


def _configuration_from_environment():
    spec = spec_from_file_location(
        "config._schema_contract_settings", ROOT.parent / "config/settings.py"
    )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.HYPERVIEW


def test_ordinary_launch_declares_extensions_without_validation_selectors():
    configuration = _configuration_from_environment()
    assert "SCHEMA_PROFILE" not in configuration
    assert "VALIDATION" not in configuration
    assert configuration["EXTRA_SCHEMAS"] == [
        settings.BASE_DIR / "schema/hypertodo.xsd"
    ]
    assert "SCHEMA_EXTENSIONS" in configuration


def test_configuration_declares_only_owned_extensions():
    configuration = _configuration_from_environment()
    registry = configuration["SCHEMA_EXTENSIONS"]
    behavior_attributes = {
        "notify-resources": {"resources"},
        "show-snackbar": {"message", "tone"},
        "store-biometric-token": {"token"},
        "probe-biometrics": {"available-target", "token-target"},
        "biometric-unlock": {"prompt"},
        "pick-avatar": {"preview-target", "current-target"},
    }
    assert set(registry["BEHAVIORS"]) == set(behavior_attributes)
    for action, names in behavior_attributes.items():
        attributes = registry["BEHAVIORS"][action]["ATTRIBUTES"]
        assert set(attributes) == names
        assert all(attribute["TYPE"] == "string" for attribute in attributes.values())
        assert all(
            attribute.get("REQUIRED", False) == (action == "notify-resources")
            for attribute in attributes.values()
        )
    assert registry["BEHAVIORS"]["show-snackbar"]["ATTRIBUTES"]["tone"]["ENUM"] == [
        "success",
        "error",
    ]
    assert registry["ELEMENT_ATTRIBUTES"] == {
        "image": {"variant": {"TYPE": "string", "ENUM": ["face", "fingerprint"]}},
        "picker-item": {
            "realtime-entity-key": {"TYPE": "string"},
            "realtime-entity-epoch": {"TYPE": "string"},
        },
    }


@pytest.mark.django_db
@pytest.mark.parametrize("version", (None, "1.2.0"))
def test_idle_avatar_preview_has_a_hidden_local_transparent_source(user, version):
    from django.test import Client

    client = Client(headers={"x-app-version": version} if version else {})
    client.force_login(user)
    root = ElementTree.fromstring(client.get("/hv/settings/").content)
    preview = root.find(".//hv:image[@id='avatar-preview']", NS)
    assert preview is not None
    assert preview.attrib["hide"] == "true"
    assert preview.attrib.get("source", "").startswith("data:image/png;base64,")
    assert "alt" not in preview.attrib
    from base64 import b64decode
    from io import BytesIO

    from PIL import Image

    image = Image.open(BytesIO(b64decode(preview.attrib["source"].split(",", 1)[1])))
    assert image.size == (1, 1)
    assert image.convert("RGBA").getpixel((0, 0))[3] == 0


def test_extension_declarations_are_detached_between_configurations():
    first = _configuration_from_environment()
    first["SCHEMA_EXTENSIONS"]["BEHAVIORS"]["show-snackbar"]["ATTRIBUTES"]["tone"][
        "ENUM"
    ].append("invalid")
    second = _configuration_from_environment()
    assert second["SCHEMA_EXTENSIONS"]["BEHAVIORS"]["show-snackbar"]["ATTRIBUTES"][
        "tone"
    ]["ENUM"] == ["success", "error"]
