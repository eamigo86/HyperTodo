"""Password sign-ins are throttled per (address, username) before PBKDF2 runs.

Every failed attempt costs one PBKDF2 round (about 135 ms), so an unthrottled form is
both an online-guessing oracle and a CPU lever. The counter lives in the default cache
and an attempt is claimed with an atomic increment BEFORE authenticate() runs, so a
burst of parallel requests cannot all pass the same stale read.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from django.contrib.auth import authenticate
from django.core.cache import cache
from django.urls import reverse

from tests.test_hxml_views import NS, assert_hxml
from tests.test_session_contract import BINDING, OUTCOME, _confirm, _headers
from todo.views import BIOMETRIC_ATTEMPT_LIMIT, LOGIN_ATTEMPT_LIMIT, _register_attempt

pytestmark = pytest.mark.django_db
THROTTLED = "Too many sign-in attempts. Try again later."


@pytest.fixture(autouse=True)
def fast_password_hasher(settings):
    """Count attempts without paying a PBKDF2 round for each of them."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


def attempt(client, username="ada", password="wrong-password", **extra):
    return client.post(
        reverse("todo:login"), {"username": username, "password": password}, **extra
    )


def exhaust(client, username="ada", **extra):
    for _ in range(LOGIN_ATTEMPT_LIMIT):
        assert attempt(client, username, **extra).status_code == 422


def error_text(response, status):
    root = assert_hxml(response, status=status)
    assert root.attrib["id"] == "login-panel"
    return root.find(".//hv:view[@id='login-error']/hv:text", NS).text


def test_failures_up_to_the_limit_still_reach_authenticate(client, user):
    with patch("todo.views.authenticate", wraps=authenticate) as spy:
        exhaust(client)

    assert spy.call_count == LOGIN_ATTEMPT_LIMIT


def test_the_next_attempt_is_refused_before_authenticate_even_with_the_right_password(
    client, user
):
    exhaust(client)

    with patch("todo.views.authenticate") as spy:
        response = attempt(client, password="correct-horse")

    assert error_text(response, 429) == THROTTLED
    spy.assert_not_called()
    assert "_auth_user_id" not in client.session


def test_a_success_clears_the_counter(client, user):
    for _ in range(LOGIN_ATTEMPT_LIMIT - 1):
        attempt(client)
    assert attempt(client, password="correct-horse").status_code == 200
    client.logout()

    exhaust(client)

    assert attempt(client).status_code == 429


def test_buckets_are_independent_per_username_and_address(client, user, other_user):
    exhaust(client)

    assert attempt(client, "grace").status_code == 422
    assert attempt(client, "ada", REMOTE_ADDR="10.9.8.7").status_code == 422
    assert attempt(client, "ADA").status_code == 429


def test_the_refusal_does_not_reveal_whether_the_account_exists(client, user):
    exhaust(client, "ada")
    exhaust(client, "nobody")

    known = error_text(attempt(client, "ada"), 429)
    unknown = error_text(attempt(client, "nobody"), 429)

    assert known == unknown == THROTTLED


def test_modern_clients_receive_a_distinct_throttled_outcome(client, user):
    anonymous, _ = _confirm(client, False)
    exhaust(client, headers=_headers(anonymous))

    response = attempt(client, headers=_headers(anonymous))

    assert error_text(response, 429) == THROTTLED
    assert response[OUTCOME] == "password-throttled"
    assert response[BINDING] == anonymous


def test_an_invalid_submission_is_not_counted(client):
    for _ in range(LOGIN_ATTEMPT_LIMIT + 1):
        assert client.post(reverse("todo:login"), {}).status_code == 422


def test_the_window_runs_from_the_first_attempt_and_is_never_extended():
    start = time.time()
    with patch("time.time", return_value=start):
        assert _register_attempt("probe", 60) == 1
    with patch("time.time", return_value=start + 59):
        assert _register_attempt("probe", 60) == 2
    with patch("time.time", return_value=start + 61):
        assert _register_attempt("probe", 60) == 1


def test_parallel_claims_never_lose_a_count():
    with ThreadPoolExecutor(max_workers=16) as pool:
        counts = list(pool.map(lambda _: _register_attempt("probe", 60), range(64)))

    assert sorted(counts) == list(range(1, 65))


def test_a_window_that_ends_between_the_two_cache_calls_opens_a_new_one():
    with patch.object(cache, "incr", side_effect=ValueError("expired")):
        assert _register_attempt("probe", 60) == 1

    assert cache.get("probe") == 1
    assert _register_attempt("probe", 60) == 2


def test_a_throttled_biometric_attempt_never_reaches_the_token_lookup(client):
    def unlock():
        return client.post(reverse("todo:biometric-login"), {"biometric_token": "x"})

    for _ in range(BIOMETRIC_ATTEMPT_LIMIT):
        assert unlock().status_code == 401

    with patch("todo.views.authenticate_biometric_token") as lookup:
        response = unlock()

    assert response.status_code == 429
    lookup.assert_not_called()
