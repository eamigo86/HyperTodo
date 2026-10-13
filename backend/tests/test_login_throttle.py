"""Password sign-ins are throttled per address and per (address, username).

Every failed attempt costs one PBKDF2 round (about 135 ms), so an unthrottled form is
both an online-guessing oracle and a CPU lever. Counters live in the default cache and
an attempt is claimed with an atomic increment BEFORE authenticate() runs, so a burst
of parallel requests cannot all pass the same stale read. The Django Admin login draws
on the same budget, and a cache that cannot answer never blocks a sign-in.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from unittest.mock import patch

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.cache import cache
from django.core.cache.backends.locmem import LocMemCache
from django.test import RequestFactory
from django.urls import reverse

from tests.test_hxml_views import NS, assert_hxml
from tests.test_session_contract import BINDING, OUTCOME, _confirm, _headers
from todo.services import issue_biometric_token
from todo.throttle import (
    ADDRESS_ATTEMPT_LIMIT,
    BIOMETRIC_ATTEMPT_LIMIT,
    LOGIN_ATTEMPT_LIMIT,
    claim_password_attempt,
    register_attempt,
)

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


# --- one address, many usernames -------------------------------------------


def test_rotating_usernames_share_one_address_budget(client, user):
    for index in range(ADDRESS_ATTEMPT_LIMIT):
        assert attempt(client, f"guesser{index}").status_code == 422

    with patch("todo.views.authenticate", wraps=authenticate) as spy:
        response = attempt(client, "ada", password="correct-horse")

    assert error_text(response, 429) == THROTTLED
    spy.assert_not_called()
    assert attempt(client, "ada", REMOTE_ADDR="10.9.8.7").status_code == 422


def test_a_tripped_bucket_survives_a_flood_of_junk_usernames(client, user):
    # LocMemCache culls the least recently used entries once it is full, and the test
    # cache keeps Django's default capacity of 300, so before the address budget this
    # many made-up names pushed the tripped bucket out and the next attempt passed.
    exhaust(client)

    for index in range(300):
        attempt(client, f"junk{index}")

    assert error_text(attempt(client, password="correct-horse"), 429) == THROTTLED


def test_an_address_over_budget_opens_no_further_account_bucket():
    request = RequestFactory().post("/hv/login/")
    for index in range(ADDRESS_ATTEMPT_LIMIT):
        assert claim_password_attempt(request, f"guesser{index}")

    with patch("todo.throttle.register_attempt", wraps=register_attempt) as spy:
        assert not claim_password_attempt(request, "one-more")

    # Only the address was claimed: the made-up name took no cache entry.
    assert spy.call_count == 1


def test_a_success_never_refills_the_address_budget(client, user):
    for index in range(ADDRESS_ATTEMPT_LIMIT - 1):
        attempt(client, f"guesser{index}")
    assert attempt(client, password="correct-horse").status_code == 200
    client.logout()

    assert error_text(attempt(client, "another"), 429) == THROTTLED


def test_a_success_clears_only_the_account_that_signed_in(client, user, other_user):
    exhaust(client, "grace")

    assert attempt(client, password="correct-horse").status_code == 200
    client.logout()

    assert attempt(client, "grace", password="correct-horse").status_code == 429


# --- the Django Admin login draws on the same budget ------------------------


@pytest.fixture
def staff(db):
    return get_user_model().objects.create_user(
        "staffer", password="correct-horse", is_staff=True
    )


def admin_attempt(client, username="staffer", password="wrong-password"):
    return client.post(
        reverse("admin:login"),
        {"username": username, "password": password, "next": reverse("admin:index")},
    )


def throttled(response):
    return THROTTLED in response.content.decode()


def test_the_admin_login_is_throttled_before_authenticate(client, staff):
    for _ in range(LOGIN_ATTEMPT_LIMIT):
        assert not throttled(admin_attempt(client))

    with patch("django.contrib.auth.forms.authenticate", wraps=authenticate) as spy:
        response = admin_attempt(client, password="correct-horse")

    assert throttled(response)
    spy.assert_not_called()
    assert "_auth_user_id" not in client.session


def test_the_admin_and_the_app_draw_on_one_budget(client, staff):
    for _ in range(LOGIN_ATTEMPT_LIMIT // 2):
        attempt(client, "staffer")
        admin_attempt(client)

    assert attempt(client, "staffer").status_code == 429
    assert throttled(admin_attempt(client, password="correct-horse"))


def test_an_admin_success_clears_the_account_counter(client, staff):
    for _ in range(LOGIN_ATTEMPT_LIMIT - 1):
        admin_attempt(client)
    assert admin_attempt(client, password="correct-horse").status_code == 302
    client.logout()

    for _ in range(LOGIN_ATTEMPT_LIMIT):
        assert not throttled(admin_attempt(client))

    assert throttled(admin_attempt(client))


def test_an_incomplete_admin_submission_is_not_counted(client, staff):
    for _ in range(LOGIN_ATTEMPT_LIMIT + 1):
        assert not throttled(admin_attempt(client, password=""))

    assert admin_attempt(client, password="correct-horse").status_code == 302


# --- the counter is a single atomic claim -----------------------------------


def test_the_window_runs_from_the_first_attempt_and_is_never_extended():
    start = time.time()
    with patch("time.time", return_value=start):
        assert register_attempt("probe", 60) == 1
    with patch("time.time", return_value=start + 59):
        assert register_attempt("probe", 60) == 2
    with patch("time.time", return_value=start + 61):
        assert register_attempt("probe", 60) == 1


def test_claims_that_all_read_before_any_write_still_count_every_attempt():
    # A get-then-set counter gives every claimant the same stale total and loses all
    # but one update, but real threads only collide now and then. The barrier makes
    # the worst interleaving certain: nobody may write until everybody has read. An
    # atomic add + incr never reads, so it never waits here.
    claimants = 8
    everybody_read = threading.Barrier(claimants, timeout=5)
    real_get = LocMemCache.get

    def read_then_wait(self, *args, **kwargs):
        value = real_get(self, *args, **kwargs)
        everybody_read.wait()
        return value

    with (
        patch.object(LocMemCache, "get", read_then_wait),
        ThreadPoolExecutor(max_workers=claimants) as pool,
    ):
        counts = list(
            pool.map(lambda _: register_attempt("probe", 60), range(claimants))
        )

    assert sorted(counts) == list(range(1, claimants + 1))


def test_a_window_that_ends_between_the_two_cache_calls_opens_a_new_one():
    with patch.object(cache, "incr", side_effect=ValueError("expired")):
        assert register_attempt("probe", 60) == 1

    assert cache.get("probe") == 1
    assert register_attempt("probe", 60) == 2


def test_a_throttled_biometric_attempt_never_reaches_the_token_lookup(client):
    def unlock():
        return client.post(reverse("todo:biometric-login"), {"biometric_token": "x"})

    for _ in range(BIOMETRIC_ATTEMPT_LIMIT):
        assert unlock().status_code == 401

    with patch("todo.views.authenticate_biometric_token") as lookup:
        response = unlock()

    assert response.status_code == 429
    lookup.assert_not_called()


# --- a cache that cannot answer never blocks a sign-in -----------------------


@pytest.fixture(params=[False, True], ids=["raises", "answers-none"])
def dead_cache(settings, request):
    """Point the default cache at a Redis nothing listens on.

    Without IGNORE_EXCEPTIONS django-redis re-raises the connection error; with it,
    every call quietly answers None instead.
    """
    settings.CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": "redis://127.0.0.1:1/0",
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "IGNORE_EXCEPTIONS": request.param,
            },
        }
    }


def throttle_warnings(caplog):
    """Return the warnings the throttle logged, whatever else the request logged."""
    return [
        record
        for record in caplog.records
        if record.name == "todo.throttle" and record.levelno == logging.WARNING
    ]


def test_a_dead_cache_never_blocks_a_password_sign_in(client, user, dead_cache, caplog):
    assert attempt(client).status_code == 422
    response = attempt(client, password="correct-horse")

    assert response.status_code == 200
    assert client.session["_auth_user_id"] == str(user.pk)
    assert throttle_warnings(caplog)


def test_the_warning_for_a_dead_cache_carries_no_secret(
    client, user, dead_cache, caplog
):
    attempt(client, password="correct-horse")

    records = throttle_warnings(caplog)
    assert records
    logged = " ".join(logging.Formatter().format(record) for record in records)
    assert "correct-horse" not in logged
    assert sha256(b"ada").hexdigest() not in logged
    assert "login-attempts" not in logged


def test_a_dead_cache_never_blocks_a_biometric_unlock(client, user, dead_cache):
    raw = issue_biometric_token(user=user)

    response = client.post(reverse("todo:biometric-login"), {"biometric_token": raw})

    assert response.status_code == 200
    assert client.session["_auth_user_id"] == str(user.pk)


def test_a_dead_cache_never_blocks_the_admin_login(client, staff, dead_cache):
    assert admin_attempt(client).status_code == 200
    assert admin_attempt(client, password="correct-horse").status_code == 302
