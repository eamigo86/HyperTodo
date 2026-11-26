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
from django.contrib.auth.models import AbstractUser
from django.core.cache import cache
from django.core.cache.backends.locmem import LocMemCache
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from django.test import Client, RequestFactory
from django.urls import reverse
from pytest_django.fixtures import Settings

from tests.test_hxml_views import NS, assert_hxml
from tests.test_session_contract import BINDING, OUTCOME, _confirm, _headers
from todo.services import issue_biometric_token
from todo.throttle import (
    ADDRESS_ATTEMPT_LIMIT,
    BIOMETRIC_ATTEMPT_LIMIT,
    LOGIN_ATTEMPT_LIMIT,
    LOGIN_ATTEMPT_WINDOW,
    biometric_attempt_key,
    claim_password_attempt,
    register_attempt,
    release_password_attempts,
)

pytestmark = pytest.mark.django_db
THROTTLED = "Too many sign-in attempts. Try again later."


class Clock:
    """A settable stand-in for time.time.

    Args:
        now: Reading the clock reports until a test changes it.
    """

    def __init__(self, now: float) -> None:
        """Start the clock at a fixed reading."""
        self.now = now

    def __call__(self) -> float:
        """Report the current reading."""
        return self.now


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """Pin the clock to the middle of a window, so no test straddles a boundary.

    The address bucket belongs to a window of the wall clock. A test that makes a
    hundred claims would otherwise fail now and then, when the window changed under it.

    Args:
        monkeypatch: Patches time.time with the fake clock.

    Returns:
        The fake clock now installed as time.time.
    """
    now = time.time()
    fake = Clock(now - now % LOGIN_ATTEMPT_WINDOW + LOGIN_ATTEMPT_WINDOW / 2)
    monkeypatch.setattr(time, "time", fake)
    return fake


@pytest.fixture(autouse=True)
def fast_password_hasher(settings: Settings) -> None:
    """Count attempts without paying a PBKDF2 round for each of them.

    Args:
        settings: Django settings overridden by this test.
    """
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


def attempt(
    client: Client,
    username: str = "ada",
    password: str = "wrong-password",
    **extra: str,
) -> HttpResponse:
    """Post one sign-in attempt to the app's login endpoint.

    Args:
        client: Client that posts the form.
        username: Username in the form.
        password: Password in the form.
        **extra: Extra request keywords, such as the peer address.

    Returns:
        The response to the login POST.
    """
    return client.post(
        reverse("todo:login"), {"username": username, "password": password}, **extra
    )


def exhaust(client: Client, username: str = "ada", **extra: str) -> None:
    """Spend the whole attempt limit of one account with wrong passwords.

    Args:
        client: Client that posts the attempts.
        username: Account that receives the failed attempts.
        **extra: Extra request keywords passed to every attempt.
    """
    for _ in range(LOGIN_ATTEMPT_LIMIT):
        assert attempt(client, username, **extra).status_code == 422


def error_text(response: HttpResponse, status: int) -> str:
    """Return the text of the login error line.

    Args:
        response: Refused login response.
        status: HTTP status the response must carry.

    Returns:
        The text of the login error line.
    """
    root = assert_hxml(response, status=status)
    assert root.attrib["id"] == "login-panel"
    return root.find(".//hv:view[@id='login-error']/hv:text", NS).text


def test_failures_up_to_the_limit_still_reach_authenticate(
    client: Client, user: AbstractUser
) -> None:
    """Failures up to the limit still reach authenticate.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
    """
    with patch("todo.views.authenticate", wraps=authenticate) as spy:
        exhaust(client)

    assert spy.call_count == LOGIN_ATTEMPT_LIMIT


def test_the_next_attempt_is_refused_before_authenticate_even_with_the_right_password(
    client: Client, user: AbstractUser
) -> None:
    """The next attempt is refused before authenticate even with the right password.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
    """
    exhaust(client)

    with patch("todo.views.authenticate") as spy:
        response = attempt(client, password="correct-horse")

    assert error_text(response, 429) == THROTTLED
    spy.assert_not_called()
    assert "_auth_user_id" not in client.session


def test_a_success_clears_the_counter(client: Client, user: AbstractUser) -> None:
    """A success clears the counter.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
    """
    for _ in range(LOGIN_ATTEMPT_LIMIT - 1):
        attempt(client)
    assert attempt(client, password="correct-horse").status_code == 200
    client.logout()

    exhaust(client)

    assert attempt(client).status_code == 429


def test_buckets_are_independent_per_username_and_address(
    client: Client, user: AbstractUser, other_user: AbstractUser
) -> None:
    """Buckets are independent per username and address.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
    """
    exhaust(client)

    assert attempt(client, "grace").status_code == 422
    assert attempt(client, "ada", REMOTE_ADDR="10.9.8.7").status_code == 422
    assert attempt(client, "ADA").status_code == 429


def test_the_refusal_does_not_reveal_whether_the_account_exists(
    client: Client, user: AbstractUser
) -> None:
    """The refusal does not reveal whether the account exists.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
    """
    exhaust(client, "ada")
    exhaust(client, "nobody")

    known = error_text(attempt(client, "ada"), 429)
    unknown = error_text(attempt(client, "nobody"), 429)

    assert known == unknown == THROTTLED


def test_modern_clients_receive_a_distinct_throttled_outcome(
    client: Client, user: AbstractUser
) -> None:
    """Modern clients receive a distinct throttled outcome.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
    """
    anonymous, _ = _confirm(client, False)
    exhaust(client, headers=_headers(anonymous))

    response = attempt(client, headers=_headers(anonymous))

    assert error_text(response, 429) == THROTTLED
    assert response[OUTCOME] == "password-throttled"
    assert response[BINDING] == anonymous


def test_an_invalid_submission_is_not_counted(client: Client) -> None:
    """An invalid submission is not counted.

    Args:
        client: Client that requests the screens under test.
    """
    for _ in range(LOGIN_ATTEMPT_LIMIT + 1):
        assert client.post(reverse("todo:login"), {}).status_code == 422


# --- one address, many usernames -------------------------------------------


def test_rotating_usernames_share_one_address_budget(
    client: Client, user: AbstractUser
) -> None:
    """Rotating usernames share one address budget.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
    """
    for index in range(ADDRESS_ATTEMPT_LIMIT):
        assert attempt(client, f"guesser{index}").status_code == 422

    with patch("todo.views.authenticate", wraps=authenticate) as spy:
        response = attempt(client, "ada", password="correct-horse")

    assert error_text(response, 429) == THROTTLED
    spy.assert_not_called()
    assert attempt(client, "ada", REMOTE_ADDR="10.9.8.7").status_code == 422


def test_a_tripped_bucket_survives_a_flood_of_junk_usernames(
    client: Client, user: AbstractUser
) -> None:
    """A tripped bucket survives a flood of junk usernames.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
    """
    # LocMemCache culls the least recently used entries once it is full, and the test
    # cache keeps Django's default capacity of 300, so before the address budget this
    # many made-up names pushed the tripped bucket out and the next attempt passed.
    exhaust(client)

    for index in range(300):
        attempt(client, f"junk{index}")

    assert error_text(attempt(client, password="correct-horse"), 429) == THROTTLED


def test_an_address_over_budget_opens_no_further_account_bucket() -> None:
    """An address over budget opens no further account bucket."""
    request = RequestFactory().post("/hv/login/")
    for index in range(ADDRESS_ATTEMPT_LIMIT):
        assert claim_password_attempt(request, f"guesser{index}")

    with patch("todo.throttle.register_attempt", wraps=register_attempt) as spy:
        assert not claim_password_attempt(request, "one-more")

    # Only the address was claimed: the made-up name took no cache entry.
    assert spy.call_count == 1


def test_a_success_gives_back_its_own_address_claim_and_no_failure(
    client: Client, user: AbstractUser
) -> None:
    """A success gives back its own address claim and no failure.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
    """
    for index in range(ADDRESS_ATTEMPT_LIMIT - 1):
        attempt(client, f"guesser{index}")
    assert attempt(client, password="correct-horse").status_code == 200
    client.logout()

    # The success claimed the 100th attempt and returned it, so the address still has
    # exactly one failure left: its 99 failures stay on the books.
    assert attempt(client, "another").status_code == 422
    assert error_text(attempt(client, "another"), 429) == THROTTLED


def test_sign_ins_that_succeed_never_exhaust_the_address_budget(
    client: Client, user: AbstractUser
) -> None:
    """Sign-ins that succeed never exhaust the address budget.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
    """
    # Everybody behind one NAT shares an address, so counting its successes locked all
    # of them out once the office had signed in 100 times in a quarter of an hour.
    for _ in range(ADDRESS_ATTEMPT_LIMIT + 5):
        assert attempt(client, password="correct-horse").status_code == 200
        client.logout()


def test_a_refund_after_the_window_ended_buys_no_extra_attempt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A refund after the window ended buys no extra attempt.

    Args:
        caplog: Captures the log records emitted by this test.
    """
    request = RequestFactory().post("/hv/login/")
    assert claim_password_attempt(request, "ada")
    cache.clear()  # the window ended between the claim and the success

    release_password_attempts(request, "ada")

    # A bucket that is gone is the ordinary end of a window, not a cache failure.
    assert throttle_warnings(caplog) == []
    for index in range(ADDRESS_ATTEMPT_LIMIT):
        assert claim_password_attempt(request, f"guesser{index}")
    assert not claim_password_attempt(request, "one-more")


def test_a_refund_that_arrives_in_a_later_window_cannot_enlarge_its_budget(
    clock: Clock,
) -> None:
    """A refund that arrives in a later window cannot enlarge its budget.

    Args:
        clock: Fake clock the test advances.
    """
    # Sign-ins claim in one window and are still inside authenticate() when it ends.
    # Their refunds used to land on whichever bucket the address had by then: the next
    # window's, opened by a guess, which then granted 100 + one attempt per refund and
    # counted below zero.
    slow = [post_from("10.1.1.1") for _ in range(3)]
    for request in slow:
        assert claim_password_attempt(request, "ada")
    clock.now += LOGIN_ATTEMPT_WINDOW + 1
    guesses = [post_from("10.1.1.1") for _ in range(2 * ADDRESS_ATTEMPT_LIMIT)]

    granted = [claim_password_attempt(guesses[0], "guesser0")]
    for request in slow:
        release_password_attempts(request, "ada")
    granted += [
        claim_password_attempt(request, f"guesser{index}")
        for index, request in enumerate(guesses[1:], start=1)
    ]

    assert sum(granted) == ADDRESS_ATTEMPT_LIMIT


def test_a_refund_within_its_own_window_still_returns_the_claim(clock: Clock) -> None:
    """A refund within its own window still returns the claim.

    Args:
        clock: Fake clock the test advances.
    """
    request = post_from("10.1.1.1")
    for index in range(ADDRESS_ATTEMPT_LIMIT - 1):
        assert claim_password_attempt(post_from("10.1.1.1"), f"guesser{index}")
    assert claim_password_attempt(request, "ada")
    clock.now += LOGIN_ATTEMPT_WINDOW / 4  # time passes inside the same window

    release_password_attempts(request, "ada")

    assert claim_password_attempt(post_from("10.1.1.1"), "after-the-success")
    assert not claim_password_attempt(post_from("10.1.1.1"), "one-more")


def test_each_window_starts_a_fresh_address_budget(clock: Clock) -> None:
    """Each window starts a fresh address budget.

    Args:
        clock: Fake clock the test advances.
    """
    spend_address_budget("10.1.1.1")
    assert not claim_password_attempt(post_from("10.1.1.1"), "one-more")

    clock.now += LOGIN_ATTEMPT_WINDOW

    assert claim_password_attempt(post_from("10.1.1.1"), "one-more")


def test_a_refund_never_returns_more_than_one_claim() -> None:
    """A refund never returns more than one claim."""
    request = RequestFactory().post("/hv/login/")
    for index in range(ADDRESS_ATTEMPT_LIMIT - 1):
        assert claim_password_attempt(request, f"guesser{index}")
    assert claim_password_attempt(request, "ada")

    release_password_attempts(request, "ada")

    assert claim_password_attempt(request, "after-the-success")
    assert not claim_password_attempt(request, "one-more")


def test_a_success_clears_only_the_account_that_signed_in(
    client: Client, user: AbstractUser, other_user: AbstractUser
) -> None:
    """A success clears only the account that signed in.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
        other_user: Second user whose data must stay isolated from the first.
    """
    exhaust(client, "grace")

    assert attempt(client, password="correct-horse").status_code == 200
    client.logout()

    assert attempt(client, "grace", password="correct-horse").status_code == 429


# --- one client, many spellings of its address ------------------------------


def post_from(
    address: str | None, path: str = "/hv/login/", **data: str
) -> WSGIRequest:
    """Build a POST from exactly this peer address (None: no peer at all).

    Args:
        address: Peer address to set, or None for no peer at all.
        path: Path the request targets.
        **data: Form fields of the POST.

    Returns:
        The request carrying exactly that peer address.
    """
    request = RequestFactory().post(path, data)
    if address is None:
        del request.META["REMOTE_ADDR"]
    else:
        request.META["REMOTE_ADDR"] = address
    return request


def spend_address_budget(address: str | None) -> None:
    """Spend the whole address budget from one peer address.

    Args:
        address: Peer address that spends the budget.
    """
    request = post_from(address)
    for index in range(ADDRESS_ATTEMPT_LIMIT):
        assert claim_password_attempt(request, f"guesser{index}")


@pytest.mark.parametrize(
    "spent,rotated",
    [
        # An IPv6 client owns its whole /64, so it can write 2**64 addresses.
        ("2001:db8:1:2::1", "2001:db8:1:2:ffff:ffff:ffff:ffff"),
        ("2001:db8:1:2::1", "2001:0DB8:1:2:0:0:0:2"),
        # A zone names an interface, not the client. With no host bits set the network
        # used to keep it, so each spelling of the zone was a budget of its own.
        ("fe80::%en0", "fe80::1"),
        ("fe80::%en0", "fe80::%eth1"),
        ("2001:db8:1:2::%eth1", "2001:db8:1:2::ffff"),
        ("fe80::1%en0", "fe80::2%eth1"),
        # An IPv4 client reached through a dual-stack socket arrives mapped.
        ("10.1.1.1", "::ffff:10.1.1.1"),
        ("::ffff:10.1.1.1", "10.1.1.1"),
        ("::ffff:10.1.1.1", "::ffff:0a01:0101"),
    ],
)
def test_every_spelling_of_one_clients_address_draws_on_one_budget(
    spent: str | None, rotated: str
) -> None:
    """Every spelling of one client's address draws on one budget.

    Args:
        spent: Peer address that uses up the budget.
        rotated: Another spelling or address of the same client.
    """
    spend_address_budget(spent)

    assert not claim_password_attempt(post_from(rotated), "one-more")


@pytest.mark.parametrize(
    "spent,other",
    [
        ("2001:db8:1:2::1", "2001:db8:1:3::1"),
        ("2001:db8:1:2::1", "2001:db8:2:2::1"),
        ("10.1.1.1", "10.1.1.2"),
        ("::ffff:10.1.1.1", "::ffff:10.1.1.2"),
        ("10.1.1.1", "2001:db8:1:2::1"),
    ],
)
def test_a_different_client_keeps_its_own_address_budget(
    spent: str | None, other: str | None
) -> None:
    """A different client keeps its own address budget.

    Args:
        spent: Peer address that uses up the budget.
        other: Peer address of a different client.
    """
    spend_address_budget(spent)

    assert claim_password_attempt(post_from(other), "one-more")


def test_the_account_bucket_follows_the_same_normalisation() -> None:
    """The account bucket follows the same normalisation."""
    first, second = post_from("2001:db8:1:2::1"), post_from("2001:db8:1:2::2")
    for _ in range(LOGIN_ATTEMPT_LIMIT):
        assert claim_password_attempt(first, "ada")

    assert not claim_password_attempt(second, "ADA")
    assert claim_password_attempt(post_from("2001:db8:1:3::1"), "ada")


def test_a_zone_id_never_reaches_a_cache_key() -> None:
    """A zone ID never reaches a cache key."""
    for address in ("fe80::%en0", "fe80::1%en0"):
        request = post_from(address, "/hv/biometric/login/", biometric_token="x")

        assert "%" not in biometric_attempt_key(request)
        assert "en0" not in biometric_attempt_key(request)


def test_the_biometric_bucket_follows_the_same_normalisation() -> None:
    """The biometric bucket follows the same normalisation."""
    key = biometric_attempt_key(
        post_from("2001:db8:1:2::1", "/hv/biometric/login/", biometric_token="x")
    )

    assert key == biometric_attempt_key(
        post_from("2001:db8:1:2::2", "/hv/biometric/login/", biometric_token="x")
    )
    assert key != biometric_attempt_key(
        post_from("2001:db8:1:3::1", "/hv/biometric/login/", biometric_token="x")
    )


@pytest.mark.parametrize(
    "spent,other",
    [
        (None, ""),
        ("", "not-an-address"),
        ("not-an-address", "10.1.1.256"),
        ("10.1.1.256", "2001:db8::1/64"),
    ],
)
def test_an_address_that_does_not_parse_shares_one_fixed_bucket(
    spent: str | None, other: str | None
) -> None:
    """An address that does not parse shares one fixed bucket.

    Args:
        spent: Peer address that uses up the budget.
        other: Peer address of a different client.
    """
    # Behind a unix socket uvicorn has no peer address, so REMOTE_ADDR is missing or
    # empty and every client lands here. Whatever else fails to parse must not mint a
    # bucket of its own either, or a made-up value would refill the budget.
    spend_address_budget(spent)

    assert not claim_password_attempt(post_from(other), "one-more")


# --- the Django Admin login draws on the same budget ------------------------


@pytest.fixture
def staff(db: None) -> AbstractUser:
    """Create a staff user who can sign in to the admin.

    Args:
        db: Database access for this test.

    Returns:
        A saved staff user named staffer.
    """
    return get_user_model().objects.create_user(
        "staffer", password="correct-horse", is_staff=True
    )


def admin_attempt(
    client: Client, username: str = "staffer", password: str = "wrong-password"
) -> HttpResponse:
    """Post one sign-in attempt to the Django admin login.

    Args:
        client: Client that posts the form.
        username: Username in the form.
        password: Password in the form.

    Returns:
        The response to the admin login POST.
    """
    return client.post(
        reverse("admin:login"),
        {"username": username, "password": password, "next": reverse("admin:index")},
    )


def throttled(response: HttpResponse) -> bool:
    """Tell whether a response carries the throttle message.

    Args:
        response: Response to inspect.

    Returns:
        True when the body shows the throttle message.
    """
    return THROTTLED in response.content.decode()


def test_the_admin_login_is_throttled_before_authenticate(
    client: Client, staff: AbstractUser
) -> None:
    """The admin login is throttled before authenticate.

    Args:
        client: Client that requests the screens under test.
        staff: Staff user who signs in to the admin.
    """
    for _ in range(LOGIN_ATTEMPT_LIMIT):
        assert not throttled(admin_attempt(client))

    with patch("django.contrib.auth.forms.authenticate", wraps=authenticate) as spy:
        response = admin_attempt(client, password="correct-horse")

    assert throttled(response)
    spy.assert_not_called()
    assert "_auth_user_id" not in client.session


def test_the_admin_and_the_app_draw_on_one_budget(
    client: Client, staff: AbstractUser
) -> None:
    """The admin and the app draw on one budget.

    Args:
        client: Client that requests the screens under test.
        staff: Staff user who signs in to the admin.
    """
    for _ in range(LOGIN_ATTEMPT_LIMIT // 2):
        attempt(client, "staffer")
        admin_attempt(client)

    assert attempt(client, "staffer").status_code == 429
    assert throttled(admin_attempt(client, password="correct-horse"))


def test_an_admin_success_clears_the_account_counter(
    client: Client, staff: AbstractUser
) -> None:
    """An admin success clears the account counter.

    Args:
        client: Client that requests the screens under test.
        staff: Staff user who signs in to the admin.
    """
    for _ in range(LOGIN_ATTEMPT_LIMIT - 1):
        admin_attempt(client)
    assert admin_attempt(client, password="correct-horse").status_code == 302
    client.logout()

    for _ in range(LOGIN_ATTEMPT_LIMIT):
        assert not throttled(admin_attempt(client))

    assert throttled(admin_attempt(client))


def test_an_admin_success_gives_back_its_address_claim_too(
    client: Client, staff: AbstractUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An admin success gives back its address claim too.

    Args:
        client: Client that requests the screens under test.
        staff: Staff user who signs in to the admin.
        monkeypatch: Patches the address attempt limit down to three.
    """
    monkeypatch.setattr("todo.throttle.ADDRESS_ATTEMPT_LIMIT", 3)

    for _ in range(5):
        assert admin_attempt(client, password="correct-horse").status_code == 302
        client.logout()


def test_an_incomplete_admin_submission_is_not_counted(
    client: Client, staff: AbstractUser
) -> None:
    """An incomplete admin submission is not counted.

    Args:
        client: Client that requests the screens under test.
        staff: Staff user who signs in to the admin.
    """
    for _ in range(LOGIN_ATTEMPT_LIMIT + 1):
        assert not throttled(admin_attempt(client, password=""))

    assert admin_attempt(client, password="correct-horse").status_code == 302


# --- the counter is a single atomic claim -----------------------------------


def test_the_window_runs_from_the_first_attempt_and_is_never_extended() -> None:
    """The window runs from the first attempt and is never extended."""
    start = time.time()
    with patch("time.time", return_value=start):
        assert register_attempt("probe", 60) == 1
    with patch("time.time", return_value=start + 59):
        assert register_attempt("probe", 60) == 2
    with patch("time.time", return_value=start + 61):
        assert register_attempt("probe", 60) == 1


def test_claims_that_all_read_before_any_write_still_count_every_attempt() -> None:
    """Claims that all read before any write still count every attempt."""
    # A get-then-set counter gives every claimant the same stale total and loses all
    # but one update, but real threads only collide now and then. The barrier makes
    # the worst interleaving certain: nobody may write until everybody has read. An
    # atomic add + incr never reads, so it never waits here.
    claimants = 8
    everybody_read = threading.Barrier(claimants, timeout=5)
    real_get = LocMemCache.get

    def read_then_wait(self: LocMemCache, *args: object, **kwargs: object) -> object:
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


def test_a_window_that_ends_between_the_two_cache_calls_opens_a_new_one() -> None:
    """A window that ends between the two cache calls opens a new one."""
    with patch.object(cache, "incr", side_effect=ValueError("expired")):
        assert register_attempt("probe", 60) == 1

    assert cache.get("probe") == 1
    assert register_attempt("probe", 60) == 2


def test_a_throttled_biometric_attempt_never_reaches_the_token_lookup(
    client: Client,
) -> None:
    """A throttled biometric attempt never reaches the token lookup.

    Args:
        client: Client that requests the screens under test.
    """

    def unlock() -> HttpResponse:
        return client.post(reverse("todo:biometric-login"), {"biometric_token": "x"})

    for _ in range(BIOMETRIC_ATTEMPT_LIMIT):
        assert unlock().status_code == 401

    with patch("todo.views.authenticate_biometric_token") as lookup:
        response = unlock()

    assert response.status_code == 429
    lookup.assert_not_called()


# --- a cache that cannot answer never blocks a sign-in -----------------------


@pytest.fixture(params=[False, True], ids=["raises", "answers-none"])
def dead_cache(settings: Settings, request: pytest.FixtureRequest) -> None:
    """Point the default cache at a Redis nothing listens on.

    Without IGNORE_EXCEPTIONS django-redis re-raises the connection error; with it,
    every call quietly answers None instead.

    Args:
        settings: Django settings overridden by this test.
        request: Pytest request whose parameter sets whether the cache ignores errors.
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


def throttle_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Return the warnings the throttle logged, whatever else the request logged.

    Args:
        caplog: Captures the log records of the request.

    Returns:
        The warning records of the todo.throttle logger.
    """
    return [
        record
        for record in caplog.records
        if record.name == "todo.throttle" and record.levelno == logging.WARNING
    ]


def test_a_dead_cache_never_blocks_a_password_sign_in(
    client: Client,
    user: AbstractUser,
    dead_cache: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A dead cache never blocks a password sign-in.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
        dead_cache: Cache that cannot answer.
        caplog: Captures the log records emitted by this test.
    """
    assert attempt(client).status_code == 422
    response = attempt(client, password="correct-horse")

    assert response.status_code == 200
    assert client.session["_auth_user_id"] == str(user.pk)
    assert throttle_warnings(caplog)


def test_the_warning_for_a_dead_cache_carries_no_secret(
    client: Client,
    user: AbstractUser,
    dead_cache: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The warning for a dead cache carries no secret.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
        dead_cache: Cache that cannot answer.
        caplog: Captures the log records emitted by this test.
    """
    attempt(client, password="correct-horse")

    records = throttle_warnings(caplog)
    assert records
    logged = " ".join(logging.Formatter().format(record) for record in records)
    assert "correct-horse" not in logged
    assert sha256(b"ada").hexdigest() not in logged
    assert "login-attempts" not in logged


def test_a_refund_the_cache_cannot_take_is_skipped_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A refund the cache cannot take is skipped with a warning.

    Args:
        caplog: Captures the log records emitted by this test.
    """
    request = post_from("10.1.1.1")

    with patch.object(cache, "decr", side_effect=ConnectionError("redis is down")):
        release_password_attempts(request, "ada")

    records = throttle_warnings(caplog)
    assert len(records) == 1
    assert "10.1.1.1" not in logging.Formatter().format(records[0])


def test_a_dead_cache_never_blocks_a_biometric_unlock(
    client: Client, user: AbstractUser, dead_cache: None
) -> None:
    """A dead cache never blocks a biometric unlock.

    Args:
        client: Client that requests the screens under test.
        user: Signed-in user who owns the data in this test.
        dead_cache: Cache that cannot answer.
    """
    raw = issue_biometric_token(user=user)

    response = client.post(reverse("todo:biometric-login"), {"biometric_token": raw})

    assert response.status_code == 200
    assert client.session["_auth_user_id"] == str(user.pk)


def test_a_dead_cache_never_blocks_the_admin_login(
    client: Client, staff: AbstractUser, dead_cache: None
) -> None:
    """A dead cache never blocks the admin login.

    Args:
        client: Client that requests the screens under test.
        staff: Staff user who signs in to the admin.
        dead_cache: Cache that cannot answer.
    """
    assert admin_attempt(client).status_code == 200
    assert admin_attempt(client, password="correct-horse").status_code == 302
