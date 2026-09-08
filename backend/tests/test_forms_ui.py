"""UI contract tests for the HyperTodo form and list screens.

Also the home of the assertion helpers the other UI modules import: contrast
maths and the standard-library PNG reader.
"""

import re
import struct
import zlib
from collections import Counter
from pathlib import Path
from typing import NamedTuple
from xml.etree import ElementTree

import pytest
from django.contrib.staticfiles import finders
from django.test import Client
from django.urls import reverse

from todo.models import Category, Task

pytestmark = pytest.mark.django_db
ICON_DIRECTORY = Path(__file__).resolve().parents[1] / "todo/static/todo/icons"
ICON_FILES = sorted(path.name for path in ICON_DIRECTORY.glob("*.png"))
assert ICON_FILES, f"no icons under {ICON_DIRECTORY}"
MEDIA_TYPE = "application/vnd.hyperview+xml"
NS = {
    "hv": "https://hyperview.org/hyperview",
    "app": "https://hypertodo.app/components",
}
STYLE_ATTRIBUTES = (
    "style",
    "field-style",
    "field-text-style",
    "modal-style",
    "modal-overlay-style",
    "modal-text-style",
    "href-style",
    "content-container-style",
)


def assert_hxml(response, *, status=200):
    """Assert a response is parseable UTF-8 Hyperview XML."""
    assert response.status_code == status
    assert response.headers["Content-Type"] in {
        f"{MEDIA_TYPE}; charset=utf-8",
        "application/vnd.hyperview_fragment+xml; charset=utf-8",
    }
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


def style_ids(root):
    """Collect every style id referenced by a subtree."""
    used = set()
    for element in root.iter():
        for attribute in STYLE_ATTRIBUTES:
            used.update((element.attrib.get(attribute) or "").split())
    return used


def declared_ids(root):
    """Collect every style id declared by a screen stylesheet."""
    return {node.attrib["id"] for node in root.findall(".//hv:styles/hv:style", NS)}


def style_by_id(root, style_id):
    """Return one declared style rule by id."""
    node = root.find(f".//hv:styles/hv:style[@id='{style_id}']", NS)
    assert node is not None, f"missing style {style_id}"
    return node


def _relative_luminance(color):
    """Return the WCAG relative luminance of a #RRGGBB colour."""
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def over(colour, backdrop, alpha):
    """Return the #RRGGBB a colour composites to when drawn at alpha on a backdrop.

    Hyperview's press feedback is opacity, not a colour swap, so the only way to
    check a pressed state's contrast is to composite it first.
    """
    top, bottom = (
        [int(value[index : index + 2], 16) for index in (1, 3, 5)]
        for value in (colour, backdrop)
    )
    return "#" + "".join(
        f"{round(alpha * front + (1 - alpha) * back):02X}"
        for front, back in zip(top, bottom, strict=True)
    )


def contrast_ratio(foreground, background):
    """Return the WCAG contrast ratio between two #RRGGBB colours."""
    lighter, darker = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


class PngIcon(NamedTuple):
    """The parts of an icon PNG this suite makes assertions about."""

    width: int
    height: int
    bit_depth: int
    colour_type: int
    colour: str


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_CHANNELS = {2: 3, 6: 4}  # truecolour, truecolour + alpha


def _unfilter(raw, height, stride, bpp):
    """Undo the per-scanline filters of a decompressed PNG image (spec 9.2)."""
    pixels, previous, offset = bytearray(), bytearray(stride), 0
    for _ in range(height):
        method = raw[offset]
        line = bytearray(raw[offset + 1 : offset + 1 + stride])
        offset += 1 + stride
        for index in range(stride):
            left = line[index - bpp] if index >= bpp else 0
            up = previous[index]
            up_left = previous[index - bpp] if index >= bpp else 0
            if method == 1:
                line[index] = (line[index] + left) & 0xFF
            elif method == 2:
                line[index] = (line[index] + up) & 0xFF
            elif method == 3:
                line[index] = (line[index] + (left + up) // 2) & 0xFF
            elif method == 4:
                estimate = left + up - up_left
                deltas = (
                    abs(estimate - left),
                    abs(estimate - up),
                    abs(estimate - up_left),
                )
                line[index] = (
                    line[index] + (left, up, up_left)[deltas.index(min(deltas))]
                ) & 0xFF
            elif method:
                raise AssertionError(f"unknown PNG filter {method}")
        pixels += line
        previous = line
    return pixels


def read_png_icon(path):
    """Decode a PNG with the standard library and report the colour it ships in.

    Only zlib is needed: parse IHDR, inflate the IDAT stream, undo the scanline
    filters. Every icon in this app is one flat glyph on transparency, so colour
    is the most common fully opaque pixel — the colour the file actually renders
    in, which is the thing a test asserting a literal never checks.
    """
    assert path is not None, "icon is not on the static files path"
    data = Path(path).read_bytes()
    assert data[:8] == _PNG_SIGNATURE, f"{path} is not a PNG"

    header, compressed, offset = None, bytearray(), len(_PNG_SIGNATURE)
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        body = data[offset + 8 : offset + 8 + length]
        if data[offset + 4 : offset + 8] == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif data[offset + 4 : offset + 8] == b"IDAT":
            compressed += body
        offset += length + 12  # length + type + data + crc

    assert header is not None, f"{path} has no IHDR"
    width, height, bit_depth, colour_type, _, _, interlace = header
    assert bit_depth == 8, f"{path}: only 8-bit samples are decoded"
    assert not interlace, f"{path}: only non-interlaced PNGs are decoded"
    assert colour_type in _PNG_CHANNELS, f"{path}: unsupported colour type"

    channels = _PNG_CHANNELS[colour_type]
    pixels = _unfilter(
        zlib.decompress(bytes(compressed)), height, width * channels, channels
    )
    opaque = Counter(
        bytes(pixels[index : index + 3])
        for index in range(0, len(pixels), channels)
        if channels == 3 or pixels[index + 3] == 0xFF
    )
    assert opaque, f"{path} has no fully opaque pixel"

    colour = opaque.most_common(1)[0][0].hex().upper()
    return PngIcon(width, height, bit_depth, colour_type, f"#{colour}")


@pytest.mark.parametrize("icon", ICON_FILES)
def test_every_icon_ships_at_the_one_size_and_format_the_app_draws(icon):
    # One convention for the whole directory: 72x72, 8-bit, RGBA. The nav icons
    # used to sit at 24 and the nav draws them at ~24pt, so every 2x and 3x phone
    # upscaled them into a soft glyph while nothing here complained. Exporting all
    # fifteen at 72 keeps 3x sharp, and pinning the size for the directory rather
    # than per icon means the next one added at 24 fails on arrival.
    source = read_png_icon(finders.find(f"todo/icons/{icon}"))

    assert (source.width, source.height) == (72, 72)
    assert (source.bit_depth, source.colour_type) == (8, 6)


@pytest.mark.parametrize(
    "route", ["todo:dashboard", "todo:tasks", "todo:categories", "todo:settings"]
)
def test_the_bottom_navigation_labels_are_readable_wherever_the_bar_is_hosted(
    route, user
):
    # `nav-label-active` composes over `nav-label`, so the label of the tab you are
    # standing on inherits fontSize 10 and overrides only the colour: 10px is normal
    # text and owes 4.5:1. #278CFF on the bar's own #F7F8FC is 3.15:1, which made the
    # one label that says WHERE YOU ARE the least readable of the five. The bar is a
    # single include, but the stylesheet is copied per screen, so scan every screen
    # that hosts it rather than one.
    client = Client()
    client.force_login(user)

    root = assert_hxml(client.get(reverse(route)))
    backdrop = style_by_id(root, "bottom-navigation-style").attrib["backgroundColor"]

    assert int(style_by_id(root, "nav-label").attrib["fontSize"]) < 18
    for style_id in ("nav-label", "nav-label-active"):
        colour = style_by_id(root, style_id).attrib["color"]
        assert contrast_ratio(colour, backdrop) >= 4.5, (
            f"{route} {style_id}: {colour} on {backdrop}"
        )


@pytest.mark.parametrize(
    ("route", "payload"),
    [
        ("todo:task-new", {"title": ""}),
        ("todo:category-new", {"name": "", "color": "lavender"}),
    ],
)
def test_form_fragments_only_use_styles_declared_by_their_screen(user, route, payload):
    client = csrf_client()
    client.force_login(user)
    screen = client.get(reverse(route))
    screen_root = assert_hxml(screen)
    declared = declared_ids(screen_root)

    assert style_ids(screen_root) <= declared

    fragment = client.post(
        reverse(route), {**payload, "csrfmiddlewaretoken": token_from(screen)}
    )
    fragment_root = assert_hxml(fragment, status=422)

    assert style_ids(fragment_root) <= declared


def test_task_form_category_uses_a_collapsed_picker_field(user):
    client = Client()
    client.force_login(user)
    work = Category.objects.create(
        user=user, name="Work", color=Category.Color.LAVENDER
    )

    root = assert_hxml(client.get(reverse("todo:task-new")))

    assert root.find(".//hv:select-single[@name='category']", NS) is None
    picker = root.find(".//hv:picker-field[@name='category']", NS)
    assert picker is not None
    items = picker.findall("./hv:picker-item", NS)
    assert [item.attrib["label"] for item in items] == ["No category", "Work"]
    assert items[0].attrib["value"] == ""
    assert items[1].attrib["value"] == str(work.pk)
    assert picker.attrib["field-style"].startswith("picker-box")
    assert picker.attrib["modal-style"] == "date-modal"
    assert picker.attrib["modal-overlay-style"] == "date-modal-overlay"
    assert picker.attrib["modal-text-style"] == "date-modal-action"
    assert picker.attrib["value"] == ""

    task = Task.objects.create(user=user, category=work, title="Ship it")
    edit_root = assert_hxml(client.get(reverse("todo:task-edit", args=[task.pk])))
    edit_picker = edit_root.find(".//hv:picker-field[@name='category']", NS)
    assert edit_picker is not None
    assert edit_picker.attrib["value"] == str(work.pk)


def test_picker_field_submits_the_same_category_field_name(user):
    client = csrf_client()
    client.force_login(user)
    work = Category.objects.create(
        user=user, name="Work", color=Category.Color.LAVENDER
    )
    token = token_from(client.get(reverse("todo:task-new")))

    assert_hxml(
        client.post(
            reverse("todo:task-new"),
            {
                "title": "Ship",
                "category": str(work.pk),
                "due_date": "2026-09-15",
                "due_time": "09:30",
                "csrfmiddlewaretoken": token,
            },
        ),
        status=201,
    )
    assert Task.objects.get(title="Ship").category_id == work.pk

    assert_hxml(
        client.post(
            reverse("todo:task-new"),
            {"title": "Loose", "category": "", "csrfmiddlewaretoken": token},
        ),
        status=201,
    )
    assert Task.objects.get(title="Loose").category_id is None


def test_task_form_fields_are_legible_and_reachable(user):
    client = Client()
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:task-new")))

    field = style_by_id(root, "field")
    assert field.attrib["fontSize"] == "16"
    assert field.attrib["color"] == "#161A35"
    assert int(field.attrib["minHeight"]) >= 48

    button_text = style_by_id(root, "button-text")
    assert int(button_text.attrib["fontSize"]) >= 19
    assert button_text.attrib["fontWeight"] == "700"

    # Only <text-field> forwards accessibilityLabel to a TextInput, which exposes its
    # value on a separate accessibility channel. On <date-field> the attribute lands
    # on the touchable box and REPLACES the announced value; on <picker-field> the
    # client never reads it at all (naming there is derived from the id).
    text_fields = [
        node
        for node in root.findall(".//hv:text-field", NS)
        if node.attrib.get("name") != "csrfmiddlewaretoken"
    ]
    assert len(text_fields) == 3
    for node in text_fields:
        assert node.attrib.get("accessibilityLabel"), node.attrib.get("name")
    for tag in ("date-field", "picker-field"):
        for node in root.findall(f".//hv:{tag}", NS):
            assert "accessibilityLabel" not in node.attrib

    due_date = root.find(".//hv:date-field[@name='due_date']", NS)
    assert due_date is not None
    assert due_date.attrib["placeholderTextColor"] == "#6A6F86"
    # A numeric pattern since the app shipped Spanish: the date field renders its
    # label with dayjs in the CLIENT bundle, which registers no `es` locale, so
    # "MMM" kept emitting English month abbreviations inside a Spanish screen no
    # matter what the server sent. Translating the pattern cannot fix that;
    # dropping the month name can.
    assert due_date.attrib["label-format"] == "DD/MM/YYYY"
    assert due_date.attrib["field-style"] == "field"

    content = root.find(".//hv:view[@id='screen-content']", NS)
    assert content is not None
    assert content.attrib["content-container-style"] == "screen-content-inner"
    assert "padding" not in style_by_id(root, "screen-content-style").attrib


def test_category_form_reports_field_level_errors(user):
    client = csrf_client()
    client.force_login(user)
    Category.objects.create(user=user, name="Work", color=Category.Color.LAVENDER)
    token = token_from(client.get(reverse("todo:category-new")))

    root = assert_hxml(
        client.post(
            reverse("todo:category-new"),
            {"name": "Work", "color": "lavender", "csrfmiddlewaretoken": token},
        ),
        status=422,
    )

    name_error = root.find(".//hv:text[@style='field-error']", NS)
    assert name_error is not None
    assert name_error.text == "A category with this name already exists."
    name = root.find(".//hv:text-field[@name='name']", NS)
    assert name is not None
    assert "field-invalid" in name.attrib["style"]
    assert name.attrib["accessibilityLabel"] == "Category name"
    summary = root.find(".//hv:view[@style='error-card']/hv:text", NS)
    assert summary is not None
    assert summary.text == "Review the fields marked in red."


def test_colour_options_are_a_compact_row_with_non_colour_selection_state(user):
    client = Client()
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:category-new")))

    select = style_by_id(root, "color-select")
    assert select.attrib["flexDirection"] == "row"
    assert select.attrib["flexWrap"] == "wrap"

    option = style_by_id(root, "color-option")
    assert int(option.attrib["minHeight"]) >= 44

    selected = root.find(
        ".//hv:styles/hv:style[@id='color-option-text']"
        "/hv:modifier[@selected='true']/hv:style",
        NS,
    )
    assert selected is not None
    assert selected.attrib["fontWeight"] == "700"


def test_task_list_meets_touch_and_contrast_minimums(user):
    client = Client()
    client.force_login(user)

    root = assert_hxml(client.get(reverse("todo:tasks"), {"status": "active"}))

    assert int(style_by_id(root, "chip").attrib["minHeight"]) >= 44
    assert style_by_id(root, "meta").attrib["color"] == "#6A6F86"

    # 13px is normal text under WCAG, so the selected chip needs 4.5:1 on the
    # selected fill just like the unselected ones do on theirs.
    assert int(style_by_id(root, "chip-text").attrib["fontSize"]) < 19
    for style_id, background_id in (
        ("chip-text", "chip"),
        ("chip-text", "chip-active"),
        ("chip-text-active", "chip-active"),
    ):
        color = style_by_id(root, style_id).attrib["color"]
        background = style_by_id(root, background_id).attrib["backgroundColor"]
        assert contrast_ratio(color, background) >= 4.5, style_id

    active = root.find(".//hv:view[@id='filter-active']/hv:text", NS)
    inactive = root.find(".//hv:view[@id='filter-all']/hv:text", NS)
    assert active is not None
    assert "chip-text-active" in active.attrib["style"]
    assert inactive is not None
    assert "chip-text-active" not in inactive.attrib["style"]

    empty = root.find(".//hv:item[@key='task-empty']", NS)
    assert empty is not None
    assert empty.find(".//hv:text[@style='empty-title']", NS) is not None
    assert empty.find(".//hv:text[@style='empty-copy']", NS) is not None


def test_category_cards_keep_text_off_the_pastel_fill(user):
    client = Client()
    client.force_login(user)
    for index, color in enumerate(Category.Color):
        Category.objects.create(user=user, name=f"Cat {index}", color=color)

    root = assert_hxml(client.get(reverse("todo:categories")))

    items = [
        node
        for node in root.findall(".//hv:item", NS)
        if node.attrib["key"].startswith("category-")
    ]
    assert len(items) == len(Category.Color)
    colors = set()
    for item in items:
        assert item.attrib["style"] == "card"
        swatch_style = next(
            node.attrib["style"]
            for node in item.iter()
            if node.attrib.get("style", "").startswith("swatch ")
        )
        colors.add(swatch_style.split()[1])
    assert colors == {color.value for color in Category.Color}

    assert style_by_id(root, "meta").attrib["color"] == "#6A6F86"
    assert int(style_by_id(root, "action-button").attrib["minHeight"]) >= 44
    primary_text = style_by_id(root, "primary-text")
    assert int(primary_text.attrib["fontSize"]) >= 19
    assert primary_text.attrib["fontWeight"] == "700"

    card_background = style_by_id(root, "card").attrib["backgroundColor"]
    for style_id in ("action", "danger"):
        label = style_by_id(root, style_id)
        assert int(label.attrib["fontSize"]) < 19, style_id
        assert contrast_ratio(label.attrib["color"], card_background) >= 4.5, style_id


@pytest.mark.parametrize("route", ["todo:login", "todo:task-new", "todo:category-new"])
def test_white_on_blue_labels_are_only_used_at_large_bold_sizes(user, route):
    client = Client()
    client.force_login(user)

    root = assert_hxml(client.get(reverse(route)))

    button = style_by_id(root, "button")
    button_text = style_by_id(root, "button-text")

    assert button.attrib["backgroundColor"] == "#278CFF"
    assert button_text.attrib["color"] == "#FFFFFF"
    # White on the primary blue is 3.34:1, which only clears WCAG AA as large text.
    assert contrast_ratio("#FFFFFF", "#278CFF") < 4.5
    assert int(button_text.attrib["fontSize"]) >= 19
    assert button_text.attrib["fontWeight"] == "700"


def test_the_session_expired_escape_button_stays_readable_on_blue():
    # The one control on the screen a dead session lands on, white on #278CFF.
    # Hyperview styles do not cascade, so an unset fontSize is React Native's
    # 14px default, not the sibling screens' 19.
    root = assert_hxml(Client().get(reverse("todo:tasks")), status=401)

    button_text = style_by_id(root, "button-text")

    assert style_by_id(root, "button").attrib["backgroundColor"] == "#278CFF"
    assert button_text.attrib["color"] == "#FFFFFF"
    assert int(button_text.attrib["fontSize"]) >= 19
    assert button_text.attrib["fontWeight"] == "700"


@pytest.mark.parametrize("route", ["todo:tasks", "todo:categories"])
@pytest.mark.parametrize("populated", [False, True])
def test_list_partials_only_use_styles_declared_by_their_screen(user, route, populated):
    if populated:
        category = Category.objects.create(
            user=user, name="Work", color=Category.Color.LAVENDER
        )
        Task.objects.create(user=user, category=category, title="Ship it")
    client = Client()
    client.force_login(user)

    root = assert_hxml(client.get(reverse(route)))

    assert style_ids(root) <= declared_ids(root)


def test_no_icon_ships_without_a_template_that_draws_it():
    # Both directions. An orphan is dead weight that still has to clear the 72x72
    # guard above, and a reference with no file renders an invisible <image> rather
    # than failing, so neither shows up anywhere else in this suite.
    referenced = {
        match.group(1)
        for path in (Path(__file__).resolve().parents[1] / "hyperview").rglob("*.xml")
        for match in re.finditer(r"todo/icons/([\w-]+\.png)", path.read_text())
    }

    assert set(ICON_FILES) == referenced, (
        f"orphaned files: {sorted(set(ICON_FILES) - referenced)}; "
        f"missing files: {sorted(referenced - set(ICON_FILES))}"
    )


# Every screen that draws a full-width blue primary button, with the style ids of
# the fill and of the label sitting on it.
PRIMARY_BUTTONS = (
    ("login", "button", "button-text"),
    ("session expired", "button", "button-text"),
    ("error", "error-button", "error-button-text"),
    ("settings", "button", "button-text"),
    ("task form", "button", "button-text"),
    ("category form", "button", "button-text"),
    ("categories", "primary", "primary-text"),
)


def primary_button_screens(user):
    """Fetch every screen in PRIMARY_BUTTONS, in that order."""
    anonymous, client = Client(), Client()
    client.force_login(user)
    return (
        anonymous.get(reverse("todo:login")),
        anonymous.get(reverse("todo:dashboard")),  # 401 -> screens/session_expired.xml
        client.post(reverse("todo:dashboard")),  # 405 -> screens/error.xml
        client.get(reverse("todo:settings")),
        client.get(reverse("todo:task-new")),
        client.get(reverse("todo:category-new")),
        client.get(reverse("todo:categories")),
    )


def test_every_primary_button_stays_readable_while_it_is_held(user):
    # A styled descendant with no pressed rule of its own falls back to opacity 0.7
    # (services/index.ts:33-41), and `pressed` reaches every descendant. With no
    # rules at all a #278CFF button composites to #68AEFF over the card and its
    # white label to #D2E6FF inside that: 1.8:1. Darkening only the fill is not
    # enough either -- the label still dims, to 2.9:1 -- so both layers declare one.
    # Not momentary: "Return home" is a reload over the network that produced the
    # error screen in the first place.
    for response, (label, fill_id, text_id) in zip(
        primary_button_screens(user), PRIMARY_BUTTONS, strict=True
    ):
        root = ElementTree.fromstring(response.content)
        fill, text = style_by_id(root, fill_id), style_by_id(root, text_id)
        pressed_fill = fill.find("./hv:modifier[@pressed='true']/hv:style", NS)
        pressed_text = text.find("./hv:modifier[@pressed='true']/hv:style", NS)

        assert pressed_fill is not None, f"{label}: the fill dims to #68AEFF"
        assert pressed_text is not None, f"{label}: the label dims inside the fill"
        held = pressed_fill.attrib["backgroundColor"]
        assert held != fill.attrib["backgroundColor"], (
            f"{label}: suppressing the fallback removed the press feedback entirely"
        )
        assert int(text.attrib["fontSize"]) >= 19, label
        assert text.attrib["fontWeight"] == "700", label
        assert contrast_ratio(pressed_text.attrib["color"], held) >= 3, label


def test_text_drawn_on_a_category_fill_clears_aa_on_every_colour(user):
    # The five fills are declared once per screen and the ink on them is a separate
    # literal, so a colour added to the model drifts silently. Green #3B9B70 is the
    # binding constraint on all five and nothing lighter than roughly #1E2338
    # survives it: the dashboard chip shipped #20243D at 4.42:1, so a user who names
    # a category green and gives it one active task reads that chip below AA.
    client = Client()
    client.force_login(user)
    for index, color in enumerate(Category.Color):
        category = Category.objects.create(user=user, name=f"Cat {index}", color=color)
        Task.objects.create(user=user, category=category, title=f"Task {index}")

    for route, ink_id in (("todo:dashboard", "chip-text"),):
        root = assert_hxml(client.get(reverse(route)))
        ink = style_by_id(root, ink_id).attrib["color"]
        assert int(style_by_id(root, ink_id).attrib["fontSize"]) < 19, ink_id
        for color in Category.Color:
            fill = style_by_id(root, color.value).attrib["backgroundColor"]
            assert contrast_ratio(ink, fill) >= 4.5, (
                f"{route} {ink_id} on {color.value}"
            )


@pytest.mark.parametrize("route", ["todo:tasks", "todo:categories"])
def test_the_pagination_spinner_is_visible_against_the_canvas_it_spins_on(user, route):
    # HvSpinner falls back to #8d9494 (hv-spinner/index.tsx:9), 2.91:1 on the
    # #F7F8FC canvas -- under the 3:1 that 1.4.11 asks of a graphical object which
    # carries meaning. A user on a slow connection scrolls to the end of the list and
    # cannot see that more is loading.
    client = Client()
    client.force_login(user)

    root = assert_hxml(client.get(reverse(route)))
    canvas = style_by_id(root, "screen").attrib["backgroundColor"]
    spinners = root.findall(".//hv:spinner", NS)

    assert spinners
    for spinner in spinners:
        colour = spinner.attrib.get("color")
        assert colour, "no colour declared, so the client default #8d9494 is used"
        assert contrast_ratio(colour, canvas) >= 3, f"{route}: {colour} on {canvas}"


def swipe_client(user):
    """Sign a client in and make it announce a version past the capability gate."""
    client = Client(headers={"x-app-version": "1.1.0"})
    client.force_login(user)
    return client


def test_a_category_card_is_painted_by_its_own_colour_again(user):
    # The fill moves onto the swipe-row itself, because SwipeRow spreads
    # createStyleProp FIRST into the outer View and its content layer sets no
    # background of its own. The padding cannot come with it: the action tray is
    # `position:absolute top:0 bottom:0 right:0` inside that same View and Yoga
    # insets absolute children from the parent's PADDING box, so padding on the root
    # would leave a coloured gutter around the tray. screens/tasks.xml:22-23 already
    # splits it exactly this way.
    client = swipe_client(user)
    for index, color in enumerate(Category.Color):
        Category.objects.create(user=user, name=f"Cat {index}", color=color)

    root = assert_hxml(client.get(reverse("todo:categories")))
    rows = root.findall(".//app:swipe-row", NS)

    assert len(rows) == len(Category.Color)
    assert {row.attrib["style"].split()[1] for row in rows} == {
        color.value for color in Category.Color
    }
    for row in rows:
        assert row.attrib["style"].split()[0] == "card-fill"
        inner = row.find("./hv:view[@style='card-inner']", NS)
        assert inner is not None
        assert inner.find("./hv:text[@style='name-on-fill']", NS) is not None
        assert inner.find("./hv:text[@style='meta-on-fill']", NS) is not None

    fill_style = style_by_id(root, "card-fill")
    assert fill_style.attrib["overflow"] == "hidden"
    assert not [name for name in fill_style.attrib if name.startswith("padding")], (
        "padding on the swipe-row leaves a coloured gutter around the action tray"
    )
    assert int(style_by_id(root, "card-inner").attrib["padding"]) == 20

    # One ink for both lines and all five fills. Green #3B9B70 is the binding
    # constraint at 4.95:1 and nothing lighter than roughly #1E2338 survives it, so
    # there are no per-colour text tokens to keep in step.
    # The meta line is normal text at 13px, so 4.5:1 is its real floor rather than
    # the 3:1 the 20/700 name could have claimed as large text; both are held to it.
    assert int(style_by_id(root, "meta-on-fill").attrib["fontSize"]) < 19
    for style_id in ("name", "meta-on-fill"):
        ink = style_by_id(root, style_id).attrib["color"]
        for color in Category.Color:
            fill = style_by_id(root, color.value).attrib["backgroundColor"]
            assert contrast_ratio(ink, fill) >= 4.5, f"{style_id} on {color.value}"

    assert style_ids(root) <= declared_ids(root)


def test_a_category_row_declares_the_two_actions_it_actually_has(user):
    client = swipe_client(user)
    category = Category.objects.create(
        user=user, name="Work", color=Category.Color.LAVENDER
    )

    root = assert_hxml(client.get(reverse("todo:categories")))
    row = root.find(".//app:swipe-row", NS)
    actions = row.findall("./app:swipe-action", NS)

    assert row.attrib["id"] == f"category-swipe-{category.pk}"
    assert [action.attrib["label"] for action in actions] == ["Edit", "Delete"]
    assert actions[0].attrib == {
        "href": f"/hv/categories/{category.pk}/edit/",
        "action": "navigate",
        "verb": "get",
        "label": "Edit",
        "a11y-label": "Edit category",
        "tone": "primary",
    }
    assert actions[1].attrib == {
        "href": f"/hv/categories/{category.pk}/delete/",
        "action": "replace",
        "verb": "post",
        "label": "Delete",
        "a11y-label": "Delete category",
        "tone": "danger",
        # delete_category is a plain delete and Task.category is SET_NULL, so the
        # task row's "cannot be undone" would be a lie here.
        "confirm-title": "Delete category?",
        "confirm-body": "Its tasks stay, without a category.",
        "confirm-label": "Delete",
    }
    # A POST action needs the token, and the row has to sit inside the form.
    assert (
        root.find(".//hv:form//app:swipe-row", NS) is not None
        and root.find(".//hv:form/hv:text-field[@name='csrfmiddlewaretoken']", NS)
        is not None
    )


def test_a_client_that_predates_the_component_still_gets_the_old_category_card(user):
    # A backend deploy reaches every installed binary at once. An old bundle handed
    # the new markup draws no row at all for <app:swipe-action> and, worse, would
    # have shown a "Complete" button that does nothing if the actions had stayed
    # attributes -- SwipeRow.update() returns silently on a missing href.
    client = Client(headers={"x-app-version": "1.0.0"})
    client.force_login(user)
    Category.objects.create(user=user, name="Work", color=Category.Color.LAVENDER)

    root = assert_hxml(client.get(reverse("todo:categories")))

    assert root.find(".//app:swipe-row", NS) is None
    item = root.find(".//hv:item[@style='card']", NS)
    assert item is not None
    assert item.find(".//hv:view[@style='swatch lavender']", NS) is not None
    assert item.find(".//hv:text[@style='meta']", NS) is not None
    assert style_ids(root) <= declared_ids(root)
