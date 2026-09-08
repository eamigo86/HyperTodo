"""Avatar upload: the transport, the decode boundary, and what lands on disk.

No binary fixture is committed. Every image below is built with Pillow in the
test process, so the bytes under test are exactly the bytes the assertions
describe and nothing has to be trusted from a file nobody can read in a diff.
"""

import ast
import os
import re
import struct
import zlib
from base64 import b64encode
from io import BytesIO
from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse
from PIL import Image

from tests.test_forms_ui import (
    NS,
    assert_hxml,
    contrast_ratio,
    declared_ids,
    style_by_id,
    style_ids,
    token_from,
)
from todo import urls, views
from todo.forms import MAX_AVATAR_BYTES, NOT_AN_IMAGE, TOO_LARGE, AvatarForm
from todo.models import Profile
from todo.services import store_avatar

pytestmark = pytest.mark.django_db


def test_media_is_configured_for_user_uploads():
    # MEDIA_URL without a leading slash is a relative url: <image source> resolves
    # it against the SCREEN url, so /hv/settings/ would ask for
    # /hv/media/avatars/... and 404. Django normalises it the way it already does
    # for STATIC_URL, and this pins that it stays normalised.
    assert settings.MEDIA_URL == "/media/"
    assert Path(settings.MEDIA_ROOT).is_absolute()


def test_every_test_writes_uploads_outside_the_repository(tmp_path_factory):
    # The isolation fixture is itself under test. test_fragment_contract.py fires a
    # real POST at every scanned href, so the avatar endpoint is exercised from a
    # second module the moment it appears in a template; without a suite-wide
    # redirect those files land in the working tree.
    root = Path(settings.MEDIA_ROOT)
    assert root.is_relative_to(tmp_path_factory.getbasetemp()), (
        f"MEDIA_ROOT is {root}, which is not the pytest tmp tree"
    )


def jpeg(size=(64, 64), colour=(255, 255, 255), *, exif=None):
    """Encode one JPEG, optionally carrying an EXIF block."""
    image = Image.new("RGB", size, colour)
    image.paste(Image.new("RGB", (16, 16), (255, 0, 0)), (0, 0))
    buffer = BytesIO()
    image.save(buffer, "JPEG", **({"exif": exif(image)} if exif else {}))
    return buffer.getvalue()


def phone_exif(image):
    """Build the EXIF a phone camera writes: orientation, make, and GPS."""
    exif = image.getexif()
    exif[274] = 6  # Orientation: rotate 90 degrees clockwise to display.
    exif[271] = "ACME Phone"
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (40.0, 24.0, 0.0)
    gps[3], gps[4] = "W", (3.0, 42.0, 0.0)
    return exif


def png(size=(64, 64), colour=(255, 0, 0, 0)):
    """Encode one PNG, transparent by default."""
    buffer = BytesIO()
    Image.new("RGBA", size, colour).save(buffer, "PNG")
    return buffer.getvalue()


def _with_declared_size(raw, width, height):
    """Rewrite a PNG's IHDR so it CLAIMS a size it never has to allocate."""
    header = struct.pack(">II", width, height) + raw[24:29]
    crc = zlib.crc32(b"IHDR" + header)
    return raw[:16] + header + struct.pack(">I", crc) + raw[33:]


def submit(raw):
    """Run raw image bytes through the form the way the client posts them."""
    return AvatarForm({"avatar_data": b64encode(raw).decode()})


def rejection(raw):
    """Return the single error the form raised for these bytes."""
    form = submit(raw)
    assert not form.is_valid()
    return form.errors["avatar_data"][0]


def normalised(raw):
    """Return the stored image the form produced for these bytes."""
    form = submit(raw)
    assert form.is_valid(), form.errors
    return form.cleaned_data["avatar_data"]


def test_a_photo_is_re_encoded_to_one_fixed_square_jpeg():
    stored = normalised(jpeg((300, 200)))

    image = Image.open(BytesIO(stored))
    assert (image.format, image.mode, image.size) == ("JPEG", "RGB", (256, 256))


def test_a_phone_photos_exif_never_reaches_storage():
    # Not decoration: a camera roll photo carries GPS coordinates, the camera make
    # and the capture time, and the avatar url is public. exif_transpose clears the
    # Orientation tag ONLY -- measured on Pillow 12.3.0, GPSInfo and Make survive it
    # intact -- so what actually strips them is re-encoding without an `exif=`
    # kwarg. That is a Pillow behaviour, not a documented contract, so the marker is
    # asserted directly rather than trusted.
    source = jpeg(exif=phone_exif)
    assert b"Exif\x00\x00" in source
    assert Image.open(BytesIO(source)).getexif().get_ifd(0x8825)

    stored = normalised(source)

    assert b"Exif\x00\x00" not in stored
    assert not dict(Image.open(BytesIO(stored)).getexif())


def test_a_photo_is_rotated_the_way_the_camera_meant_it_to_be_seen():
    # Orientation 6 means "rotate 90 clockwise to display", so the red block in the
    # source's top-left belongs in the stored image's top-RIGHT. Without
    # exif_transpose it stays top-left and every iPhone portrait lands sideways.
    stored = Image.open(BytesIO(normalised(jpeg(exif=phone_exif))))

    assert stored.getpixel((250, 6))[0] > 200
    assert stored.getpixel((250, 6))[1] < 80
    assert min(stored.getpixel((6, 6))) > 200


def test_transparency_is_flattened_onto_white_and_not_onto_black():
    # convert("RGB") composites alpha onto BLACK, so a transparent PNG would land as
    # a black square inside a white disc. The fresh canvas is the fix.
    stored = Image.open(BytesIO(normalised(png())))

    assert min(stored.getpixel((128, 128))) > 200


def test_a_renamed_shell_script_is_not_an_image():
    assert rejection(b"#!/bin/sh\necho pwned\n") == NOT_AN_IMAGE


def test_a_renamed_mach_o_executable_is_not_an_image():
    assert rejection(b"\xcf\xfa\xed\xfe" + b"\x00" * 512) == NOT_AN_IMAGE


def test_a_payload_that_is_not_base64_at_all_is_not_an_image():
    form = AvatarForm({"avatar_data": "not base64 at all!!"})

    assert not form.is_valid()
    assert form.errors["avatar_data"] == [NOT_AN_IMAGE]


def test_a_payload_over_the_byte_ceiling_is_refused_before_it_is_decoded():
    error = rejection(os.urandom(700_000))

    assert error == TOO_LARGE
    # Distinct copy on purpose: "too large" and "not an image" are different
    # problems with different fixes, and one message for both hides which guard bit.
    assert error != NOT_AN_IMAGE


def test_a_pixel_bomb_is_refused_even_though_its_file_is_small():
    # Pillow's own MAX_IMAGE_PIXELS only WARNS between 1x and 2x the limit
    # (Image._decompression_bomb_check), so 25 megapixels sails past it and
    # allocates ~100MB on decode. A flat PNG compresses to a few KB, which is what
    # makes the byte ceiling useless here -- asserted, so the guards cannot swap.
    bomb = png((5000, 5000), (0, 0, 0, 255))
    assert len(bomb) < MAX_AVATAR_BYTES

    assert rejection(bomb) == TOO_LARGE


def test_a_pixel_bomb_over_pillows_own_ceiling_is_refused_and_does_not_crash():
    # Above 2x Image.MAX_IMAGE_PIXELS, Pillow stops warning and RAISES
    # DecompressionBombError from Image.open itself -- before the MAX_SOURCE_EDGE
    # guard below it ever runs. That error subclasses Exception, NOT OSError, so
    # without its own arm it escapes clean_avatar_data, escapes form.is_valid(),
    # and the endpoint answers a plain-HTML 500 that `replace` cannot parse.
    # The header is rewritten rather than rendered: Image.open reads IHDR only, so
    # the declared size is what trips the check and no 200MB buffer is allocated.
    bomb = _with_declared_size(png((1, 1)), 400_000, 500)
    assert 400_000 * 500 > 2 * Image.MAX_IMAGE_PIXELS
    assert len(bomb) < MAX_AVATAR_BYTES

    assert rejection(bomb) == TOO_LARGE


def test_an_exotic_decoder_is_never_reached():
    # The client only ever posts JPEG. Everything else in Pillow's 43-format OPEN
    # registry is attack surface this app has no use for.
    buffer = BytesIO()
    Image.new("RGB", (64, 64)).save(buffer, "BMP")

    assert rejection(buffer.getvalue()) == NOT_AN_IMAGE


# --- endpoint -----------------------------------------------------------------

CURRENT_CLIENT = {"x-app-version": "1.2.0"}


def signed_in(user, **headers):
    """Return a CSRF-enforcing client already holding a session for one user."""
    client = Client(enforce_csrf_checks=True, headers=headers)
    client.force_login(user)
    return client


def post_avatar(client, raw, *, token):
    """Save the settings form carrying one picked photo.

    /hv/avatar/ is gone: the photo is a FIELD of settings-form now, and the Save
    button is the only thing that commits it. These storage properties are
    unchanged by that move, so they are asserted through the endpoint that
    actually writes today rather than deleted with the one that used to.
    """
    return client.post(
        reverse("todo:settings"),
        {
            "first_name": "",
            "last_name": "",
            "email": "",
            "avatar_data": b64encode(raw).decode(),
            "csrfmiddlewaretoken": token,
        },
    )


def csrf_token(client):
    """Read a usable CSRF value out of the settings screen."""
    return token_from(client.get(reverse("todo:settings")))


def stored_files():
    """List every file currently under MEDIA_ROOT."""
    root = Path(settings.MEDIA_ROOT)
    return sorted(path for path in root.rglob("*") if path.is_file())


def test_a_posted_photo_is_stored_and_answered_with_a_bare_fragment(user):
    client = signed_in(user, **CURRENT_CLIENT)

    response = post_avatar(client, jpeg(), token=csrf_token(client))

    root = assert_hxml(response)
    # A `replace` reaches the client through loadElement, which raises
    # XMLRestrictedElementFound the moment doc/navigator/screen/body appears.
    assert root.tag == "{https://hyperview.org/hyperview}view"
    assert not [node for node in root.iter() if node.tag.endswith("}screen")]
    user.refresh_from_db()
    assert user.profile.avatar.name.startswith("avatars/")
    assert len(stored_files()) == 1


def test_the_stored_name_is_unguessable_so_the_url_needs_no_authentication(user):
    client = signed_in(user, **CURRENT_CLIENT)
    post_avatar(client, jpeg(), token=csrf_token(client))

    user.refresh_from_db()
    name = Path(user.profile.avatar.name).stem

    # 32 hex characters of uuid4. The filename IS the capability: <Image> would send
    # cookies (RN Android wires Fresco to the app cookie jar), but an unguessable
    # name costs no view, no url, and no cache-busting query parameter, and a fresh
    # uuid per upload busts RN's URI-keyed image cache for free.
    assert len(name) == 32
    assert int(name, 16) >= 0


def test_replacing_a_photo_deletes_the_one_it_replaced(
    user, django_capture_on_commit_callbacks
):
    client = signed_in(user, **CURRENT_CLIENT)
    token = csrf_token(client)
    post_avatar(client, jpeg(colour=(10, 10, 10)), token=token)
    user.refresh_from_db()
    first = user.profile.avatar.name

    # The cleanup is deferred to on_commit so a rolled-back transaction cannot
    # delete a file the database still names; the test suite never commits, so
    # the callbacks have to be run explicitly or this guard would pass vacuously.
    with django_capture_on_commit_callbacks(execute=True):
        post_avatar(client, jpeg(colour=(200, 200, 200)), token=token)

    user.refresh_from_db()
    assert user.profile.avatar.name != first
    # Django never deletes the file a FileField stops pointing at, so without an
    # explicit delete every re-upload leaves an orphan on disk forever.
    assert len(stored_files()) == 1


def test_a_failed_profile_save_removes_the_file_written_before_it(user, monkeypatch):
    """Compensate when FileField storage succeeds but the model save fails."""
    profile = Profile.objects.create(user=user)
    original_save = Profile.save

    def fail_with_avatar(instance, *args, **kwargs):
        if instance.pk == profile.pk and instance.avatar:
            raise RuntimeError("forced profile save failure")
        return original_save(instance, *args, **kwargs)

    monkeypatch.setattr(Profile, "save", fail_with_avatar)

    with pytest.raises(RuntimeError, match="forced profile save failure"):
        store_avatar(user=user, data=jpeg())

    profile.refresh_from_db()
    assert not profile.avatar
    assert stored_files() == []


def test_a_failed_settings_transaction_removes_the_new_avatar(user, monkeypatch):
    """Keep external storage consistent when the surrounding transaction rolls back."""
    from todo import services

    Profile.objects.create(user=user)
    original_revoke = services.revoke_biometric_token

    def fail_after_avatar(*, user):
        original_revoke(user=user)
        raise RuntimeError("forced transaction failure")

    monkeypatch.setattr(views, "revoke_biometric_token", fail_after_avatar)
    client = signed_in(user, **CURRENT_CLIENT)

    with pytest.raises(RuntimeError, match="forced transaction failure"):
        save_settings(
            client,
            token=csrf_token(client),
            avatar_data=b64encode(jpeg()).decode(),
            biometric_unlock="off",
        )

    user.refresh_from_db()
    assert not user.profile.avatar
    assert stored_files() == []


def test_one_account_cannot_touch_another_accounts_photo(user, other_user):
    owner = signed_in(user, **CURRENT_CLIENT)
    post_avatar(owner, jpeg(), token=csrf_token(owner))
    user.refresh_from_db()
    mine = user.profile.avatar.name

    intruder = signed_in(other_user, **CURRENT_CLIENT)
    post_avatar(intruder, jpeg(), token=csrf_token(intruder))

    user.refresh_from_db()
    assert user.profile.avatar.name == mine
    assert len(stored_files()) == 2


def test_a_refused_photo_answers_422_and_writes_nothing(user):
    client = signed_in(user, **CURRENT_CLIENT)

    response = post_avatar(client, b"#!/bin/sh\n", token=csrf_token(client))

    assert response.status_code == 422
    assert str(NOT_AN_IMAGE) in response.content.decode()
    assert stored_files() == []
    # Not merely 'no avatar': a refused upload must not even materialise the
    # shared preferences row, which would carry a theme and a language with it.
    assert not Profile.objects.filter(user=user).exists()


def test_an_expired_session_gets_a_fragment_and_not_the_session_expired_screen():
    # The Save POST is a `replace`, which reaches the client through loadElement
    # and raises XMLRestrictedElementFound on <screen>. A 401 owes the same shape.
    response = Client().post(reverse("todo:settings"), {"avatar_data": "x"})

    assert response.status_code == 401
    assert b"<screen" not in response.content


def test_a_method_the_save_endpoint_does_not_serve_is_refused_by_name(user):
    # Was a GET against /hv/avatar/, which only ever answered POST. The Save
    # endpoint legitimately answers both, so the same property is asserted with a
    # verb it still refuses.
    client = Client()
    client.force_login(user)

    response = client.delete(reverse("todo:settings"))

    assert response.status_code == 405
    assert response.headers["Allow"] == "GET, POST"


def test_the_pick_button_is_hidden_from_clients_that_would_do_nothing_with_it(user):
    # `pick-avatar` is a CUSTOM action. Hyperview silently ignores an action no
    # registered behavior claims, so a 1.1.0 binary would render a "Change photo"
    # row that does absolutely nothing when tapped.
    old = signed_in(user, **{"x-app-version": "1.1.0"}).get(reverse("todo:settings"))
    new = signed_in(user, **CURRENT_CLIENT).get(reverse("todo:settings"))

    assert 'action="pick-avatar"' not in old.content.decode()
    assert 'action="pick-avatar"' in new.content.decode()
    assert old.headers["Vary"].lower().count("x-app-version") == 1


def test_a_client_that_announces_nothing_is_treated_as_too_old(user):
    body = signed_in(user).get(reverse("todo:settings")).content.decode()

    assert 'action="pick-avatar"' not in body


# --- one Save, one commit -----------------------------------------------------


def save_settings(client, *, token, **fields):
    """POST the whole settings form the way the Save button serialises it."""
    payload = {"first_name": "", "last_name": "", "email": "", **fields}
    return client.post(
        reverse("todo:settings"), {**payload, "csrfmiddlewaretoken": token}
    )


def test_one_save_commits_the_name_and_the_photo_together(user):
    client = signed_in(user, **CURRENT_CLIENT)

    response = save_settings(
        client,
        token=csrf_token(client),
        first_name="Maria",
        email="maria@example.com",
        avatar_data=b64encode(jpeg()).decode(),
    )

    assert_hxml(response)
    user.refresh_from_db()
    assert (user.first_name, user.email) == ("Maria", "maria@example.com")
    assert user.profile.avatar.name.startswith("avatars/")
    assert len(stored_files()) == 1


def test_an_invalid_email_writes_nothing_and_hands_back_every_pending_edit(
    user, other_user
):
    # The whole point of the fold. Four independent writers meant a user could get
    # the photo stored and the email refused in one tap, with nothing on screen
    # saying which half had happened. One transaction, one 422, everything the
    # user did still on the screen and still pending.
    other_user.email = "taken@example.com"
    other_user.save(update_fields=("email",))
    client = signed_in(user, **CURRENT_CLIENT)
    encoded = b64encode(jpeg()).decode()

    response = save_settings(
        client,
        token=csrf_token(client),
        first_name="Maria",
        email="taken@example.com",
        avatar_data=encoded,
    )

    root = assert_hxml(response, status=422)
    user.refresh_from_db()
    assert (user.first_name, user.email) == ("", "")
    assert not Profile.objects.filter(user=user).exists()
    assert stored_files() == []

    # Everything pending comes back: the typed name, the base64 re-armed in the
    # hidden field, and the same bytes as a data: URI in the preview, so a second
    # Save after fixing the email still carries the photo.
    assert (
        root.find(".//hv:text-field[@name='first_name']", NS).attrib["value"] == "Maria"
    )
    assert (
        root.find(".//hv:text-field[@name='avatar_data']", NS).attrib["value"]
        == encoded
    )
    preview = root.find(".//hv:image[@id='avatar-preview']", NS)
    assert preview.attrib["source"] == f"data:image/jpeg;base64,{encoded}"
    assert preview.attrib["hide"] == "false"
    assert root.find(".//hv:view[@id='avatar-current']", NS).attrib["hide"] == "true"


def test_a_refused_photo_is_dropped_rather_than_re_armed_and_says_why(user):
    # Re-arming a payload that JUST failed is not preserving work, it is queueing
    # the same refusal behind the next tap. The typed name still survives.
    client = signed_in(user, **CURRENT_CLIENT)

    response = save_settings(
        client,
        token=csrf_token(client),
        first_name="Maria",
        avatar_data=b64encode(b"#!/bin/sh\nrm -rf /").decode(),
    )

    root = assert_hxml(response, status=422)
    user.refresh_from_db()
    assert not Profile.objects.filter(user=user).exists()
    assert (
        root.find(".//hv:text-field[@name='first_name']", NS).attrib["value"] == "Maria"
    )
    assert root.find(".//hv:text-field[@name='avatar_data']", NS).attrib["value"] == ""
    preview = root.find(".//hv:image[@id='avatar-preview']", NS)
    assert preview.attrib["hide"] == "true"
    assert preview.attrib["source"].startswith("data:image/png;base64,")
    # By style, not by id: an id on a <text> becomes accessibilityLabel on Android
    # (services/index.ts:161 then :81-84) and TalkBack would read the slug instead
    # of the sentence.
    assert (
        root.find(".//hv:view[@id='avatar-panel']//hv:text[@style='field-error']", NS)
    ).text == NOT_AN_IMAGE


def test_a_save_with_no_photo_at_all_is_not_read_as_a_refused_one(user):
    # An empty avatar_data is what EVERY Save posts when the user did not pick:
    # the hidden field is always in the DOM, so it always serialises. Binding the
    # AvatarForm to it would answer 422 "not an image" on every plain profile save.
    client = signed_in(user, **CURRENT_CLIENT)

    response = save_settings(
        client, token=csrf_token(client), first_name="Maria", avatar_data=""
    )

    assert_hxml(response)
    user.refresh_from_db()
    assert user.first_name == "Maria"


# --- separate defect: a version-gated body owes Vary on the version header -----


def _version_gated_views():
    """Return every ROUTED view whose body depends on the announced client version.

    Derived from the module's own call graph rather than enumerated, so an
    endpoint that starts reading a gate tomorrow is covered on arrival instead of
    when somebody remembers to add it to a list here.
    """
    module = ast.parse(Path(views.__file__).read_text())
    functions = {
        node.name: node for node in module.body if isinstance(node, ast.FunctionDef)
    }
    calls = {
        name: {
            call.func.id
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        }
        for name, node in functions.items()
    }
    gates = {"_supports_avatar_upload", "_supports_swipe_actions"}
    # Transitive closure: _avatar_context reads a gate and settings_view reads
    # _avatar_context, so settings_view depends on the header just as directly.
    reaching, changed = set(gates), True
    while changed:
        changed = False
        for name, called in calls.items():
            if name not in reaching and called & reaching:
                reaching.add(name)
                changed = True
    routed = set(re.findall(r"views\.(\w+)", Path(urls.__file__).read_text()))
    return {name: functions[name] for name in reaching & routed}


def test_every_version_dependent_response_declares_vary_on_the_version_header():
    """The defect this fold removed, pinned so it cannot come back.

    /hv/avatar/ rendered a version-dependent body through _avatar_context and was
    the only such endpoint without @vary_on_headers, while settings_view and
    category_list both declared it and the _supports_swipe_actions docstring
    states the rule outright. Any shared HTTP cache could store the ungated panel
    served to a 1.2.0 client and replay it to a 1.1.0 one, which then drew a live
    "Change photo" control whose pick-avatar action no registered behavior claims:
    a tap that does nothing, silently, with no error anywhere. That is precisely
    the rule-9 failure the gate exists to prevent.

    The endpoint is gone, so the defect is gone with it. This is the guard that
    would have caught it, written derived rather than enumerated.
    """
    gated = _version_gated_views()

    assert gated, "the derivation found nothing; it has stopped guarding anything"
    for name, node in gated.items():
        decorators = {
            getattr(getattr(d, "func", d), "id", "") for d in node.decorator_list
        }
        assert "vary_on_headers" in decorators, (
            f"{name} renders a version-dependent body without declaring Vary"
        )


# --- what the three host screens render ---------------------------------------

AVATAR_HOSTS = ("todo:dashboard", "todo:menu", "todo:settings")


def images(root):
    """Return every <image> source in a rendered tree."""
    return [
        node.attrib.get("source", "")
        for node in root.iter("{https://hyperview.org/hyperview}image")
    ]


@pytest.mark.parametrize("route", AVATAR_HOSTS)
def test_a_photo_replaces_the_initials_on_every_screen_that_shows_a_disc(user, route):
    client = signed_in(user, **CURRENT_CLIENT)
    store_avatar(user=user, data=jpeg())

    root = assert_hxml(client.get(reverse(route)))
    sources = [source for source in images(root) if "/media/" in source]

    assert len(sources) == 1, images(root)


@pytest.mark.parametrize("route", AVATAR_HOSTS)
def test_an_avatar_url_is_relative_so_it_inherits_the_screens_own_scheme(user, route):
    # The single most valuable assertion here, because the failure only reproduces
    # in production. hv-image/index.tsx:17-20 resolves `source` against the SCREEN
    # url, so a relative path inherits scheme and host for free. An absolute url
    # built with build_absolute_uri takes its scheme from request.is_secure(), and
    # app.config.ts ships NSAllowsArbitraryLoads: false -- so an http:// avatar
    # would load perfectly in development and silently fail to load on iOS release.
    client = signed_in(user, **CURRENT_CLIENT)
    store_avatar(user=user, data=jpeg())

    sources = images(assert_hxml(client.get(reverse(route))))

    assert [source for source in sources if "/media/" in source], sources
    for source in sources:
        assert not source.startswith("http"), source


@pytest.mark.parametrize("route", AVATAR_HOSTS)
def test_an_account_with_no_photo_asks_for_no_image_at_all(user, route):
    client = signed_in(user, **CURRENT_CLIENT)

    root = assert_hxml(client.get(reverse(route)))

    assert not [source for source in images(root) if "/media/" in source]
    assert root.findall(".//*[@style='avatar-initials']") or route != "todo:settings"


def hero_photo(root):
    """Return the dashboard hero disc as it renders for an account WITH a photo."""
    node = root.find(".//hv:view[@id='dashboard-hero']//hv:image", NS)
    assert node is not None, "the hero draws no photo"
    return node


def test_a_photo_disc_is_still_the_door_to_the_side_menu(user):
    # test_settings.py pins this triad on the initials branch only, so every gate
    # there stays green if the <image> loses its href, action or target -- and the
    # dashboard has no other way into the menu, for exactly the users who uploaded.
    client = signed_in(user, **CURRENT_CLIENT)
    store_avatar(user=user, data=jpeg())

    disc = hero_photo(assert_hxml(client.get(reverse("todo:dashboard"))))

    assert disc.attrib["href"] == f"{reverse('todo:menu')}?active=dashboard"
    assert disc.attrib["action"] == "replace"
    assert disc.attrib["target"] == "side-menu-host"


def test_a_photo_disc_still_dims_under_the_finger(user):
    # createStyleProp substitutes the opacity-0.7 fallback only when the element's
    # style ids contribute NO pressed rule at all (services/index.ts:33-41), and
    # hero-avatar declares one. That rule is a backgroundColor, which an opaque
    # 256x256 JPEG covers completely, so the photo branch needs a pressed rule that
    # survives being painted over. /hv/menu/ is a round trip plus a 220ms animation;
    # a control that does not react gets tapped twice.
    client = signed_in(user, **CURRENT_CLIENT)
    store_avatar(user=user, data=jpeg())

    root = assert_hxml(client.get(reverse("todo:dashboard")))
    pressed = [
        rule
        for style_id in hero_photo(root).attrib["style"].split()
        for rule in style_by_id(root, style_id).findall(
            "./hv:modifier[@pressed='true']/hv:style", NS
        )
    ]

    assert pressed, "no pressed rule at all: check the 0.7 fallback still applies"
    visible = [
        float(rule.attrib["opacity"]) for rule in pressed if "opacity" in rule.attrib
    ]
    assert visible and max(visible) < 1, (
        "every pressed rule here is hidden behind the photo; the press reads as dead"
    )


def test_the_avatar_panel_only_uses_styles_its_only_host_screen_declares(user):
    # Rule 2 of this codebase: `replace` does NOT rebuild stylesheets, so a fragment
    # may only name style ids the screen hosting it already declares. This panel has
    # exactly one host, and the 422 branch carries an extra element the 200 branch
    # does not, so both are scanned.
    client = signed_in(user, **CURRENT_CLIENT)
    screen = client.get(reverse("todo:settings"))
    declared = declared_ids(assert_hxml(screen))
    token = token_from(screen)

    for response, status in (
        (post_avatar(client, jpeg(), token=token), 200),
        (post_avatar(client, b"not an image", token=token), 422),
    ):
        assert style_ids(assert_hxml(response, status=status)) <= declared


@pytest.mark.parametrize("stored_theme", [Profile.Theme.LIGHT, Profile.Theme.DARK])
def test_the_initials_stay_readable_on_the_disc_in_both_palettes(user, stored_theme):
    Profile.objects.update_or_create(user=user, defaults={"theme": stored_theme})
    root = assert_hxml(signed_in(user).get(reverse("todo:settings")))

    ink = style_by_id(root, "avatar-initials").attrib["color"]
    disc = style_by_id(root, "avatar-disc").attrib["backgroundColor"]

    assert contrast_ratio(ink, disc) >= 4.5, f"{stored_theme}: {ink} on {disc}"


# --- the photo row, gated and ungated -----------------------------------------


def panel(user, **headers):
    """Return the avatar panel as it renders on its only host screen."""
    root = assert_hxml(signed_in(user, **headers).get(reverse("todo:settings")))
    node = root.find(".//hv:view[@id='avatar-panel']", NS)
    assert node is not None
    return root, node


def avatar_row(node):
    """Return the one row that holds the disc and the control beside it."""
    row = node.find(".//hv:view[@style='avatar-row']", NS)
    assert row is not None, "the panel is not a row"
    return row


def _parents(root):
    """Return a child -> parent map, which ElementTree does not keep."""
    return {child: parent for parent in root.iter() for child in parent}


def _closest_form(root, node):
    """Return the <form> ancestor whose data a control inside it would post."""
    parents = _parents(root)
    while node is not None:
        if node.tag == f"{{{NS['hv']}}}form":
            return node
        node = parents.get(node)
    return None


def test_the_photo_row_defers_to_the_save_button(user):
    # The fold. The photo used to have its own <form>, its own endpoint and its
    # own 422, which is four independent writers on one screen: a user who picked
    # a photo, mistyped the email and tapped Save got the photo committed and the
    # email refused, with no single point that either succeeded or failed.
    #
    # Now the pick writes a hidden field inside settings-form and nothing else.
    # The only behavior left on the control is pick-avatar: no sibling replace, no
    # href anywhere in the panel, so nothing here can reach the network on its own.
    root, node = panel(user, **CURRENT_CLIENT)
    row = avatar_row(node)
    pick = row.find("./hv:view[@style='avatar-action']", NS)

    assert [b.attrib.get("action") for b in pick.findall("./hv:behavior", NS)] == [
        "pick-avatar"
    ]
    assert not [n for n in node.iter() if n.attrib.get("href")], "the panel can post"

    field = root.find(".//hv:text-field[@name='avatar_data']", NS)
    assert field is not None
    assert field.attrib["hide"] == "true"
    assert _closest_form(root, field).attrib["id"] == "settings-form"

    # Rule 6, both directions. The preview carries the behavior's target id and NO
    # alt: react-native Image.android.js:272-276 only sets accessible=true when
    # alt != null, so the id-derived accessibilityLabel is never focusable and
    # TalkBack never speaks "avatar-preview". The wrapper the behavior hides is a
    # <view>, which copies no server attribute at all.
    preview = node.find(".//hv:image[@id='avatar-preview']", NS)
    assert preview is not None
    assert preview.attrib["hide"] == "true"
    # NEVER source="": createProps copies the attribute verbatim, so an empty
    # source is the empty STRING on the RN Image rather than absent.
    assert preview.attrib["source"].startswith("data:image/png;base64,")
    assert not {"alt", "accessibilityLabel"} & set(preview.attrib)

    current = node.find(".//hv:view[@id='avatar-current']", NS)
    assert current is not None
    assert not [key for key in current.attrib if key.startswith("accessib")]
    assert "alt" not in current.attrib
    behavior = pick.find("./hv:behavior[@action='pick-avatar']", NS)
    assert behavior.attrib["target"] == "avatar-data"
    assert behavior.attrib["preview-target"] == "avatar-preview"
    assert behavior.attrib["current-target"] == "avatar-current"
    # The dispatch is gone with the POST it armed.
    assert "event-name" not in behavior.attrib


def test_the_photo_row_says_when_the_photo_is_actually_saved(user):
    # Picking and walking away loses the pick, and nothing can warn at the moment
    # of loss: Hyperview has no unsaved-changes hook and a `navigate` cannot be
    # cancelled from HXML. An always-visible server-rendered caption is the only
    # honest mitigation, and it has to be there BEFORE the pick, not after it.
    root, _ = panel(user, **CURRENT_CLIENT)

    captions = [text.text for text in root.findall(".//hv:text[@style='meta']", NS)]

    assert "Your photo is saved when you tap Save settings." in captions


def test_the_photo_row_puts_a_real_button_beside_the_disc(user):
    # F: reuse the ONE compact secondary shape this app already declares, the
    # categories Edit/Delete box, rather than a full-width primary. The disc and
    # the control share a row, so the eye finds a control-shaped object in the
    # card instead of a caption.
    root, node = panel(user, **CURRENT_CLIENT)
    row = avatar_row(node)
    # Three children now: the stored disc inside the wrapper the pick hides, the
    # preview that takes its place, and the control.
    current, preview, right = list(row)

    assert list(current)[0].attrib["style"].split() == [
        "avatar-disc",
        "avatar-disc-row",
    ]
    assert preview.attrib["style"].split() == ["avatar-disc", "avatar-disc-row"]
    # The <form> that used to wrap it is gone with the endpoint it posted to, so
    # the control IS the row's third child now.
    pick = right
    assert pick.attrib["style"] == "avatar-action"
    # No id: HyperRef puts createTestProps on its own TouchableOpacity
    # (hyper-ref.tsx:299 and 343) and that is accessibilityLabel=id off iOS
    # (services/index.ts:81-84), so TalkBack would focus the wrapper and read
    # "avatar-pick". PickAvatarBehavior reads `target`, never this element's id.
    assert "id" not in pick.attrib
    label = pick.find("./hv:text[@style='avatar-action-text']", NS)
    # "Choose photo", not "Change photo" and not "Upload": it opens the library
    # and writes nothing. The Save button is what changes the photo.
    assert label.text == "Choose photo"
    # HvView copies no server attribute and the TouchableOpacity is
    # accessible={false}, so this <text> is the only announceable node in the
    # control and without the role it reads as static text. Same as the side-menu
    # rows and the appearance toggle.
    assert label.attrib["accessibilityRole"] == "button"
    actions = [
        behavior.attrib.get("action") for behavior in pick.findall("./hv:behavior", NS)
    ]
    assert actions == ["pick-avatar"]
    assert int(style_by_id(root, "avatar-action").attrib["minHeight"]) >= 44
    # The disc keeps its own marginBottom in the golden and drops it by COMPOSING
    # a second id, because dropping an attribute the fixture pins would fail there.
    assert style_by_id(root, "avatar-disc").attrib["marginBottom"] == "12"
    assert style_by_id(root, "avatar-disc-row").attrib["marginBottom"] == "0"


@pytest.mark.parametrize("headers", [{"x-app-version": "1.1.0"}, {}])
def test_a_gated_client_gets_the_same_row_with_an_inert_box_and_a_reason(user, headers):
    # E: the gate was right and the MESSAGE was wrong. A 13px caption at the end of
    # the third card down, identical to the biometric caption two cards below, is
    # why "there is no button" was a literally accurate reading of the screen. Now
    # the row never changes shape: same disc, same box geometry, drawn as a
    # disabled control, with the reason under it. It carries no href and no
    # behavior, so HyperRef never wraps it and it genuinely cannot be pressed.
    _, node = panel(user, **headers)
    row = avatar_row(node)
    current, _preview, right = list(row)

    assert list(current)[0].attrib["style"].split() == [
        "avatar-disc",
        "avatar-disc-row",
    ]
    assert right.attrib["style"] == "avatar-gate"
    assert "href" not in right.attrib
    assert not right.findall(".//hv:behavior", NS)
    assert right.find("./hv:text[@style='avatar-gate-text']", NS).text == (
        "Update the app"
    )
    note = node.find(".//hv:text[@style='avatar-gate-note']", NS)
    assert note is not None
    assert note.text == "Update HyperTodo to change your photo."
    # The disc explains itself too. A <view> cannot carry a server-set label at
    # all (HvView copies no attributes), and the <text> must carry no id, because
    # createTestProps is spread last and an id overwrites the label on Android.
    initials = node.find(".//hv:text[@style='avatar-initials']", NS)
    assert initials.attrib["accessibilityLabel"] == (
        "Your initials. Update HyperTodo to change your photo."
    )
    assert "id" not in initials.attrib


def test_an_uploadable_client_leaves_the_initials_announcing_only_the_initials(user):
    _, node = panel(user, **CURRENT_CLIENT)

    initials = node.find(".//hv:text[@style='avatar-initials']", NS)

    assert "accessibilityLabel" not in initials.attrib


def test_storing_a_photo_leaves_the_writers_own_instance_holding_the_new_row(user):
    """Rule 13, asserted where it now lives.

    Django caches the reverse one-to-one on whichever instance walked it, and
    store_avatar works on its own get_or_create instance. Anything that read
    request.user.profile earlier in the request -- the theme context processor
    does, on every render -- left a stale copy behind, which is how the avatar
    panel used to re-render the PREVIOUS photo after a successful upload.

    That panel is no longer a replace payload: the Save answers with a transition
    and the new photo reaches the dashboard through session-changed, i.e. through
    a fresh request. So the defect has no rendered surface on this path any more,
    and the guard moves down to the service that owns the property rather than
    disappearing with the markup that used to expose it.
    """
    # Walk it first, exactly as the theme context processor does on every render.
    Profile.objects.create(user=user)
    assert not user.profile.avatar

    store_avatar(user=user, data=jpeg())

    assert user.profile.avatar.name.startswith("avatars/")
