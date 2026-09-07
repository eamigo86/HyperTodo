"""Security and contract tests for biometric device credentials."""

import hashlib
from datetime import timedelta
from xml.etree import ElementTree

import pytest
from django.core.cache import cache
from django.db import IntegrityError
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from tests.test_forms_ui import assert_hxml, contrast_ratio
from todo.models import BiometricCredential
from todo.services import (
    BIOMETRIC_TOKEN_TTL,
    authenticate_biometric_token,
    issue_biometric_token,
    revoke_biometric_token,
)
from todo.views import BIOMETRIC_ATTEMPT_LIMIT, _biometric_attempt_key

pytestmark = pytest.mark.django_db
NS = {"hv": "https://hyperview.org/hyperview"}


def test_credential_is_one_per_user_and_never_exposes_the_raw_token(user):
    raw = "not-a-real-token"
    credential = BiometricCredential.objects.create(
        user=user, token_hash=hashlib.sha256(raw.encode()).hexdigest()
    )

    assert user.username in str(credential)
    assert credential.token_hash not in str(credential)
    assert raw not in str(credential)

    with pytest.raises(IntegrityError):
        BiometricCredential.objects.create(user=user, token_hash="another-hash")


def test_credential_hash_is_unique_across_users(user, other_user):
    shared = hashlib.sha256(b"collision").hexdigest()
    BiometricCredential.objects.create(user=user, token_hash=shared)

    with pytest.raises(IntegrityError):
        BiometricCredential.objects.create(user=other_user, token_hash=shared)


def test_credential_is_deleted_with_its_user(user):
    BiometricCredential.objects.create(user=user, token_hash="a" * 64)
    user.delete()

    assert BiometricCredential.objects.count() == 0


def test_credential_starts_unused_and_records_a_creation_time(user):
    credential = BiometricCredential.objects.create(user=user, token_hash="b" * 64)

    assert credential.last_used_at is None
    assert timezone.now() - credential.created_at < timedelta(seconds=5)


def test_issue_stores_only_the_hash_and_returns_high_entropy_material(user):
    raw = issue_biometric_token(user=user)
    credential = BiometricCredential.objects.get()

    assert len(raw) >= 32
    assert credential.user == user
    assert credential.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in credential.token_hash
    assert BiometricCredential.objects.filter(token_hash=raw).exists() is False


def test_issue_rotates_in_place_and_kills_the_previous_token(user):
    first = issue_biometric_token(user=user)
    second = issue_biometric_token(user=user)

    assert first != second
    assert BiometricCredential.objects.count() == 1
    assert authenticate_biometric_token(raw_token=first) is None
    assert authenticate_biometric_token(raw_token=second) == user


def test_authenticate_returns_only_the_issuing_user(user, other_user):
    mine = issue_biometric_token(user=user)
    theirs = issue_biometric_token(user=other_user)

    assert authenticate_biometric_token(raw_token=mine) == user
    assert authenticate_biometric_token(raw_token=theirs) == other_user


@pytest.mark.parametrize("bad", ["", "   ", "garbage", "a" * 64])
def test_authenticate_rejects_absent_and_wrong_tokens(user, bad):
    issue_biometric_token(user=user)

    assert authenticate_biometric_token(raw_token=bad) is None


def test_authenticate_rejects_a_revoked_token(user):
    raw = issue_biometric_token(user=user)
    revoke_biometric_token(user=user)

    assert BiometricCredential.objects.count() == 0
    assert authenticate_biometric_token(raw_token=raw) is None


def test_revoke_is_idempotent_when_no_credential_exists(user):
    revoke_biometric_token(user=user)

    assert BiometricCredential.objects.count() == 0


def test_authenticate_rejects_and_deletes_an_expired_token(user):
    raw = issue_biometric_token(user=user)
    BiometricCredential.objects.update(
        created_at=timezone.now() - BIOMETRIC_TOKEN_TTL - timedelta(seconds=1)
    )

    assert authenticate_biometric_token(raw_token=raw) is None
    assert BiometricCredential.objects.count() == 0


def test_rotation_keeps_the_original_issue_time(user):
    issue_biometric_token(user=user)
    issued_at = timezone.now() - BIOMETRIC_TOKEN_TTL + timedelta(hours=1)
    BiometricCredential.objects.update(created_at=issued_at)

    rotated = issue_biometric_token(user=user)

    # The lifetime is absolute from the first opt-in: rotating on every unlock does
    # not slide the expiry, so the password is required again after the TTL.
    assert BiometricCredential.objects.get().created_at == issued_at
    assert authenticate_biometric_token(raw_token=rotated) == user


def test_rotation_keeps_the_recorded_last_use(user):
    raw = issue_biometric_token(user=user)
    authenticate_biometric_token(raw_token=raw)
    used_at = BiometricCredential.objects.get().last_used_at
    assert used_at is not None

    issue_biometric_token(user=user)

    assert BiometricCredential.objects.get().last_used_at == used_at


def test_authenticate_stamps_last_used(user):
    raw = issue_biometric_token(user=user)

    assert authenticate_biometric_token(raw_token=raw) == user
    assert BiometricCredential.objects.get().last_used_at is not None


def test_changing_the_password_revokes_the_device_credential(user):
    # Changing the password is the standard "I think I am compromised" response, and
    # Django's session auth hash already ends every live session. Without this the
    # phone in the thief's pocket keeps unlocking, and every unlock rotates the token.
    raw = issue_biometric_token(user=user)
    user.set_password("a-brand-new-password")
    user.save(update_fields=("password",))

    assert authenticate_biometric_token(raw_token=raw) is None
    assert not BiometricCredential.objects.exists()


def test_the_unlock_endpoint_refuses_a_credential_issued_before_a_password_change(
    client, user
):
    raw = issue_biometric_token(user=user)
    user.set_password("a-brand-new-password")
    user.save(update_fields=("password",))

    response = client.post(reverse("todo:biometric-login"), {"biometric_token": raw})

    assert response.status_code == 401
    assert "_auth_user_id" not in client.session


def test_an_untouched_password_leaves_the_credential_working(user):
    raw = issue_biometric_token(user=user)
    user.save()

    assert authenticate_biometric_token(raw_token=raw) == user


def test_an_operator_can_revoke_an_enrolment_without_the_enrolled_phone(admin_site):
    # /hv/biometric/forget/ and a password sign-in with the switch off both require
    # the enrolled device, which is exactly what a stolen-phone report no longer has.
    model_admin = admin_site._registry[BiometricCredential]

    assert set(model_admin.exclude) == {"token_hash", "password_hash"}
    assert model_admin.has_add_permission(RequestFactory().get("/admin/")) is False
    assert "user" in model_admin.list_display


def _throttle(token):
    """Fill the attempt bucket for one presented token.

    Built through the view's own key helper so the tests never pin its format.
    """
    request = RequestFactory().post(
        reverse("todo:biometric-login"), {"biometric_token": token}
    )
    cache.set(_biometric_attempt_key(request), BIOMETRIC_ATTEMPT_LIMIT, timeout=300)


def _panel_root(response, *, status):
    assert response.status_code == status
    root = ElementTree.fromstring(response.content)
    assert root.tag == f"{{{NS['hv']}}}view"
    assert root.attrib["id"] == "login-panel"
    return root


def _csrf_post(client, url, data):
    login_page = client.get(reverse("todo:login"))
    root = ElementTree.fromstring(login_page.content)
    token = root.find(
        ".//hv:form[@id='biometric-form']//hv:text-field[@name='csrfmiddlewaretoken']",
        NS,
    ).attrib["value"]
    return client.post(url, {**data, "csrfmiddlewaretoken": token})


def test_biometric_login_creates_a_session_and_rotates_the_token(client, user):
    raw = issue_biometric_token(user=user)

    response = client.post(reverse("todo:biometric-login"), {"biometric_token": raw})
    root = ElementTree.fromstring(response.content)

    assert response.status_code == 200
    assert root.attrib["id"] == "login-transition"
    assert client.session["_auth_user_id"] == str(user.pk)

    store = root.find("./hv:behavior[@action='store-biometric-token']", NS)
    assert store is not None
    assert store.attrib["trigger"] == "load"
    assert store.attrib["once"] == "true"
    assert store.attrib["immediate"] == "true"
    rotated = store.attrib["token"]
    assert rotated and rotated != raw
    assert authenticate_biometric_token(raw_token=rotated) == user


def test_biometric_login_rejects_a_token_belonging_to_nobody(client, user):
    issue_biometric_token(user=user)

    response = client.post(
        reverse("todo:biometric-login"), {"biometric_token": "forged-token"}
    )
    root = _panel_root(response, status=401)

    assert "_auth_user_id" not in client.session
    assert "".join(root.itertext()).strip()
    reset = root.find("./hv:behavior[@action='store-biometric-token']", NS)
    assert reset is not None
    assert reset.attrib["token"] == ""


def test_biometric_login_rejects_a_revoked_token(client, user):
    raw = issue_biometric_token(user=user)
    revoke_biometric_token(user=user)

    response = client.post(reverse("todo:biometric-login"), {"biometric_token": raw})

    _panel_root(response, status=401)
    assert "_auth_user_id" not in client.session


def test_biometric_login_rejects_an_absent_token(client, user):
    issue_biometric_token(user=user)

    response = client.post(reverse("todo:biometric-login"), {})

    _panel_root(response, status=401)
    assert "_auth_user_id" not in client.session


def test_biometric_login_never_signs_in_the_wrong_user(client, user, other_user):
    issue_biometric_token(user=user)
    theirs = issue_biometric_token(user=other_user)

    client.post(reverse("todo:biometric-login"), {"biometric_token": theirs})

    assert client.session["_auth_user_id"] == str(other_user.pk)


def test_biometric_login_is_post_only(client):
    response = client.get(reverse("todo:biometric-login"))

    assert response.status_code == 405
    assert response.headers["Allow"] == "POST"


def test_biometric_login_is_csrf_protected(user):
    raw = issue_biometric_token(user=user)
    client = Client(enforce_csrf_checks=True)

    assert (
        client.post(
            reverse("todo:biometric-login"), {"biometric_token": raw}
        ).status_code
        == 403
    )
    assert (
        _csrf_post(
            client, reverse("todo:biometric-login"), {"biometric_token": raw}
        ).status_code
        == 200
    )


def test_biometric_login_throttles_repeated_attempts(client, user):
    for _ in range(BIOMETRIC_ATTEMPT_LIMIT):
        response = client.post(
            reverse("todo:biometric-login"), {"biometric_token": "wrong"}
        )
        assert response.status_code == 401

    blocked = client.post(reverse("todo:biometric-login"), {"biometric_token": "wrong"})
    _panel_root(blocked, status=429)
    assert "_auth_user_id" not in client.session


def _password_login(client, **extra):
    return client.post(
        reverse("todo:login"),
        {"username": "ada", "password": "correct-horse", **extra},
    )


def test_password_login_issues_no_token_without_opt_in(client, user):
    response = _password_login(client)
    root = ElementTree.fromstring(response.content)

    assert client.session["_auth_user_id"] == str(user.pk)
    assert BiometricCredential.objects.count() == 0
    store = root.find("./hv:behavior[@action='store-biometric-token']", NS)
    assert store is not None
    assert store.attrib["token"] == ""


def test_password_login_without_opt_in_revokes_a_previous_enrolment(client, user):
    _password_login(client, enable_biometrics="on")
    assert BiometricCredential.objects.count() == 1

    root = ElementTree.fromstring(_password_login(client).content)
    store = root.find("./hv:behavior[@action='store-biometric-token']", NS)

    assert BiometricCredential.objects.count() == 0
    assert store is not None
    assert store.attrib["token"] == ""


def test_another_users_password_login_wipes_the_device_key(client, user, other_user):
    raw = issue_biometric_token(user=user)

    root = ElementTree.fromstring(_password_login(client, username="grace").content)
    store = root.find("./hv:behavior[@action='store-biometric-token']", NS)

    assert client.session["_auth_user_id"] == str(other_user.pk)
    assert store is not None
    assert store.attrib["token"] == ""
    # The request carries no evidence of which credential this phone held, so the
    # device wipe is what stops the first user's token being replayed from it.
    assert authenticate_biometric_token(raw_token=raw) == user


def test_another_users_password_login_re_keys_the_device_slot(client, user, other_user):
    # The switch now arrives pre-selected on an enrolled phone, so the interesting
    # case is opt-in ON: the one keychain slot is overwritten with grace's token,
    # which is what destroys ada's raw material.
    ada_raw = issue_biometric_token(user=user)

    root = ElementTree.fromstring(
        _password_login(client, username="grace", enable_biometrics="on").content
    )
    grace_raw = root.find("./hv:behavior[@action='store-biometric-token']", NS).attrib[
        "token"
    ]

    assert authenticate_biometric_token(raw_token=grace_raw) == other_user
    assert grace_raw != ada_raw
    # ada's server row survives as a credential no device holds. Harmless: the raw
    # token died with the keychain slot, it expires within the TTL, and she can clear
    # it from the settings screen.
    # ponytail: to kill it eagerly the phone would have to ship its held token up
    # with the password POST. More machinery, more attack surface, no real gain.


def test_password_login_issues_a_token_when_the_user_opts_in(client, user):
    response = _password_login(client, enable_biometrics="on")
    root = ElementTree.fromstring(response.content)

    store = root.find("./hv:behavior[@action='store-biometric-token']", NS)
    assert store is not None
    assert store.attrib["immediate"] == "true"
    assert store.attrib["once"] == "true"
    assert BiometricCredential.objects.count() == 1
    issued = store.attrib["token"]
    assert authenticate_biometric_token(raw_token=issued) == user


def test_password_login_never_stores_the_issued_token_in_the_database(client, user):
    response = _password_login(client, enable_biometrics="on")
    root = ElementTree.fromstring(response.content)
    store = root.find("./hv:behavior[@action='store-biometric-token']", NS)
    raw = store.attrib["token"]

    assert raw not in BiometricCredential.objects.get().token_hash
    assert not BiometricCredential.objects.filter(token_hash__contains=raw[:16])


def test_failed_password_login_issues_nothing(client, user):
    response = client.post(
        reverse("todo:login"),
        {"username": "ada", "password": "wrong", "enable_biometrics": "on"},
    )

    _panel_root(response, status=422)
    assert BiometricCredential.objects.count() == 0


def test_logout_keeps_the_enrolment_and_the_device_key(client, user):
    # Signing out is a SESSION action, not a device action. Revoking here made the
    # credential exist only while the user was already signed in, i.e. exactly when
    # it is useless, and the login screen could never offer the unlock button.
    _password_login(client, enable_biometrics="on")
    assert BiometricCredential.objects.count() == 1

    response = client.post(reverse("todo:logout"))
    root = ElementTree.fromstring(response.content)

    assert BiometricCredential.objects.count() == 1
    assert root.find("./hv:behavior[@action='store-biometric-token']", NS) is None
    assert root.find("./hv:behavior[@action='reload']", NS) is not None


def test_logout_without_a_session_leaves_the_device_alone(client):
    response = client.post(reverse("todo:logout"))
    root = ElementTree.fromstring(response.content)

    assert root.find("./hv:behavior[@action='store-biometric-token']", NS) is None


def test_the_kept_token_still_unlocks_after_logout(client, user):
    # The owner's exact report: enable biometrics, sign out, and the phone can no
    # longer unlock. What forces a password sign-in now is the TTL, the explicit
    # forget control, or an opt-in switch left off at a password login.
    root = ElementTree.fromstring(
        _password_login(client, enable_biometrics="on").content
    )
    store = root.find("./hv:behavior[@action='store-biometric-token']", NS)
    raw = store.attrib["token"]
    client.post(reverse("todo:logout"))
    assert "_auth_user_id" not in client.session

    response = client.post(reverse("todo:biometric-login"), {"biometric_token": raw})

    assert response.status_code == 200
    assert client.session["_auth_user_id"] == str(user.pk)


def test_the_raw_token_is_never_written_to_the_logs(client, user, caplog):
    with caplog.at_level(0):
        response = _password_login(client, enable_biometrics="on")
    root = ElementTree.fromstring(response.content)
    store = root.find("./hv:behavior[@action='store-biometric-token']", NS)
    raw = store.attrib["token"]

    assert raw not in caplog.text
    assert str(BiometricCredential.objects.get()) == f"Biometric credential for {user}"


def _login_screen(client):
    return ElementTree.fromstring(client.get(reverse("todo:login")).content)


def test_login_screen_ships_hidden_biometric_controls(client):
    root = _login_screen(client)

    probe = root.find(".//hv:view[@id='login-panel']/hv:behavior", NS)
    assert probe.attrib["action"] == "probe-biometrics"
    assert probe.attrib["trigger"] == "load"
    assert probe.attrib["once"] == "true"
    assert probe.attrib["available-target"] == "biometric-optin"
    assert probe.attrib["token-target"] == "biometric-signin"

    for element_id in ("biometric-optin", "biometric-signin"):
        assert root.find(f".//*[@id='{element_id}']", NS).attrib["hide"] == "true"

    field = root.find(".//hv:text-field[@id='biometric-token']", NS)
    assert field.attrib["hide"] == "true"
    assert field.attrib["name"] == "biometric_token"
    assert field.attrib["value"] == ""


def test_the_privacy_hint_follows_both_ways_to_sign_in(client):
    # The hint used to sit INSIDE login-form's card, wedged between the password
    # button and the biometric control, which read as a footnote on one method
    # rather than on signing in. It now closes the panel, after both forms.
    panel = _login_screen(client).find(".//hv:view[@id='login-panel']", NS)

    forms = [child for child in panel if child.tag != f"{{{NS['hv']}}}behavior"]
    assert [
        child.attrib.get("id") or child.tag.rpartition("}")[2] for child in forms
    ] == [
        "login-form",
        "biometric-form",
        "text",
    ]
    hint = forms[-1]
    assert hint.attrib["style"] == "hint"
    assert hint.text.startswith("Your tasks stay private")
    login_form = panel.find("./hv:form[@id='login-form']", NS)
    assert login_form.find(".//hv:text[@style='hint']", NS) is None


def test_the_biometric_opt_in_switch_is_visible_in_its_off_state(client):
    # HvSwitch maps backgroundColor -> trackColor and color -> thumbColor
    # (hv-switch/index.tsx:57-95), so this style IS the control's whole appearance and
    # the WCAG user-agent-default exception no longer applies. A switch is a graphical
    # object: 3:1 for the boundaries that carry its state. OFF is the state a
    # first-time signer-in has to find in order to turn biometrics on at all; #C4CBDC
    # was 1.53:1 against the sheet and 1.63:1 against its own white thumb.
    root = _login_screen(client)
    switch = root.find("./hv:styles/hv:style[@id='optin-switch']", NS)
    selected = switch.find("./hv:modifier[@selected='true']/hv:style", NS)
    sheet = root.find("./hv:styles/hv:style[@id='login-sheet']", NS)
    backdrop = sheet.attrib["backgroundColor"]

    for label, pair in {
        "off track on the sheet": (switch.attrib["backgroundColor"], backdrop),
        "off thumb on its track": (
            switch.attrib["color"],
            switch.attrib["backgroundColor"],
        ),
        "on track on the sheet": (selected.attrib["backgroundColor"], backdrop),
    }.items():
        assert contrast_ratio(*pair) >= 3, f"{label}: {pair[0]} on {pair[1]}"


def test_the_privacy_hint_is_readable_body_text(client):
    # 13px is not WCAG large text, so the hint owes 4.5:1 against the sheet it closes.
    # #6E738A was 4.41:1 - the same near-miss the settings version line carried.
    root = _login_screen(client)
    hint = root.find("./hv:styles/hv:style[@id='hint']", NS)
    backdrop = root.find("./hv:styles/hv:style[@id='login-sheet']", NS)

    assert int(hint.attrib["fontSize"]) < 18
    assert (
        contrast_ratio(hint.attrib["color"], backdrop.attrib["backgroundColor"]) >= 4.5
    )


def test_the_password_form_and_the_biometric_form_never_share_inputs(client):
    root = _login_screen(client)
    login_form = root.find(".//hv:form[@id='login-form']", NS)
    biometric_form = root.find(".//hv:form[@id='biometric-form']", NS)

    def names(form):
        return {node.attrib["name"] for node in form.iter() if "name" in node.attrib}

    assert names(login_form) == {
        "username",
        "password",
        "enable_biometrics",
        "csrfmiddlewaretoken",
    }
    assert names(biometric_form) == {"biometric_token", "csrfmiddlewaretoken"}
    assert biometric_form.find(".//hv:form", NS) is None
    assert login_form.find(".//hv:form", NS) is None


def test_the_biometric_button_writes_then_posts(client):
    root = _login_screen(client)
    button = root.find(".//hv:view[@id='biometric-signin']", NS)
    press, on_event = button.findall("./hv:behavior", NS)

    assert press.attrib["trigger"] == "press"
    assert press.attrib["action"] == "biometric-unlock"
    assert press.attrib["target"] == "biometric-token"
    assert "once" not in press.attrib

    assert on_event.attrib["trigger"] == "on-event"
    assert on_event.attrib["event-name"] == press.attrib["event-name"]
    assert on_event.attrib["href"] == reverse("todo:biometric-login")
    assert on_event.attrib["verb"] == "post"
    assert on_event.attrib["action"] == "replace"
    assert on_event.attrib["target"] == "login-panel"


def test_the_icon_only_biometric_button_is_a_tappable_circle(client):
    # The button lost its text child, so nothing but the declared box keeps the
    # 44pt target: padding plus a 28pt glyph is not a contract. It is a fixed-size
    # circle now rather than a full-width slab, so it cannot be mistaken for a
    # second primary button sitting under the real one.
    # `./hv:styles/hv:style` and not `.//hv:style`: the latter also matches the
    # <style> nested in a <modifier>, which carries no id.
    style = _login_screen(client).find(
        "./hv:styles/hv:style[@id='biometric-button']", NS
    )

    assert int(style.attrib["height"]) >= 44
    assert int(style.attrib["width"]) >= 44
    # borderRadius is exactly half the box, which is what makes a circle in React
    # Native. Both are parsed with parseInt (stylesheets/index.ts:21-23), so they
    # must stay integers.
    assert int(style.attrib["borderRadius"]) * 2 == int(style.attrib["height"])
    assert int(style.attrib["height"]) == int(style.attrib["width"])
    # Without alignSelf the fixed width would stretch back to the form's full
    # width, which is the slab this replaced.
    assert style.attrib["alignSelf"] == "center"
    assert style.find("./hv:modifier[@pressed='true']", NS) is not None


def test_the_biometric_glyph_is_tinted_to_read_as_actionable(client):
    # Untinted, the glyph rendered in the PNG's baked dark navy directly under a
    # saturated blue button and read as disabled. tintColor recolours every
    # non-transparent pixel (react-native ImageProps.js:311) and is on hyperview's
    # supported list (stylesheets/index.ts:195), so one attribute tints both
    # modality variants without shipping a second pair of PNGs.
    root = _login_screen(client)
    icon = root.find("./hv:styles/hv:style[@id='biometric-icon']", NS)
    button = root.find("./hv:styles/hv:style[@id='biometric-button']", NS)

    assert icon.attrib["tintColor"] == "#278CFF"
    # Every icon in the directory ships at 72x72, which is exactly 3x of 24pt. Drawing
    # this pair at 28 asked a 3x phone for 84 physical pixels it does not have, so the
    # single glyph inside the 60pt circle rendered soft.
    assert (icon.attrib["height"], icon.attrib["width"]) == ("24", "24")
    # 3:1 is the WCAG floor for a graphical object: glyph against its own fill,
    # and the circle's outline against the sheet it sits on.
    assert (
        contrast_ratio(icon.attrib["tintColor"], button.attrib["backgroundColor"]) >= 3
    )
    assert contrast_ratio(button.attrib["borderColor"], "#F7F8FC") >= 3


def test_the_biometric_glyph_clears_the_graphical_floor_in_both_press_states(client):
    # The resting pair passes on its own (3.34:1) but the pressed one used not to.
    # Two things stack there. The pressed fill lifts the background, and `pressed`
    # propagates into every descendant where a child with no pressed rule of its
    # own falls back to opacity 0.7 (services/index.ts:33-41): the glyph then
    # composites to #62ABFF over the fill, 2.1:1. An explicit pressed tint is what
    # cancels the fallback and buys the contrast back.
    # Read out of the stylesheet rather than pinned to literals, so recolouring
    # either style is what this catches.
    root = _login_screen(client)
    icon = root.find("./hv:styles/hv:style[@id='biometric-icon']", NS)
    button = root.find("./hv:styles/hv:style[@id='biometric-button']", NS)
    icon_pressed = icon.find("./hv:modifier[@pressed='true']/hv:style", NS)
    button_pressed = button.find("./hv:modifier[@pressed='true']/hv:style", NS)

    assert icon_pressed is not None, "no pressed rule: the glyph dims to opacity 0.7"
    # Pressed rules are concatenated onto the regular ones (services/index.ts:40),
    # so anything the modifier omits keeps its resting value.
    states = {
        "resting": (icon.attrib["tintColor"], button.attrib["backgroundColor"]),
        "pressed": (
            icon_pressed.attrib.get("tintColor", icon.attrib["tintColor"]),
            button_pressed.attrib.get(
                "backgroundColor", button.attrib["backgroundColor"]
            ),
        ),
    }

    for state, (glyph, fill) in states.items():
        assert contrast_ratio(glyph, fill) >= 3, f"{state}: {glyph} on {fill}"
    # The press still has to read as a press: same glyph on the same fill is a
    # state change nobody can see.
    assert states["pressed"] != states["resting"]


def test_the_rejected_panel_wipes_the_device_but_still_offers_re_enrolment(
    client, user
):
    response = client.post(
        reverse("todo:biometric-login"), {"biometric_token": "wrong"}
    )
    root = _panel_root(response, status=401)
    behavior = root.find("./hv:behavior", NS)

    assert behavior.attrib["action"] == "store-biometric-token"
    assert behavior.attrib["token"] == ""
    assert behavior.attrib["once"] == "true"
    assert behavior.attrib["immediate"] == "true"
    # The copy tells the user to sign in and enable the device again, so the probe
    # that reveals the opt-in switch must survive the wipe.
    assert root.find("./hv:behavior[@action='probe-biometrics']", NS) is not None
    assert root.find(".//hv:switch[@name='enable_biometrics']", NS) is not None
    assert root.find(".//hv:view[@id='biometric-error']", NS) is not None


def test_the_throttled_panel_leaves_the_device_credential_alone(client, user):
    _throttle("wrong")

    response = client.post(
        reverse("todo:biometric-login"), {"biometric_token": "wrong"}
    )
    root = _panel_root(response, status=429)

    # A rate-limited request proves nothing about the token, so it must not de-enrol
    # the device the way a rejected token does.
    assert root.find("./hv:behavior[@action='store-biometric-token']", NS) is None
    assert root.find("./hv:behavior[@action='probe-biometrics']", NS) is not None
    assert root.find(".//hv:view[@id='biometric-error']", NS) is not None


def test_a_rejected_token_never_throttles_a_different_credential(client, user):
    # The bucket is per presented token. Keyed on REMOTE_ADDR alone, one client
    # burning ten garbage tokens locked out every user behind the same proxy or NAT
    # for five minutes, and any success cleared the counter for all of them.
    url = reverse("todo:biometric-login")
    for _ in range(BIOMETRIC_ATTEMPT_LIMIT):
        assert client.post(url, {"biometric_token": "wrong"}).status_code == 401
    raw = issue_biometric_token(user=user)

    assert client.post(url, {"biometric_token": "wrong"}).status_code == 429
    assert client.post(url, {"biometric_token": raw}).status_code == 200


@override_settings(
    AUTHENTICATION_BACKENDS=[
        "django.contrib.auth.backends.ModelBackend",
        "django.contrib.auth.backends.AllowAllUsersModelBackend",
    ]
)
def test_biometric_login_names_its_backend_so_extra_backends_cannot_break_it(
    client, user
):
    raw = issue_biometric_token(user=user)

    response = client.post(reverse("todo:biometric-login"), {"biometric_token": raw})

    assert response.status_code == 200
    assert client.session["_auth_user_id"] == str(user.pk)


@pytest.mark.parametrize("status", [401, 429])
def test_reset_panels_are_bare_fragments_using_only_screen_styles(client, status):
    if status == 429:
        _throttle("wrong")
    screen = _login_screen(client)
    root = _panel_root(
        client.post(reverse("todo:biometric-login"), {"biometric_token": "wrong"}),
        status=status,
    )

    for forbidden in ("doc", "screen", "body", "styles"):
        assert root.find(f".//hv:{forbidden}", NS) is None

    defined = {
        style.attrib["id"] for style in screen.findall("./hv:styles/hv:style", NS)
    }
    used = {
        style_id
        for node in root.iter()
        for name, value in node.attrib.items()
        if name.endswith("style")
        for style_id in value.split()
    }
    assert used
    assert used <= defined


def _assert_bare(root):
    assert root.tag == f"{{{NS['hv']}}}view"
    for forbidden in ("doc", "screen", "body", "styles"):
        assert root.find(f".//hv:{forbidden}", NS) is None


def test_the_login_transition_is_bare_and_carries_the_token(client, user):
    root = ElementTree.fromstring(
        _password_login(client, enable_biometrics="on").content
    )

    _assert_bare(root)
    assert root.find("./hv:behavior[@action='store-biometric-token']", NS) is not None


def test_the_logout_transition_is_bare_and_touches_no_device_key(client, user):
    _password_login(client, enable_biometrics="on")

    root = ElementTree.fromstring(client.post(reverse("todo:logout")).content)

    _assert_bare(root)
    assert root.find("./hv:behavior[@action='store-biometric-token']", NS) is None


def _screen_styles(client, route):
    screen = ElementTree.fromstring(client.get(route).content)
    return {style.attrib["id"] for style in screen.findall("./hv:styles/hv:style", NS)}


def _used_styles(root):
    return {
        style_id
        for node in root.iter()
        for name, value in node.attrib.items()
        if name.endswith("style")
        for style_id in value.split()
    }


# The forget affordance moved off the side menu onto the settings screen; its
# enrolment-gated assertions now live in
# tests/test_settings.py::test_settings_offers_forgetting_biometrics_only_when_enrolled.


# --- un-enrolling, as a pending field of the one settings form ----------------
#
# /hv/biometric/forget/ is gone. It was an immediate writer on a screen that also
# held unsaved text, which is the same class of hazard the preference switcher had
# there: a tap committed while the name beside it was still typed and unsaved.
# It is a <switch> inside settings-form now, and the Save button commits it.

SWITCH_LABEL = "Unlock with biometrics on this phone"


def _closest_form(root, node):
    """Return the <form> ancestor whose data a control inside it would post."""
    parents = {child: parent for parent in root.iter() for child in parent}
    while node is not None:
        if node.tag == f"{{{NS['hv']}}}form":
            return node
        node = parents.get(node)
    return None


def _settings_switch(root):
    return root.find(f".//hv:switch[@id='{SWITCH_LABEL}']", NS)


def _save(client, **fields):
    """POST the whole settings form the way the Save button serialises it."""
    payload = {"first_name": "", "last_name": "", "email": "", **fields}
    return client.post(reverse("todo:settings"), payload)


def test_the_biometric_switch_only_exists_when_a_credential_does(client, user):
    # OFF-ONLY by ABSENCE, not by a disabled control. HvSwitch builds its props
    # from a fixed literal (hv-switch/index.tsx:53-76) and never calls createProps,
    # so `disabled` is unreachable from HXML: a "disabled" switch would still flip
    # under the finger and still serialise. And there is nothing to turn ON, since
    # with no credential the ON position would mean "enrol", which the
    # password-sign-in-only model exists to forbid.
    client.force_login(user)

    before = assert_hxml(client.get(reverse("todo:settings")))
    assert _settings_switch(before) is None
    captions = [
        node.text
        for node in before.find(".//hv:view[@id='biometric-panel']", NS).iter()
    ]
    assert "Biometric unlock is off on this phone." in captions
    # The one way back on, named. Without it the card states a fact and offers no
    # route out of it.
    assert any("password" in (text or "") for text in captions), captions

    issue_biometric_token(user=user)
    after = assert_hxml(client.get(reverse("todo:settings")))
    switch = _settings_switch(after)

    assert switch is not None
    assert switch.attrib["name"] == "biometric_unlock"
    # It starts ON, so OFF is the only state change it can express; flipping it
    # back before saving cancels the pending change and never enrols.
    assert switch.attrib["value"] == "on"
    # The id is the accessible name on Android: HvSwitch takes only createTestProps,
    # so an accessibilityLabel attribute would be dropped on the floor. On iOS the
    # same call yields testID and no name at all, which no template can fix.
    assert "accessibilityLabel" not in switch.attrib
    assert _closest_form(after, switch).attrib["id"] == "settings-form"


def test_saving_with_the_switch_off_revokes_the_credential_and_wipes_the_device(
    client, user
):
    raw = issue_biometric_token(user=user)
    client.force_login(user)

    response = _save(client, first_name="Ada", biometric_unlock="off")

    root = assert_hxml(response)
    assert BiometricCredential.objects.count() == 0
    assert authenticate_biometric_token(raw_token=raw) is None
    store = root.find("./hv:behavior[@action='store-biometric-token']", NS)
    assert store is not None
    assert store.attrib["token"] == ""
    assert store.attrib["once"] == "true"
    assert store.attrib["immediate"] == "true"
    user.refresh_from_db()
    assert user.first_name == "Ada"


def test_a_422_hands_back_the_switch_position_the_user_posted(client, user, other_user):
    # Every OTHER pending edit survives a refused save -- the typed name, the email,
    # the base64 photo are all re-armed -- so a switch that repaints ON silently
    # reverts a revocation the user asked for. They fix the email, tap Save, and the
    # DOM now serialises "on": `forgotten` is False, nothing is revoked, and the
    # 30-day device credential they believe they killed keeps unlocking the account.
    other_user.email = "taken@example.com"
    other_user.save(update_fields=("email",))
    issue_biometric_token(user=user)
    client.force_login(user)

    root = assert_hxml(
        _save(client, email="taken@example.com", biometric_unlock="off"), status=422
    )

    # The atomic block never ran, so the credential is still there -- which is why
    # the switch is still rendered, and why its position has to be the posted one.
    assert BiometricCredential.objects.count() == 1
    assert _settings_switch(root).attrib["value"] == "off"


def test_saving_with_the_switch_left_on_touches_nothing(client, user):
    raw = issue_biometric_token(user=user)
    client.force_login(user)

    root = assert_hxml(_save(client, biometric_unlock="on"))

    assert authenticate_biometric_token(raw_token=raw) is not None
    assert root.find("./hv:behavior[@action='store-biometric-token']", NS) is None


def test_a_body_that_never_carried_the_switch_is_not_read_as_turning_it_off(
    client, user
):
    # Absence is NOT the marker, and it cannot be: getNameValueFormInputValues
    # posts a named input's `value` attribute unconditionally (client
    # services/index.ts:292-300), so a <switch> that is on screen is ALWAYS in the
    # body -- unlike an HTML checkbox, where absence means off. Absence here means
    # the control was never rendered, which is a statement about nothing. Reading
    # it as "off" would let any body that omits the key revoke a credential.
    raw = issue_biometric_token(user=user)
    client.force_login(user)

    root = assert_hxml(client.post(reverse("todo:settings"), {}))

    assert authenticate_biometric_token(raw_token=raw) is not None
    assert root.find("./hv:behavior[@action='store-biometric-token']", NS) is None


def test_the_save_endpoint_is_csrf_protected_before_it_revokes_anything(user):
    enforcing = Client(enforce_csrf_checks=True)
    enforcing.force_login(user)
    issue_biometric_token(user=user)

    refused = enforcing.post(reverse("todo:settings"), {"biometric_unlock": "off"})

    assert refused.status_code == 403
    assert BiometricCredential.objects.count() == 1


def test_saving_the_switch_off_twice_is_idempotent(client, user):
    # The first save has to actually DELETE a row, or the second one is not the
    # second pass over an already-empty table and this guard cannot fail.
    issue_biometric_token(user=user)
    client.force_login(user)

    assert _save(client, biometric_unlock="off").status_code == 200
    assert _save(client, biometric_unlock="off").status_code == 200
    assert BiometricCredential.objects.count() == 0


# Each fragment is pinned to the screens that can actually host it: `replace` does
# not rebuild stylesheets, so this is the whole contract. The side menu opens from
# the dashboard hero only. The forget fragment is gone with its endpoint; the
# settings 422 fragment that replaced it is checked by
# tests/test_settings.py::test_the_settings_fragments_only_use_styles_the_screen
# _declares.
@pytest.mark.parametrize(
    ("route_name", "host", "verb"),
    [
        ("todo:menu", "todo:dashboard", "get"),
    ],
)
def test_the_menu_fragments_only_use_styles_their_host_screen_declares(
    client, user, route_name, host, verb
):
    client.force_login(user)
    issue_biometric_token(user=user)
    defined = _screen_styles(client, reverse(host))

    root = ElementTree.fromstring(getattr(client, verb)(reverse(route_name)).content)

    for forbidden in ("doc", "screen", "body", "styles"):
        assert root.find(f".//hv:{forbidden}", NS) is None
    used = _used_styles(root)
    assert used
    assert used <= defined, f"{route_name} on {host}: undeclared {used - defined}"


OPTIN_LABEL = "Unlock with biometrics next time"


def _optin_switch(root):
    return root.find(f".//hv:switch[@id='{OPTIN_LABEL}']", NS)


def test_the_optin_switch_carries_its_own_accessible_name_on_android(client):
    # ANDROID ONLY, and the name says so. HvSwitch builds componentProps from
    # createTestProps alone (hv-switch/index.tsx:57) -- no createProps -- so an alt
    # or accessibilityLabel attribute is dropped and the id is the ONLY channel:
    # createTestPropsFromId returns {accessibilityLabel: id} off iOS but
    # {testID: id} ON iOS (services/index.ts:81-84), so VoiceOver still reaches this
    # switch unnamed. That gap needs a client change; this pins the half a template
    # can reach. With a slug in the id, TalkBack announced "biometric-optin-switch"
    # for a control that enrols a 30-day device credential. The visible copy is a
    # sibling <text> and is never associated with the switch.
    root = _login_screen(client)
    switch = _optin_switch(root)

    assert switch is not None, "the switch id is its accessible name; keep them equal"
    label = root.find(".//hv:view[@id='biometric-optin']/hv:text", NS)
    assert label is not None and label.text == switch.attrib["id"]


def test_a_rejected_password_echoes_the_optin_switch_the_user_flipped(client, user):
    # Safe for exactly the reason the rejected-token panel already pre-selects it:
    # the person retrying the password is the person who just flipped this switch.
    # Dropping it back to "off" meant a user who mistyped a password signed in on
    # the retry and was silently not enrolled, with nothing on screen saying so.
    root = _panel_root(
        client.post(
            reverse("todo:login"),
            {"username": "ada", "password": "wrong", "enable_biometrics": "on"},
        ),
        status=422,
    )

    assert _optin_switch(root).attrib["value"] == "on"


def test_a_rejected_password_leaves_the_optin_switch_off_when_it_was_off(client, user):
    root = _panel_root(
        client.post(reverse("todo:login"), {"username": "ada", "password": "wrong"}),
        status=422,
    )

    assert _optin_switch(root).attrib["value"] == "off"


def test_the_optin_switch_is_off_by_default_and_the_probe_never_selects_it(client):
    # A stored key names a DEVICE, not a person. Pre-selecting the switch from it
    # enrolled whoever signed in next on a shared phone, without ever asking them.
    root = _login_screen(client)

    probe = root.find(".//hv:view[@id='login-panel']/hv:behavior", NS)
    assert "checked-target" not in probe.attrib
    switch = _optin_switch(root)
    assert switch is not None
    assert switch.attrib["name"] == "enable_biometrics"
    assert switch.attrib["value"] == "off"


def test_the_rejected_panel_pre_selects_the_optin_switch(client, user):
    # This panel only exists in response to a presented token, so the user
    # demonstrably wanted biometrics. Leaving the switch off turned one rejected
    # token into a silent, permanent un-enrolment.
    response = client.post(
        reverse("todo:biometric-login"), {"biometric_token": "wrong"}
    )

    assert _optin_switch(_panel_root(response, status=401)).attrib["value"] == "on"


def test_the_throttled_panel_leaves_the_optin_switch_off(client, user):
    # A rate-limited request says nothing about whether the user wanted biometrics,
    # and nothing else pre-selects the switch, so enrolling stays an explicit act.
    _throttle("wrong")

    response = client.post(
        reverse("todo:biometric-login"), {"biometric_token": "wrong"}
    )

    assert _optin_switch(_panel_root(response, status=429)).attrib["value"] == "off"


def test_an_expired_credential_sends_the_user_to_a_pre_selected_reset_panel(
    client, user
):
    raw = issue_biometric_token(user=user)
    BiometricCredential.objects.update(
        created_at=timezone.now() - BIOMETRIC_TOKEN_TTL - timedelta(seconds=1)
    )

    root = _panel_root(
        client.post(reverse("todo:biometric-login"), {"biometric_token": raw}),
        status=401,
    )

    assert _optin_switch(root).attrib["value"] == "on"
    store = root.find("./hv:behavior[@action='store-biometric-token']", NS)
    assert store.attrib["token"] == ""


def test_the_optin_row_ships_a_single_line_of_copy(client):
    # The owner removed the enrolment warning deliberately. One line, and no room
    # for a future agent to quietly reinstate a second.
    row = _login_screen(client).find(".//hv:view[@id='biometric-optin']", NS)

    labels = row.findall("./hv:text", NS)
    assert len(labels) == 1
    assert labels[0].text == "Unlock with biometrics next time"
    assert "Anyone whose face" not in ElementTree.tostring(row, encoding="unicode")


# The 72x72 RGBA export of face-id.png and fingerprint.png is asserted with every
# other icon by the directory-wide convention test in test_forms_ui.py. Neither
# has a colour assertion anywhere on purpose: biometric-icon sets tintColor, which
# repaints every non-transparent pixel (stylesheets/index.ts:195), so what these
# two were exported in never reaches the screen. The tint itself is asserted by
# the two contrast tests above.


def test_the_biometric_button_ships_both_icon_variants_hidden(client):
    button = _login_screen(client).find(".//hv:view[@id='biometric-signin']", NS)
    icons = button.findall("./hv:image", NS)

    assert len(icons) == 2
    for icon in icons:
        assert icon.attrib["hide"] == "true"
        assert icon.attrib["alt"]
        # NO id, deliberately. createProps spreads the id-derived test props LAST
        # (hyperview/src/services/index.ts:161) and createTestPropsFromId returns
        # {accessibilityLabel: id} on Android (:84), so an id would overwrite the
        # label RN takes from alt (react-native Image.android.js:260-263) and
        # TalkBack would announce the slug instead of the copy.
        assert "id" not in icon.attrib
    assert {icon.attrib["variant"] for icon in icons} == {"face", "fingerprint"}
    assert len({icon.attrib["source"] for icon in icons}) == 2
    # The label is gone for good: it could not vary by modality without an id.
    assert button.findall("./hv:text", NS) == []
