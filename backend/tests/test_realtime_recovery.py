"""Neutral Sign in presentation never adopts the actual unexpected cookie owner."""

from xml.etree import ElementTree as ET
from xml.etree.ElementTree import Element

import pytest
from dj_hyperview import validate_hyperview_schema
from dj_hyperview.contrib.database.services import publish_template
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.messages import INFO
from django.contrib.messages.storage.session import SessionStorage
from django.db import connection
from django.http import HttpResponse
from django.test import Client, RequestFactory
from django.test.utils import CaptureQueriesContext
from pytest_django.fixtures import Settings

from tests.test_session_contract import (
    BINDING,
    CONTRACT,
    EXPECTED,
    OUTCOME,
    _confirm,
    _headers,
)
from todo.models import BiometricCredential, Profile, Task
from todo.services import issue_biometric_token
from todo.throttle import BIOMETRIC_ATTEMPT_LIMIT

pytestmark = pytest.mark.django_db
RECOVERY = "X-HyperTodo-Recovery"
ROOT = "/hv/recovery/"
LOGIN = ROOT + "?screen=login"
HV = "https://hyperview.org/hyperview"
NS = {"hv": HV}


def headers(client: Client, **extra: object) -> dict[str, str]:
    """Build the headers of a recovery request for the current session of the client.

    Args:
        client: Client whose session the binding is confirmed for.
        **extra: Further request headers merged over the defaults.

    Returns:
        The contract, binding, recovery and request id headers plus the extras.
    """
    binding, _ = _confirm(client, client.session.get("_auth_user_id") is not None)
    return {
        **_headers(binding),
        RECOVERY: "login-v1",
        "X-HyperTodo-Request-ID": "gate-recovery-1",
        **extra,
    }


def xml(response: HttpResponse, status: int = 200) -> Element:
    """Check that a response is a valid Hyperview document and parse it.

    Args:
        response: Response that must carry a Hyperview document.
        status: Status code the response must have.

    Returns:
        The root element of the response body.
    """
    assert response.status_code == status
    assert response["Content-Type"].startswith("application/vnd.hyperview")
    validate_hyperview_schema(response.content.decode())
    assert "X-HyperTodo-Theme" not in response
    assert response["Content-Language"] == settings.LANGUAGE_CODE
    assert "no-store" in response["Cache-Control"]
    return ET.fromstring(response.content)


def csrf(root: Element) -> str:
    """Return the CSRF token shared by the two forms of the document.

    Args:
        root: Parsed recovery document.

    Returns:
        The CSRF token that both forms share.
    """
    values = root.findall(".//hv:text-field[@name='csrfmiddlewaretoken']", NS)
    assert len(values) == 2
    assert all(len(node.attrib["value"]) == 64 for node in values)
    assert len({node.attrib["value"] for node in values}) == 1
    return values[0].attrib["value"]


@pytest.mark.parametrize("authenticated", (False, True))
def test_recovery_uses_real_public_navigator_and_original_cookie_csrf(
    user: AbstractUser, authenticated: bool
) -> None:
    """Recovery uses the real public navigator and the cookie session's CSRF token.

    Args:
        user: Signed-in user who owns the data in this test.
        authenticated: Whether the original request belongs to a signed-in session.
    """
    client = Client(enforce_csrf_checks=True)
    if authenticated:
        Profile.objects.create(user=user, theme="dark", language="es")
        client.force_login(user)
    head = headers(client)
    before_key = client.session.session_key
    root_response = client.get(ROOT, headers=head)
    root = xml(root_response)
    assert root.tag == f"{{{HV}}}doc"
    route = root.find("hv:navigator/hv:nav-route", NS)
    assert route.attrib == {"id": "root-route", "href": LOGIN, "selected": "true"}
    response = client.get(route.attrib["href"], headers=head)
    panel = xml(response)
    assert panel.find("hv:screen", NS).attrib["id"] == "login-screen"
    assert client.session.session_key == before_key
    token = csrf(panel)
    invalid = client.post(
        "/hv/login/",
        {"username": "missing", "password": "incorrect", "csrfmiddlewaretoken": token},
        headers=head,
    )
    error = xml(invalid, 422)
    assert invalid[OUTCOME] == "password-invalid"
    assert invalid[BINDING] == head[EXPECTED]
    assert csrf(error)
    assert error.attrib["key"] == "auth-panel-gate-recovery-1"


PROBE = (
    '<text id="probe">user={{ user.username }};'
    "request_user={{ request.user.username }};"
    "session={{ request.session.private_value }};"
    "meta={{ request.META.HTTP_X_PRIVATE }};"
    "cookie={{ request.COOKIES.private_cookie }};"
    "messages={% for message in messages %}{{ message }}{% endfor %};"
    "password={{ form.data.password }};field_password={{ form.password.value }};"
    "post={{ request.POST.password }};username={{ form.username.value }}</text>"
)


@pytest.mark.parametrize("fragment", (False, True))
def test_database_templates_never_receive_original_request_or_bound_password(
    user: AbstractUser, fragment: bool
) -> None:
    """Database templates never receive the original request or the bound password.

    Args:
        user: Signed-in user who owns the data in this test.
        fragment: Whether the template is rendered as a fragment.
    """
    client = Client()
    Profile.objects.create(user=user, theme="dark", language="es")
    client.force_login(user)
    session = client.session
    session["private_value"] = "PRIVATE_SESSION_SENTINEL"
    message_request = RequestFactory().get("/test-only/")
    message_request.session = session
    storage = SessionStorage(message_request)
    storage.add(INFO, "PRIVATE_MESSAGE_SENTINEL")
    storage.update(HttpResponse())
    session.save()
    stored_messages = session["_messages"]
    client.cookies["private_cookie"] = "PRIVATE_COOKIE_SENTINEL"
    head = headers(client)
    head["X-Private"] = "PRIVATE_META_SENTINEL"
    name = "fragments/login_panel.xml" if fragment else "screens/login.xml"
    source = (
        f'<view xmlns="{HV}" id="login-panel">{PROBE}</view>'
        if fragment
        else f'<doc xmlns="{HV}"><screen><body>{PROBE}</body></screen></doc>'
    )
    publish_template(name, source)
    if fragment:
        response = client.post(
            "/hv/login/",
            {"username": "public-attempt", "password": "PRIVATE_PASSWORD_SENTINEL"},
            headers=head,
        )
    else:
        response = client.get(LOGIN, headers=head)
    value = response.content.decode()
    xml(response, 422 if fragment else 200)
    for secret in (
        user.username,
        "PRIVATE_SESSION_SENTINEL",
        "PRIVATE_META_SENTINEL",
        "PRIVATE_COOKIE_SENTINEL",
        "PRIVATE_PASSWORD_SENTINEL",
        "PRIVATE_MESSAGE_SENTINEL",
    ):
        assert secret not in value
    assert ("public-attempt" in value) is fragment
    assert not response._request.user.is_authenticated
    assert response._request.COOKIES == {}
    assert response._request.session == {}
    assert not response._request.META
    assert client.session["_messages"] == stored_messages


def test_neutral_requests_do_not_query_profile_or_publish_theme(
    user: AbstractUser,
) -> None:
    """Neutral requests neither query the profile nor publish a theme.

    Args:
        user: Signed-in user who owns the data in this test.
    """
    Profile.objects.create(user=user, theme="dark", language="es")
    client = Client()
    client.force_login(user)
    head = headers(client)
    for url in ("/hv/session-state/", ROOT, LOGIN):
        with CaptureQueriesContext(connection) as queries:
            response = client.get(url, headers=head)
        assert response.status_code == 200
        assert all("todo_profile" not in row["sql"].lower() for row in queries)
        assert "X-HyperTodo-Theme" not in response
        if url == "/hv/session-state/":
            assert response.json()["authenticated"] is True
            assert response.json()["binding"] == head[EXPECTED]


@pytest.mark.parametrize(
    "url,method",
    [
        (ROOT, "get"),
        (LOGIN, "get"),
        ("/hv/login/", "post"),
        ("/hv/biometric/login/", "post"),
    ],
)
def test_recovery_never_bypasses_expected_binding(
    user: AbstractUser, url: str, method: str
) -> None:
    """Recovery never bypasses the expected session binding.

    Args:
        user: Signed-in user who owns the data in this test.
        url: Recovery URL that is requested.
        method: Lower-case name of the client method that sends the request.
    """
    client = Client()
    client.force_login(user)
    response = getattr(client, method)(
        url,
        {},
        headers={
            CONTRACT: "realtime-v1",
            RECOVERY: "login-v1",
            EXPECTED: "hvs1." + "Z" * 43,
        },
    )
    assert response.status_code == 409
    assert response.json() == {"error": "session-binding-mismatch"}
    assert BINDING not in response and OUTCOME not in response
    assert not Task.objects.exists()


@pytest.mark.parametrize(
    "url,method",
    [
        ("/hv/tasks/new/", "post"),
        ("/hv/settings/", "post"),
        ("/hv/logout/", "post"),
        ("/hv/", "get"),
        (ROOT, "post"),
        (ROOT, "head"),
        (ROOT + "?screen=dashboard", "get"),
        (ROOT + "?screen=login&screen=login", "get"),
        (ROOT + "?screen=%6Cogin", "get"),
        (LOGIN + "&next=/hv/dashboard/", "get"),
        ("/hv/session-state/?x=1", "get"),
        ("/hv/login/?x=1", "post"),
        ("/admin/", "get"),
    ],
)
def test_recovery_scope_rejects_before_business_work(
    user: AbstractUser, url: str, method: str
) -> None:
    """Requests outside the recovery scope are rejected before any business work.

    Args:
        user: Signed-in user who owns the data in this test.
        url: Recovery URL that is requested.
        method: Lower-case name of the client method that sends the request.
    """
    client = Client()
    client.force_login(user)
    head = headers(client)
    before = client.session.session_key
    response = getattr(client, method)(
        url,
        {"title": "Must not create", "first_name": "Must not change"}
        if method == "post"
        else {},
        headers=head,
    )
    assert response.status_code == 400
    if method != "head":
        assert response.json() == {"error": "invalid-recovery-scope"}
    else:
        assert not response.content
        assert response["Content-Type"].startswith("application/json")
    assert BINDING not in response and OUTCOME not in response
    assert not Task.objects.exists()
    user.refresh_from_db()
    assert user.first_name == ""
    assert client.session.session_key == before


@pytest.mark.parametrize(
    "contract,recovery",
    [
        (None, "login-v1"),
        ("wrong", "login-v1"),
        ("realtime-v1", ""),
        ("realtime-v1", "LOGIN-V1"),
        ("realtime-v1", "login-v1 "),
    ],
)
def test_header_grammar_does_not_grant_recovery(
    contract: str | None, recovery: str
) -> None:
    """A malformed contract or recovery header does not grant recovery.

    Args:
        contract: Value of the client contract header, or None to omit it.
        recovery: Value of the recovery header.
    """
    head = {RECOVERY: recovery}
    if contract is not None:
        head[CONTRACT] = contract
    response = Client().get(ROOT, headers=head)
    assert response.status_code == 400
    assert response.json() == {"error": "invalid-recovery-contract"}


@pytest.mark.parametrize("modern", (False, True))
def test_recovery_route_requires_explicit_selector(modern: bool) -> None:
    """The recovery route requires an explicit screen selector.

    Args:
        modern: Whether the client negotiates the realtime contract.
    """
    client = Client()
    head = _headers(_confirm(client, False)[0]) if modern else {}
    response = client.get(ROOT, headers=head)
    assert response.status_code == 404


def test_explicit_password_success_keeps_actual_rotation_and_outcome(
    user: AbstractUser, other_user: AbstractUser
) -> None:
    """An explicit password sign-in keeps the actual rotation and auth outcome.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
    """
    client = Client(enforce_csrf_checks=True)
    client.force_login(other_user)
    head = headers(client)
    original_key = client.session.session_key
    token = csrf(xml(client.get(LOGIN, headers=head)))
    result = client.post(
        "/hv/login/",
        {
            "username": user.username,
            "password": "correct-horse",
            "enable_biometrics": "on",
            "csrfmiddlewaretoken": token,
        },
        headers=head,
    )
    root = xml(result)
    assert result[OUTCOME] == "password-ok"
    assert result[BINDING] != head[EXPECTED]
    assert client.session.session_key != original_key
    assert client.session["_auth_user_id"] == str(user.pk)
    assert root.attrib["id"] == "login-transition"
    assert root.find("hv:behavior[@action='store-biometric-token']", NS).attrib["token"]
    assert BiometricCredential.objects.filter(user=user).exists()


@pytest.mark.parametrize(
    "case,status",
    [("biometric-invalid", 401), ("biometric-throttled", 429), ("csrf", 403)],
)
def test_recovery_auth_failure_semantics_stay_authoritative(
    user: AbstractUser, case: str, status: int
) -> None:
    """Authentication failures keep their authoritative status during recovery.

    Args:
        user: Signed-in user who owns the data in this test.
        case: Authentication failure that is exercised.
        status: Status code the failure must keep.
    """
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    head = headers(client)
    token = csrf(xml(client.get(LOGIN, headers=head)))
    if case == "biometric-throttled":
        for _ in range(BIOMETRIC_ATTEMPT_LIMIT):
            client.post(
                "/hv/biometric/login/",
                {"biometric_token": "synthetic-invalid", "csrfmiddlewaretoken": token},
                headers=head,
            )
    payload = (
        {"biometric_token": "synthetic-invalid", "csrfmiddlewaretoken": token}
        if case != "csrf"
        else {}
    )
    response = client.post("/hv/biometric/login/", payload, headers=head)
    root = xml(response, status)
    assert response[BINDING] == head[EXPECTED]
    if case == "csrf":
        assert OUTCOME not in response
    else:
        assert response[OUTCOME] == case
        assert root.attrib["id"] == "login-panel"
        assert csrf(root)
        stores = root.findall("hv:behavior[@action='store-biometric-token']", NS)
        assert len(stores) == int(status == 401)
    assert client.session["_auth_user_id"] == str(user.pk)


def test_neutral_render_failure_cannot_return_debug_request_data(
    user: AbstractUser, settings: Settings
) -> None:
    """A neutral render failure cannot return debug request data.

    Args:
        user: Signed-in user who owns the data in this test.
        settings: Django settings overridden by this test.
    """
    settings.DEBUG = True
    client = Client(raise_request_exception=False)
    client.force_login(user)
    client.cookies["private_cookie"] = "PRIVATE_COOKIE_SENTINEL"
    head = headers(client)
    head["X-Private"] = "PRIVATE_META_SENTINEL"
    publish_template(
        "screens/login.xml",
        f'<doc xmlns="{HV}"><screen><body>'
        '<text selectable="{{ missing }}">Invalid rendered type</text>'
        "</body></screen></doc>",
    )
    response = client.get(LOGIN, headers=head)
    assert response.status_code == 500
    assert "PRIVATE_META_SENTINEL" not in response.content.decode()
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {"error": "recovery-render-failed"}
    assert OUTCOME not in response and BINDING not in response
    assert all(
        value not in response.content.decode()
        for value in (user.username, "PRIVATE_COOKIE_SENTINEL", "PRIVATE_META_SENTINEL")
    )


@pytest.mark.parametrize("modern", (False, True))
def test_normal_login_keeps_actual_account_theme_language_and_lazy_response(
    user: AbstractUser, modern: bool
) -> None:
    """A normal login keeps the actual account theme, language and lazy response.

    Args:
        user: Signed-in user who owns the data in this test.
        modern: Whether the client negotiates the realtime contract.
    """
    Profile.objects.create(user=user, theme="dark", language="es")
    client = Client()
    client.force_login(user)
    head = _headers(_confirm(client, True)[0]) if modern else {}
    response = client.get("/hv/login/", headers=head)
    assert response.status_code == 200
    assert response["X-HyperTodo-Theme"] == "dark"
    assert response["Content-Language"] == "es"
    assert response._request.user.pk == user.pk
    validate_hyperview_schema(response.content.decode())
    assert bool(response.get(BINDING)) is modern


def test_recovery_get_still_requires_expected_binding() -> None:
    """A recovery GET still requires the expected session binding."""
    response = Client().get(
        ROOT, headers={CONTRACT: "realtime-v1", RECOVERY: "login-v1"}
    )
    assert response.status_code == 400
    assert response.json() == {"error": "invalid-session-binding"}
    assert BINDING not in response and OUTCOME not in response


def test_explicit_biometric_recovery_rotates_actual_session_and_token(
    user: AbstractUser, other_user: AbstractUser
) -> None:
    """An explicit biometric recovery rotates the actual session and the token.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
    """
    token = issue_biometric_token(user=user)
    client = Client(enforce_csrf_checks=True)
    client.force_login(other_user)
    head = headers(client)
    csrf_token = csrf(xml(client.get(LOGIN, headers=head)))
    response = client.post(
        "/hv/biometric/login/",
        {"biometric_token": token, "csrfmiddlewaretoken": csrf_token},
        headers=head,
    )
    result = xml(response)
    assert response[OUTCOME] == "biometric-ok"
    assert response[BINDING] != head[EXPECTED]
    assert client.session["_auth_user_id"] == str(user.pk)
    rotated = result.find("hv:behavior[@action='store-biometric-token']", NS).attrib[
        "token"
    ]
    assert rotated and rotated != token


def test_original_session_csrf_storage_is_not_copied_into_render_context(
    user: AbstractUser, settings: Settings
) -> None:
    """The CSRF storage of the original session is not copied into the render context.

    Args:
        user: Signed-in user who owns the data in this test.
        settings: Django settings overridden by this test.
    """
    settings.CSRF_USE_SESSIONS = True
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    head = headers(client)
    login = client.get(LOGIN, headers=head)
    token = csrf(xml(login))
    assert login._request.session == {}
    assert "_csrftoken" in client.session
    result = client.post(
        "/hv/login/",
        {"username": "missing", "password": "incorrect", "csrfmiddlewaretoken": token},
        headers=head,
    )
    xml(result, 422)
    assert result[OUTCOME] == "password-invalid"


def test_failed_neutral_transition_never_claims_successful_auth_outcome(
    user: AbstractUser, other_user: AbstractUser
) -> None:
    """A failed neutral transition never claims a successful authentication outcome.

    Args:
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
    """
    client = Client()
    client.force_login(other_user)
    head = headers(client)
    publish_template(
        "fragments/login_transition.xml",
        f'<view xmlns="{HV}">'
        '<text selectable="{{ missing }}">Invalid</text></view>',
    )
    response = client.post(
        "/hv/login/",
        {"username": user.username, "password": "correct-horse"},
        headers=head,
    )
    assert response.status_code == 500
    assert response.json() == {"error": "recovery-render-failed"}
    assert OUTCOME not in response
    # Django skips session persistence on 5xx; no in-memory binding is authority.
    assert BINDING not in response
    assert settings.SESSION_COOKIE_NAME not in response.cookies
    # Confirmation observes the resulting cookie after built-in flush, no replay.
    assert _confirm(client, False)[1].json()["authenticated"] is False
