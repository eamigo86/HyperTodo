"""Cookie-owned realtime negotiation and pre-business-write session guards."""

import base64
import json
import re
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.crypto import constant_time_compare, salted_hmac

from tests.test_hxml_views import assert_hxml, token_from
from todo.context_processors import THEME_COOKIE
from todo.models import BiometricCredential, Task
from todo.services import issue_biometric_token
from todo.views import BIOMETRIC_ATTEMPT_LIMIT

pytestmark = pytest.mark.django_db
CONTRACT = "X-HyperTodo-Client-Contract"
EXPECTED = "X-HyperTodo-Expected-Session"
BINDING = "X-HyperTodo-Session-Binding"
OUTCOME = "X-HyperTodo-Auth-Outcome"
STATE = "/hv/session-state/"
FORMAT = re.compile(r"hvs1\.[A-Za-z0-9_-]{43}")
NS = {"hv": "https://hyperview.org/hyperview"}


def _expected_binding(user=None, key=None):
    identity = (
        [1, user._state.db, str(user.pk), key]
        if user is not None
        else [1, None, None, None]
    )
    payload = json.dumps(identity, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    digest = salted_hmac(
        "hypertodo.session-binding.v1", payload, algorithm="sha256"
    ).digest()
    return "hvs1." + base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _headers(binding=None):
    headers = {CONTRACT: "realtime-v1"}
    if binding is not None:
        headers[EXPECTED] = binding
    return headers


def _confirm(client, authenticated):
    response = client.get(STATE, headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"version", "authenticated", "binding"}
    assert body["version"] == 1
    assert body["authenticated"] is authenticated
    assert FORMAT.fullmatch(body["binding"])
    assert response[BINDING] == body["binding"]
    assert len(response.content) <= 1024
    assert "no-store" in response["Cache-Control"]
    assert "cookie" in response["Vary"].lower()
    assert OUTCOME not in response
    return body["binding"], response


def _json_error(response, status, code):
    assert response.status_code == status
    assert response.json() == {"error": code}
    assert len(response.content) <= 1024
    assert "no-store" in response["Cache-Control"]
    assert BINDING not in response
    assert OUTCOME not in response


def test_anonymous_confirmation_is_exact_stable_and_creates_nothing(client):
    with CaptureQueriesContext(connection) as queries:
        first, response = _confirm(client, False)
        second, _ = _confirm(client, False)
    assert first == second == _expected_binding()
    assert not queries.captured_queries
    assert not response.cookies
    assert not client.cookies
    assert not Session.objects.exists()


def test_authenticated_confirmation_has_exact_hmac_and_no_writes(
    client, user, settings
):
    settings.SECRET_KEY = "session-contract-fixture-only-secret"
    client.force_login(user)
    key = client.session.session_key
    last_login = user.last_login
    with CaptureQueriesContext(connection) as queries:
        first, response = _confirm(client, True)
        second, _ = _confirm(client, True)
    assert first == second == _expected_binding(user, key)
    assert not any(
        q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for q in queries
    )
    assert not response.cookies
    wire = response.content.decode() + str(dict(response.headers))
    for private in (key, user.username, settings.SECRET_KEY):
        assert private not in wire
    user.refresh_from_db()
    assert user.last_login == last_login


def test_confirmation_ignores_claimed_owner_and_expected_binding(client, user):
    client.force_login(user)
    expected = _expected_binding(user, client.session.session_key)
    response = client.get(
        STATE,
        {"owner": "someone-else", "alias": "foreign"},
        headers={**_headers("malformed"), "X-HyperTodo-User": "foreign"},
    )
    assert response.status_code == 200
    assert response.json()["binding"] == expected


def test_anonymous_existing_session_is_not_identity(client):
    session = client.session
    session["preference"] = "not-authentication"
    session.save()
    assert _confirm(client, False)[0] == _expected_binding()
    assert client.session["preference"] == "not-authentication"


def test_sessions_and_users_have_distinct_bindings(user, other_user):
    bindings = []
    for account in (user, user, other_user):
        client = Client()
        client.force_login(account)
        bindings.append(_confirm(client, True)[0])
    assert len(set(bindings)) == 3


def test_session_rotation_changes_binding(client, user):
    client.force_login(user)
    before, _ = _confirm(client, True)
    session = client.session
    session.cycle_key()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
    after, _ = _confirm(client, True)
    assert after == _expected_binding(user, session.session_key) != before


@pytest.mark.parametrize("reason", ["deactivated", "password-revoked", "deleted"])
def test_invalidated_auth_becomes_anonymous_without_private_data(client, user, reason):
    client.force_login(user)
    previous, _ = _confirm(client, True)
    old_key = client.session.session_key
    if reason == "deactivated":
        user.is_active = False
        user.save(update_fields=["is_active"])
    elif reason == "password-revoked":
        user.set_password("changed-after-session")
        user.save(update_fields=["password"])
    else:
        user.delete()
    assert _confirm(client, False)[0] == _expected_binding() != previous
    _json_error(
        client.get("/hv/tasks/", headers=_headers(previous)),
        409,
        "session-binding-mismatch",
    )
    if reason == "password-revoked":
        assert not Session.objects.filter(session_key=old_key).exists()


def test_django_fallback_auth_hash_rotation_remains_intact(client, user, settings):
    old_secret = settings.SECRET_KEY
    client.force_login(user)
    key = client.session.session_key
    settings.SECRET_KEY = "rotated-test-secret"
    settings.SECRET_KEY_FALLBACKS = [old_secret]
    binding, _ = _confirm(client, True)
    assert client.session.session_key != key
    assert binding == _expected_binding(user, client.session.session_key)
    assert _confirm(client, True)[0] == binding


@pytest.mark.parametrize(
    "method", ["post", "put", "patch", "delete", "head", "options"]
)
def test_confirmation_accepts_only_get(client, method):
    response = getattr(client, method)(STATE, headers=_headers())
    assert response.status_code == 405
    assert response["Allow"] == "GET"
    assert not Session.objects.exists()
    assert OUTCOME not in response


def test_confirmation_post_is_405_even_with_enforced_csrf():
    assert (
        Client(enforce_csrf_checks=True).post(STATE, headers=_headers()).status_code
        == 405
    )


@pytest.mark.parametrize("method", ["get", "post"])
def test_confirmation_is_404_for_legacy(client, method):
    assert getattr(client, method)(STATE).status_code == 404


@pytest.mark.parametrize(
    "value",
    ["", " ", "realtime-v2", "Realtime-v1", "realtime-v1 ", "realtime-v1,realtime-v1"],
)
def test_unknown_contract_fails_before_business_view(client, value):
    with CaptureQueriesContext(connection) as queries:
        response = client.get("/hv/tasks/", headers={CONTRACT: value})
    _json_error(response, 400, "unsupported-client-contract")
    assert not queries.captured_queries


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "hvs1." + "a" * 42,
        "hvs1." + "a" * 44,
        "hvs1." + "a" * 42 + "=",
        "hvs1." + "a" * 42 + "/",
        "hvs1." + "a" * 42 + "é",
        "hvs1." + "a" * 43 + "\n",
    ],
)
def test_expected_binding_format_is_strict(client, value):
    _json_error(
        client.get("/hv/tasks/", headers=_headers(value)),
        400,
        "invalid-session-binding",
    )


def test_mismatch_precedes_business_queries_and_writes(client, user, other_user):
    client.force_login(user)
    task = Task.objects.create(user=user, title="Private fixture task")
    foreign = Client()
    foreign.force_login(other_user)
    unexpected, _ = _confirm(foreign, True)
    with CaptureQueriesContext(connection) as queries:
        response = client.post(
            reverse("todo:task-toggle", args=[task.pk]), headers=_headers(unexpected)
        )
    _json_error(response, 409, "session-binding-mismatch")
    assert not any("todo_" in q["sql"].lower() for q in queries)
    task.refresh_from_db()
    assert task.completed_at is None
    assert task.title.encode() not in response.content
    assert _expected_binding(user, client.session.session_key) not in str(
        response.headers
    )


def test_guard_uses_constant_time_comparison(client):
    with patch(
        "todo.session_contract.constant_time_compare", wraps=constant_time_compare
    ) as compare:
        response = client.get("/hv/", headers=_headers(_expected_binding()))
    assert response.status_code == 200
    compare.assert_called_once_with(_expected_binding(), _expected_binding())


def test_binding_never_authenticates_or_grants_object_permission(
    client, user, other_user
):
    anonymous, _ = _confirm(client, False)
    denied = client.get("/hv/tasks/", headers=_headers(anonymous))
    assert denied.status_code == 401
    assert denied[BINDING] == anonymous
    assert OUTCOME not in denied
    client.force_login(user)
    mine, _ = _confirm(client, True)
    task = Task.objects.create(user=other_user, title="Other owner's task")
    denied = client.post(
        reverse("todo:task-toggle", args=[task.pk]), headers=_headers(mine)
    )
    assert denied.status_code == 404
    assert denied[BINDING] == mine
    task.refresh_from_db()
    assert task.completed_at is None


def test_valid_mutation_retains_binding_without_auth_outcome(client, user):
    client.force_login(user)
    mine, _ = _confirm(client, True)
    task = Task.objects.create(user=user, title="Mine")
    response = client.post(
        reverse("todo:task-toggle", args=[task.pk]), headers=_headers(mine)
    )
    assert_hxml(response)
    assert response[BINDING] == mine
    assert OUTCOME not in response
    task.refresh_from_db()
    assert task.completed_at is not None


def test_legacy_and_admin_are_unchanged(client, admin_client):
    legacy = client.get("/hv/login/", headers={EXPECTED: "garbage"})
    assert_hxml(legacy)
    assert BINDING not in legacy
    assert OUTCOME not in legacy
    admin = admin_client.get(
        "/admin/", headers={CONTRACT: "unknown", EXPECTED: "garbage"}
    )
    assert admin.status_code == 200
    assert BINDING not in admin
    assert OUTCOME not in admin


def test_csrf_denial_stays_403_without_auth_outcome(user):
    client = Client(enforce_csrf_checks=True)
    anonymous, _ = _confirm(client, False)
    response = client.post(
        "/hv/login/",
        {"username": user.username, "password": "correct-horse"},
        headers=_headers(anonymous),
    )
    assert response.status_code == 403
    assert response[BINDING] == anonymous
    assert OUTCOME not in response
    assert _confirm(client, False)[0] == anonymous


@pytest.mark.parametrize("optin", ["on", "off"])
def test_password_success_preserves_csrf_and_effect_returns_result_binding(user, optin):
    client = Client(enforce_csrf_checks=True)
    anonymous, _ = _confirm(client, False)
    login_form = client.get("/hv/login/", headers=_headers(anonymous))
    response = client.post(
        "/hv/login/",
        {
            "username": user.username,
            "password": "correct-horse",
            "enable_biometrics": optin,
            "csrfmiddlewaretoken": token_from(login_form),
        },
        headers=_headers(anonymous),
    )
    tree = assert_hxml(response)
    assert response[OUTCOME] == "password-ok"
    assert response[BINDING] == _confirm(client, True)[0] != anonymous
    effect = tree.find("./hv:behavior[@action='store-biometric-token']", NS)
    assert effect is not None
    token = effect.attrib["token"]
    assert bool(token) is (optin == "on")
    assert BiometricCredential.objects.filter(user=user).exists() is (optin == "on")
    if token:
        assert token not in str(dict(response.headers))


@pytest.mark.parametrize(
    "payload",
    [{}, {"username": "ada", "password": "incorrect", "enable_biometrics": "on"}],
)
def test_password_failure_keeps_binding_and_422_panel(client, user, payload):
    anonymous, _ = _confirm(client, False)
    response = client.post("/hv/login/", payload, headers=_headers(anonymous))
    tree = assert_hxml(response, status=422)
    assert tree.attrib["id"] == "login-panel"
    assert response[OUTCOME] == "password-invalid"
    assert response[BINDING] == anonymous
    assert not BiometricCredential.objects.exists()


def test_password_account_switch_compares_incoming_and_returns_new_binding(
    client, user, other_user
):
    client.force_login(user)
    first, _ = _confirm(client, True)
    response = client.post(
        "/hv/login/",
        {"username": other_user.username, "password": "correct-horse"},
        headers=_headers(first),
    )
    assert response.status_code == 200
    assert response[OUTCOME] == "password-ok"
    assert response[BINDING] == _confirm(client, True)[0] != first
    assert client.session["_auth_user_id"] == str(other_user.pk)


def test_mismatched_auth_post_cannot_switch_or_rotate(client, user, other_user):
    client.force_login(user)
    key = client.session.session_key
    response = client.post(
        "/hv/login/",
        {"username": other_user.username, "password": "correct-horse"},
        headers=_headers(_expected_binding()),
    )
    _json_error(response, 409, "session-binding-mismatch")
    assert client.session.session_key == key
    assert client.session["_auth_user_id"] == str(user.pk)


def test_biometric_success_rotates_token_and_returns_result_binding(client, user):
    raw = issue_biometric_token(user=user)
    anonymous, _ = _confirm(client, False)
    response = client.post(
        "/hv/biometric/login/", {"biometric_token": raw}, headers=_headers(anonymous)
    )
    tree = assert_hxml(response)
    assert response[OUTCOME] == "biometric-ok"
    assert response[BINDING] == _confirm(client, True)[0] != anonymous
    rotated = tree.find("./hv:behavior[@action='store-biometric-token']", NS).attrib[
        "token"
    ]
    assert rotated and rotated != raw
    assert raw not in str(dict(response.headers))
    assert rotated not in str(dict(response.headers))


def test_biometric_failure_and_throttle_remain_distinct(client):
    anonymous, _ = _confirm(client, False)
    for _ in range(BIOMETRIC_ATTEMPT_LIMIT):
        response = client.post(
            "/hv/biometric/login/",
            {"biometric_token": "fixture-invalid"},
            headers=_headers(anonymous),
        )
        tree = assert_hxml(response, status=401)
        assert response[OUTCOME] == "biometric-invalid"
        assert response[BINDING] == anonymous
        assert (
            tree.find("./hv:behavior[@action='store-biometric-token']", NS) is not None
        )
    response = client.post(
        "/hv/biometric/login/",
        {"biometric_token": "fixture-invalid"},
        headers=_headers(anonymous),
    )
    tree = assert_hxml(response, status=429)
    assert response[OUTCOME] == "biometric-throttled"
    assert response[BINDING] == anonymous
    assert tree.find("./hv:behavior[@action='store-biometric-token']", NS) is None


def test_logout_returns_anonymous_and_keeps_enrollment(client, user):
    issue_biometric_token(user=user)
    client.force_login(user)
    before, _ = _confirm(client, True)
    client.cookies[THEME_COOKIE] = "dark"
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = "es"
    response = client.post("/hv/logout/", headers=_headers(before))
    assert_hxml(response)
    assert response[OUTCOME] == "logout-ok"
    assert response[BINDING] == _confirm(client, False)[0] != before
    assert BiometricCredential.objects.filter(user=user).exists()
    for cookie in (THEME_COOKIE, settings.LANGUAGE_COOKIE_NAME):
        assert response.cookies[cookie]["max-age"] == 0


@pytest.mark.parametrize("path", ["/hv/login/", "/hv/logout/", "/hv/biometric/login/"])
def test_auth_gets_and_legacy_posts_have_no_modern_outcome(client, path):
    anonymous, _ = _confirm(client, False)
    response = client.get(path, headers=_headers(anonymous))
    assert OUTCOME not in response
    assert BINDING in response
    legacy = client.post(path, {})
    assert BINDING not in legacy
    assert OUTCOME not in legacy


def test_guard_and_finalizer_surround_django_session_persistence(settings):
    middleware = settings.MIDDLEWARE
    assert middleware.index(
        "todo.session_middleware.SessionBindingResponseMiddleware"
    ) < middleware.index("django.contrib.sessions.middleware.SessionMiddleware")
    assert (
        middleware.index("django.contrib.auth.middleware.AuthenticationMiddleware")
        < middleware.index("todo.session_middleware.SessionContractMiddleware")
        < middleware.index("todo.middleware.ProfileLanguageMiddleware")
    )


def test_failed_session_persistence_cannot_claim_success_or_result_binding(
    client, user, other_user
):
    from django.contrib.sessions.backends.base import UpdateError

    client.force_login(user)
    incoming, _ = _confirm(client, True)
    with patch(
        "django.contrib.sessions.backends.db.SessionStore.save", side_effect=UpdateError
    ):
        response = client.post(
            "/hv/login/",
            {"username": other_user.username, "password": "correct-horse"},
            headers=_headers(incoming),
        )
    assert response.status_code == 400
    assert OUTCOME not in response
    assert BINDING not in response


def test_settings_credential_clear_is_same_session_not_authentication(client, user):
    issue_biometric_token(user=user)
    client.force_login(user)
    binding, _ = _confirm(client, True)
    response = client.post(
        "/hv/settings/",
        {"first_name": "Ada", "last_name": "", "email": "", "biometric_unlock": "off"},
        headers=_headers(binding),
    )
    tree = assert_hxml(response)
    assert response[BINDING] == binding == _confirm(client, True)[0]
    assert OUTCOME not in response
    assert not BiometricCredential.objects.filter(user=user).exists()
    effect = tree.find("./hv:behavior[@action='store-biometric-token']", NS)
    assert effect is not None and effect.attrib["token"] == ""
