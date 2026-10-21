"""Push registration is bound to the authenticated cookie session, not JSON identity."""

import json
from uuid import UUID, uuid4

import pytest
from django.conf import settings
from django.contrib.sessions.models import Session
from django.test import Client
from django.utils import timezone

from todo.models import PushDevice

pytestmark = pytest.mark.django_db
PATH = "/hv/push-registrations/"
STATE = "/hv/session-state/"
CONTRACT = "X-HyperTodo-Client-Contract"
EXPECTED = "X-HyperTodo-Expected-Session"
TOKEN = "ExpoPushToken[fixture_one]"


def _headers(binding, csrf=None):
    headers = {CONTRACT: "realtime-v1", EXPECTED: binding}
    if csrf is not None:
        headers["X-CSRFToken"] = csrf
    return headers


def _bootstrap(user=None):
    client = Client(enforce_csrf_checks=True)
    if user is not None:
        client.force_login(user)
    state = client.get(STATE, headers={CONTRACT: "realtime-v1"}).json()
    binding = state["binding"]
    response = client.get(PATH, headers=_headers(binding))
    return client, binding, response


def _register(client, binding, csrf, installation=None, token=TOKEN, **extra):
    payload = {
        "installationId": str(installation or uuid4()),
        "expoPushToken": token,
        **extra,
    }
    return client.post(
        PATH,
        data=json.dumps(payload),
        content_type="application/json",
        headers=_headers(binding, csrf),
    )


def test_bootstrap_requires_modern_authenticated_session(user):
    _, _, anonymous = _bootstrap()
    assert anonymous.status_code == 401
    assert "csrfToken" not in anonymous.content.decode()
    client, binding, bootstrap = _bootstrap(user)
    assert bootstrap.status_code == 200
    assert set(bootstrap.json()) == {"csrfToken"}
    assert bootstrap.json()["csrfToken"]
    assert "no-store" in bootstrap["Cache-Control"]
    assert "cookie" in bootstrap["Vary"].lower()
    assert client.get(PATH).status_code == 404
    assert not PushDevice.objects.exists()
    assert binding == bootstrap["X-HyperTodo-Session-Binding"]


def test_registration_rejects_missing_csrf_and_stale_binding(user):
    client, binding, bootstrap = _bootstrap(user)
    assert bootstrap.status_code == 200
    missing_csrf = _register(client, binding, None)
    assert missing_csrf.status_code == 403
    stale = _register(client, "hvs1." + "A" * 43, bootstrap.json()["csrfToken"])
    assert stale.status_code == 409
    assert not PushDevice.objects.exists()


def test_registration_rotates_same_installation_and_never_returns_token(user):
    client, binding, bootstrap = _bootstrap(user)
    installation = uuid4()
    first = _register(
        client, binding, bootstrap.json()["csrfToken"], installation=installation
    )
    assert first.status_code == 201
    assert first.json()["registered"] is True
    first_version = first.json()["registrationVersion"]
    assert first_version
    assert TOKEN not in first.content.decode()
    device = PushDevice.objects.get()
    assert device.user == user
    assert device.session_id == client.session.session_key
    assert device.installation_id == installation
    assert device.expo_token == TOKEN
    second = _register(
        client,
        binding,
        bootstrap.json()["csrfToken"],
        installation=installation,
        token="ExponentPushToken[fixture_two]",
        registrationVersion=first_version,
    )
    assert second.status_code == 200
    assert second.json()["registrationVersion"] != first_version
    assert PushDevice.objects.count() == 1
    device.refresh_from_db()
    assert device.expo_token == "ExponentPushToken[fixture_two]"


def test_client_cannot_claim_user_or_send_malformed_registration(user, other_user):
    client, binding, bootstrap = _bootstrap(user)
    csrf = bootstrap.json()["csrfToken"]
    assert _register(client, binding, csrf, userId=other_user.pk).status_code == 400
    assert (
        _register(client, binding, csrf, token="not-an-expo-token").status_code == 400
    )
    assert (
        _register(client, binding, csrf, installation="not-a-uuid").status_code == 400
    )
    assert not PushDevice.objects.exists()


def test_new_account_claiming_same_installation_revokes_prior_owner(user, other_user):
    first, first_binding, first_bootstrap = _bootstrap(user)
    installation = uuid4()
    assert (
        _register(
            first,
            first_binding,
            first_bootstrap.json()["csrfToken"],
            installation=installation,
        ).status_code
        == 201
    )
    second, second_binding, second_bootstrap = _bootstrap(other_user)
    assert (
        _register(
            second,
            second_binding,
            second_bootstrap.json()["csrfToken"],
            installation=installation,
            token="ExpoPushToken[new_account]",
        ).status_code
        == 409
    )
    assert PushDevice.objects.get().user == user
    first.post(
        "/hv/logout/",
        headers=_headers(first_binding, first_bootstrap.json()["csrfToken"]),
    )
    assert (
        _register(
            second,
            second_binding,
            second_bootstrap.json()["csrfToken"],
            installation=installation,
            token="ExpoPushToken[new_account]",
        ).status_code
        == 201
    )
    assert PushDevice.objects.count() == 1
    assert PushDevice.objects.get().user == other_user


def test_revoke_is_scoped_to_current_session_and_logout_cascades(user):
    first, binding, bootstrap = _bootstrap(user)
    installation = uuid4()
    csrf = bootstrap.json()["csrfToken"]
    registered = _register(first, binding, csrf, installation=installation)
    assert registered.status_code == 201
    version = registered.json()["registrationVersion"]
    second, second_binding, second_bootstrap = _bootstrap(user)
    foreign = second.delete(
        PATH,
        data=json.dumps(
            {"installationId": str(installation), "registrationVersion": version}
        ),
        content_type="application/json",
        headers=_headers(second_binding, second_bootstrap.json()["csrfToken"]),
    )
    assert foreign.status_code == 204
    assert PushDevice.objects.count() == 1
    response = first.delete(
        PATH,
        data=json.dumps(
            {"installationId": str(installation), "registrationVersion": version}
        ),
        content_type="application/json",
        headers=_headers(binding, csrf),
    )
    assert response.status_code == 204
    assert not PushDevice.objects.exists()
    assert _register(first, binding, csrf, installation=installation).status_code == 201
    first.post("/hv/logout/", headers=_headers(binding, csrf))
    assert not PushDevice.objects.exists()


def test_deleted_session_leaves_no_registration(user):
    client, binding, bootstrap = _bootstrap(user)
    csrf = bootstrap.json()["csrfToken"]
    assert _register(client, binding, csrf).status_code == 201
    session_key = client.session.session_key
    Session.objects.filter(session_key=session_key).delete()
    assert not PushDevice.objects.exists()
    assert _register(client, binding, csrf).status_code == 409
    assert not PushDevice.objects.exists()


def test_registration_closes_when_session_invalidates_inside_request(user, monkeypatch):
    client, binding, bootstrap = _bootstrap(user)
    monkeypatch.setattr("todo.push_registration.fresh_identity", lambda _key: None)
    response = _register(client, binding, bootstrap.json()["csrfToken"])
    assert response.status_code == 409
    assert not PushDevice.objects.exists()


def test_device_limit_and_token_transfer_are_bounded(user):
    client, binding, bootstrap = _bootstrap(user)
    csrf = bootstrap.json()["csrfToken"]
    for index in range(10):
        response = _register(
            client, binding, csrf, token=f"ExpoPushToken[fixture_{index}]"
        )
        assert response.status_code == 201
    assert PushDevice.objects.count() == 10
    assert (
        _register(client, binding, csrf, token="ExpoPushToken[overflow]").status_code
        == 429
    )
    assert PushDevice.objects.count() == 10


def test_token_transfer_requires_revoking_old_installation(user):
    client, binding, bootstrap = _bootstrap(user)
    csrf = bootstrap.json()["csrfToken"]
    assert _register(client, binding, csrf).status_code == 201
    assert _register(client, binding, csrf).status_code == 409
    assert PushDevice.objects.count() == 1


def test_invalid_body_and_method_do_not_write(user):
    client, binding, bootstrap = _bootstrap(user)
    csrf = bootstrap.json()["csrfToken"]
    assert client.put(PATH, headers=_headers(binding, csrf)).status_code == 405
    oversized = client.post(
        PATH,
        data=json.dumps({"installationId": str(uuid4()), "expoPushToken": "x" * 1025}),
        content_type="application/json",
        headers=_headers(binding, csrf),
    )
    assert oversized.status_code == 400
    assert not PushDevice.objects.exists()


def test_stale_revision_cannot_rotate_or_revoke_new_token(user):
    client, binding, bootstrap = _bootstrap(user)
    csrf = bootstrap.json()["csrfToken"]
    installation = uuid4()
    first = _register(client, binding, csrf, installation=installation)
    old_version = first.json()["registrationVersion"]
    second = _register(
        client,
        binding,
        csrf,
        installation=installation,
        token="ExpoPushToken[rotated]",
        registrationVersion=old_version,
    )
    assert second.status_code == 200
    new_version = second.json()["registrationVersion"]
    assert new_version != old_version
    assert (
        _register(
            client,
            binding,
            csrf,
            installation=installation,
            token="ExpoPushToken[late]",
            registrationVersion=old_version,
        ).status_code
        == 409
    )
    client.delete(
        PATH,
        data=json.dumps(
            {"installationId": str(installation), "registrationVersion": old_version}
        ),
        content_type="application/json",
        headers=_headers(binding, csrf),
    )
    assert PushDevice.objects.get().expo_token == "ExpoPushToken[rotated]"
    assert PushDevice.objects.get().registration_version == UUID(new_version)


def test_same_account_login_rotation_can_reregister(user):
    client, binding, bootstrap = _bootstrap(user)
    installation = uuid4()
    assert (
        _register(
            client, binding, bootstrap.json()["csrfToken"], installation
        ).status_code
        == 201
    )
    old_key = client.session.session_key
    session = client.session
    session.cycle_key()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
    assert client.session.session_key != old_key
    assert not PushDevice.objects.exists()
    new_binding = client.get(STATE, headers={CONTRACT: "realtime-v1"}).json()["binding"]
    new_bootstrap = client.get(PATH, headers=_headers(new_binding))
    assert (
        _register(
            client,
            new_binding,
            new_bootstrap.json()["csrfToken"],
            installation,
        ).status_code
        == 201
    )
    assert PushDevice.objects.get().session_id == client.session.session_key


def test_expired_old_session_token_can_be_reclaimed_after_reinstall(user, other_user):
    first, binding, bootstrap = _bootstrap(user)
    assert _register(first, binding, bootstrap.json()["csrfToken"]).status_code == 201
    old_key = first.session.session_key
    Session.objects.filter(session_key=old_key).update(expire_date=timezone.now())
    from todo.realtime_auth import fresh_identity

    assert fresh_identity(old_key) is None
    second, binding, bootstrap = _bootstrap(other_user)
    response = _register(second, binding, bootstrap.json()["csrfToken"])
    assert response.status_code == 201, response.json()
    assert PushDevice.objects.count() == 1
    assert PushDevice.objects.get().user == other_user


def test_bootstrap_can_recover_current_session_revision(user):
    client, binding, bootstrap = _bootstrap(user)
    installation = uuid4()
    created = _register(client, binding, bootstrap.json()["csrfToken"], installation)
    recovered = client.get(
        PATH,
        {"installationId": str(installation)},
        headers=_headers(binding),
    )
    assert recovered.status_code == 200
    assert (
        recovered.json()["registrationVersion"] == created.json()["registrationVersion"]
    )
    assert (
        client.get(
            PATH, {"installationId": "bad"}, headers=_headers(binding)
        ).status_code
        == 400
    )
