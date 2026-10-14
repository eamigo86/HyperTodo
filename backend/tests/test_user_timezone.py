"""Each request runs in the time zone the client reports in X-Timezone.

The server zone (TIME_ZONE) decided "today", overdue and the greeting for every user,
so someone in Madrid was greeted with "Good morning" until 18:00 and saw Today and
Overdue flip at New York midnight. The header names the zone the person is really in.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from asgiref.sync import async_to_sync
from django.http import HttpResponse
from django.test import AsyncClient, Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from tests.test_hxml_views import (
    NS,
    assert_hxml,
    csrf_client,
    schedule_of,
    text_of,
    token_from,
)
from todo.middleware import TIMEZONE_HEADER, UserTimezoneMiddleware
from todo.models import Task

pytestmark = pytest.mark.django_db

# 21:30 UTC on 15 July is 17:30 in New York, 23:30 in Madrid and already 09:30 on the
# 16th in Auckland: three different greetings, and a different calendar day for one.
NOW = datetime(2026, 7, 15, 21, 30, tzinfo=UTC)
MADRID = "Europe/Madrid"
AUCKLAND = "Pacific/Auckland"


@pytest.fixture(autouse=True)
def new_york_server_at_a_fixed_instant(settings, monkeypatch):
    settings.TIME_ZONE = "America/New_York"
    monkeypatch.setattr("django.utils.timezone.now", lambda: NOW)


def get(user, name, zone=None, query=""):
    """Request one authenticated screen, reporting a zone when one is given."""
    client = Client()
    client.force_login(user)
    headers = {} if zone is None else {TIMEZONE_HEADER: zone}
    return client.get(reverse(name) + query, headers=headers)


def listed(response):
    """Return the titles a task list screen shows, in document order."""
    root = assert_hxml(response)
    return [
        "".join(node.itertext()).removeprefix("✓ ")
        for node in root.findall(".//hv:text[@style='task-title']", NS)
    ]


@pytest.mark.parametrize(
    ("zone", "greeting", "caption"),
    [
        (None, "Good afternoon", "Wednesday, Jul 15"),
        ("America/New_York", "Good afternoon", "Wednesday, Jul 15"),
        (MADRID, "Good evening", "Wednesday, Jul 15"),
        (AUCKLAND, "Good morning", "Thursday, Jul 16"),
    ],
    ids=["no-header", "server-zone", "madrid", "auckland"],
)
def test_the_greeting_and_the_date_follow_the_clients_zone(
    user, zone, greeting, caption
):
    hero = text_of(assert_hxml(get(user, "todo:dashboard", zone)), "dashboard-hero")

    assert greeting in hero
    assert caption in hero


@pytest.fixture
def three_deadlines(user):
    """One task per boundary, each due at an instant that moves between zones."""
    due = {
        # New York 22:00 the 15th, Madrid 04:00 the 16th, Auckland 14:00 the 16th.
        "alpha": datetime(2026, 7, 16, 2, 0, tzinfo=UTC),
        # New York 06:00 and Madrid 12:00 the 15th, Auckland 22:00 the 15th: past.
        "bravo": datetime(2026, 7, 15, 10, 0, tzinfo=UTC),
        # The 16th in New York and Madrid, the 17th in Auckland: ahead everywhere.
        "charlie": datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
    }
    for title, due_at in due.items():
        Task.objects.create(user=user, title=title, due_at=due_at)


@pytest.mark.parametrize(
    ("zone", "today", "scheduled"),
    [
        (None, ["alpha", "bravo"], ["charlie"]),
        (MADRID, ["bravo"], ["alpha", "charlie"]),
        (AUCKLAND, ["alpha"], ["charlie"]),
    ],
    ids=["server-zone", "madrid", "auckland"],
)
def test_today_and_scheduled_follow_the_clients_zone(
    user, three_deadlines, zone, today, scheduled
):
    for status, expected in (("today", today), ("scheduled", scheduled)):
        response = get(user, "todo:tasks", zone, f"?status={status}")
        assert sorted(listed(response)) == expected, status


@pytest.mark.parametrize("zone", [None, MADRID, AUCKLAND])
def test_overdue_is_the_same_instant_comparison_in_every_zone(
    user, three_deadlines, zone
):
    response = get(user, "todo:tasks", zone, "?status=overdue")

    assert listed(response) == ["bravo"]


@pytest.mark.parametrize(
    ("zone", "shown"),
    [
        (None, "Jul 15 · 22:00"),
        (MADRID, "Jul 16 · 04:00"),
        (AUCKLAND, "Jul 16 · 14:00"),
    ],
    ids=["server-zone", "madrid", "auckland"],
)
def test_deadlines_are_shown_in_the_clients_zone(user, three_deadlines, zone, shown):
    body = get(user, "todo:tasks", zone).content.decode()

    assert f"Due {shown}" in body


@pytest.mark.parametrize(
    "value",
    [
        "Mars/Olympus_Mons",
        "Europe",
        "UTC+2",
        "../../etc/passwd",
        "/etc/localtime",
        "Europe/Madrid/Extra",
        "Europe\\Madrid",
        "Europe/Madrid\x00",
        " ",
        "x" * 65,
        "A" * 5000,
    ],
    ids=lambda value: repr(value)[:24],
)
def test_a_header_that_names_no_zone_is_ignored(user, value):
    response = get(user, "todo:dashboard", value)

    assert "Good afternoon" in text_of(assert_hxml(response), "dashboard-hero")
    assert "X-Timezone" in response["Vary"]


def test_a_header_over_the_length_bound_never_reaches_the_tz_lookup(monkeypatch):
    # The names in the test above would be refused by the lookup anyway, so only a spy
    # tells the bound from the lookup. 64 characters is the documented ceiling.
    looked_up = []

    def lookup(name):
        looked_up.append(name)
        return ZoneInfo(MADRID)

    monkeypatch.setattr("todo.middleware.ZoneInfo", lookup)
    seen = []

    def view(request):
        seen.append(timezone.get_current_timezone_name())
        return HttpResponse()

    for length in (64, 65):
        request = RequestFactory().get("/hv/", headers={TIMEZONE_HEADER: "x" * length})
        UserTimezoneMiddleware(view)(request)

    assert looked_up == ["x" * 64]
    assert seen == [MADRID, timezone.get_default_timezone_name()]


@pytest.mark.parametrize(
    "failure",
    [KeyError, ValueError, OSError, IsADirectoryError, PermissionError],
)
def test_whatever_way_the_tz_lookup_fails_the_zone_is_ignored(monkeypatch, failure):
    # ZoneInfoNotFoundError is a KeyError, a key that is not a normalized relative path
    # is a ValueError, and a name that hits a directory or a file the process cannot
    # read is an OSError. Each one is a client that sent rubbish, never a server error.
    def lookup(name):
        raise failure(name)

    monkeypatch.setattr("todo.middleware.ZoneInfo", lookup)
    seen = []

    def view(request):
        seen.append(timezone.get_current_timezone_name())
        return HttpResponse()

    request = RequestFactory().get("/hv/", headers={TIMEZONE_HEADER: MADRID})
    response = UserTimezoneMiddleware(view)(request)

    assert response.status_code == 200
    assert seen == [timezone.get_default_timezone_name()]


def test_the_zone_reaches_the_views_through_the_asgi_chain(user):
    # Production runs under ASGI, where the sync middleware and views are adapted: the
    # active zone has to survive those hops, not only the plain WSGI test client.
    async def run():
        client = AsyncClient()
        await client.aforce_login(user)
        return await client.get(
            reverse("todo:dashboard"), headers={TIMEZONE_HEADER: MADRID}
        )

    response = async_to_sync(run)()

    assert "Good evening" in text_of(assert_hxml(response), "dashboard-hero")
    assert "X-Timezone" in response["Vary"]


def test_without_a_header_the_server_zone_stays_in_force(user):
    response = get(user, "todo:dashboard")

    assert "Good afternoon" in text_of(assert_hxml(response), "dashboard-hero")


def test_the_zone_is_active_only_for_the_request(user):
    default = timezone.get_current_timezone_name()

    get(user, "todo:dashboard", AUCKLAND)

    assert timezone.get_current_timezone_name() == default


def test_a_zone_that_was_already_active_is_restored_afterwards(user):
    with timezone.override("Asia/Tokyo"):
        get(user, "todo:dashboard", MADRID)

        assert timezone.get_current_timezone_name() == "Asia/Tokyo"


def test_the_zone_is_restored_when_the_request_fails():
    def failing(request):
        raise RuntimeError("the view failed")

    request = RequestFactory().get("/hv/", headers={TIMEZONE_HEADER: AUCKLAND})
    default = timezone.get_current_timezone_name()

    with pytest.raises(RuntimeError):
        UserTimezoneMiddleware(failing)(request)

    assert timezone.get_current_timezone_name() == default


def test_the_view_sees_the_clients_zone():
    seen = []

    def view(request):
        seen.append(timezone.get_current_timezone_name())
        return HttpResponse()

    request = RequestFactory().get("/hv/", headers={TIMEZONE_HEADER: MADRID})
    UserTimezoneMiddleware(view)(request)

    assert seen == [MADRID]


@pytest.mark.parametrize("zone", [None, MADRID, "Nowhere/Land"])
@pytest.mark.parametrize(
    ("name", "status"),
    [("todo:dashboard", 200), ("todo:login", 200)],
)
def test_responses_vary_on_the_header_whether_or_not_it_was_sent(
    user, zone, name, status
):
    response = get(user, name, zone)

    assert response.status_code == status
    assert "X-Timezone" in response["Vary"]


def test_error_responses_vary_on_the_header_too(user):
    client = Client()
    client.force_login(user)

    missing = client.get("/hv/no-such-screen/", headers={TIMEZONE_HEADER: MADRID})
    refused = client.delete(reverse("todo:dashboard"))

    assert missing.status_code == 404 and "X-Timezone" in missing["Vary"]
    assert refused.status_code == 405 and "X-Timezone" in refused["Vary"]


def test_the_event_stream_neither_reads_the_header_nor_varies_on_it():
    seen = []

    def view(request):
        seen.append(timezone.get_current_timezone_name())
        return HttpResponse()

    request = RequestFactory().get(
        "/realtime/events/", headers={TIMEZONE_HEADER: AUCKLAND}
    )
    response = UserTimezoneMiddleware(view)(request)

    assert seen == [timezone.get_default_timezone_name()]
    assert "Vary" not in response


# --- a date-only deadline is the end of the day wherever the person is ----------


def create_deadline(user, due_date, due_time, zone=None):
    client = csrf_client()
    client.force_login(user)
    headers = {} if zone is None else {TIMEZONE_HEADER: zone}
    token = token_from(client.get(reverse("todo:task-new"), headers=headers))
    response = client.post(
        reverse("todo:task-new"),
        {
            "title": "Pay rent",
            "due_date": due_date,
            "due_time": due_time,
            "csrfmiddlewaretoken": token,
        },
        headers=headers,
    )
    assert_hxml(response, status=201)
    return client, Task.objects.get(user=user)


def create_all_day(user, due_date, zone=None):
    return create_deadline(user, due_date, "", zone)


def test_a_date_only_deadline_ends_the_day_in_the_clients_zone(user):
    _, task = create_all_day(user, "2026-07-15", MADRID)

    assert task.due_all_day is True
    # 23:59:59.999999 in Madrid, two hours ahead of UTC in July.
    assert task.due_at == datetime(2026, 7, 15, 21, 59, 59, 999999, tzinfo=UTC)


def test_the_same_date_ends_the_day_in_the_server_zone_without_a_header(user):
    _, task = create_all_day(user, "2026-07-15")

    # 23:59:59.999999 in New York, four hours behind UTC in July.
    assert task.due_at == datetime(2026, 7, 16, 3, 59, 59, 999999, tzinfo=UTC)


def test_an_all_day_deadline_round_trips_through_the_clients_zone(user):
    client, task = create_all_day(user, "2026-07-15", MADRID)

    edit = client.get(
        reverse("todo:task-edit", args=(task.pk,)), headers={TIMEZONE_HEADER: MADRID}
    )

    # The person typed no time, so none comes back; and the date is the one they chose.
    assert schedule_of(assert_hxml(edit)) == ("2026-07-15", "")


def test_a_date_only_deadline_is_open_through_a_repeated_hour_and_late_after_it(
    user, monkeypatch
):
    # Santiago turns its clocks back at midnight, so 23:xx on 4 April happens twice.
    # The deadline used to be the first 23:59:59, an hour before the day really ended.
    santiago = ZoneInfo("America/Santiago")
    create_all_day(user, "2026-04-04", "America/Santiago")

    def overdue_at(*wall_clock, fold):
        now = datetime(*wall_clock, fold=fold, tzinfo=santiago).astimezone(UTC)
        monkeypatch.setattr("django.utils.timezone.now", lambda: now)
        return listed(get(user, "todo:tasks", "America/Santiago", "?status=overdue"))

    assert overdue_at(2026, 4, 4, 23, 30, fold=0) == []
    # The same wall-clock minute again, an hour later: still the 4th.
    assert overdue_at(2026, 4, 4, 23, 30, fold=1) == []
    assert overdue_at(2026, 4, 4, 23, 59, 59, fold=1) == []
    assert overdue_at(2026, 4, 5, 0, 0, fold=0) == ["Pay rent"]


def test_a_title_only_edit_from_another_zone_does_not_move_the_deadline(user):
    # Created for the 10th in New York, the deadline is 03:59:59 UTC on the 11th, and
    # Madrid shows the 11th for it. Posting that date back used to rebuild the end of
    # the Madrid day: the same task, 18 hours later, after nothing but a new title.
    client, task = create_all_day(user, "2026-06-10", "America/New_York")
    stored = task.due_at
    url = reverse("todo:task-edit", args=(task.pk,))
    headers = {TIMEZONE_HEADER: MADRID}
    shown = schedule_of(assert_hxml(client.get(url, headers=headers)))

    response = client.post(
        url,
        {
            "title": "Pay rent now",
            "due_date": shown[0],
            "due_time": shown[1],
            "csrfmiddlewaretoken": token_from(client.get(url, headers=headers)),
        },
        headers=headers,
    )

    assert_hxml(response)
    task.refresh_from_db()
    assert task.title == "Pay rent now"
    assert (task.due_at, task.due_all_day) == (stored, True)


def test_a_date_only_deadline_is_still_open_until_the_clients_day_ends(user):
    # It is 23:30 in Madrid on the 15th: the task due that day is due today and not
    # overdue yet, because its deadline is the last instant of the Madrid day.
    create_all_day(user, "2026-07-15", MADRID)

    today = listed(get(user, "todo:tasks", MADRID, "?status=today"))
    overdue = listed(get(user, "todo:tasks", MADRID, "?status=overdue"))

    assert today == ["Pay rent"] and overdue == []


# --- a zone change while the edit form is open -----------------------------------

NEW_YORK = "America/New_York"
CHICAGO = "America/Chicago"
LOS_ANGELES = "America/Los_Angeles"
TOKYO = "Asia/Tokyo"


def screen_values(response, *, status=200):
    """Return every named value a form screen posts back, as the client reads it."""
    root = assert_hxml(response, status=status)
    return {
        node.attrib["name"]: node.attrib.get("value", "")
        for node in root.iterfind(".//*[@name]")
    }


def open_form(client, task, zone):
    url = reverse("todo:task-edit", args=(task.pk,))
    return screen_values(client.get(url, headers={TIMEZONE_HEADER: zone}))


def save_form(client, task, zone, values, **changes):
    url = reverse("todo:task-edit", args=(task.pk,))
    return client.post(url, {**values, **changes}, headers={TIMEZONE_HEADER: zone})


def stored_deadline(task):
    task.refresh_from_db()
    return task.due_at, task.due_all_day


def switch(name, due_time, made_in, opened_in, saved_in):
    return pytest.param(due_time, made_in, opened_in, saved_in, id=name)


@pytest.mark.parametrize(
    ("due_time", "made_in", "opened_in", "saved_in"),
    [
        switch("timed-new-york-to-madrid", "09:30", NEW_YORK, NEW_YORK, MADRID),
        switch("timed-madrid-to-new-york", "09:30", MADRID, MADRID, NEW_YORK),
        switch("timed-new-york-to-chicago", "09:30", NEW_YORK, NEW_YORK, CHICAGO),
        switch("timed-new-york-to-tokyo", "09:30", NEW_YORK, NEW_YORK, TOKYO),
        switch(
            "timed-los-angeles-to-new-york", "09:30", LOS_ANGELES, LOS_ANGELES, NEW_YORK
        ),
        switch(
            "timed-seen-from-madrid-saved-in-tokyo", "09:30", NEW_YORK, MADRID, TOKYO
        ),
        switch("all-day-new-york-to-madrid", "", NEW_YORK, NEW_YORK, MADRID),
        switch("all-day-madrid-to-new-york", "", MADRID, MADRID, NEW_YORK),
        switch("all-day-new-york-to-tokyo", "", NEW_YORK, NEW_YORK, TOKYO),
        switch("all-day-tokyo-to-new-york", "", TOKYO, TOKYO, NEW_YORK),
        switch(
            "all-day-los-angeles-to-new-york", "", LOS_ANGELES, LOS_ANGELES, NEW_YORK
        ),
        switch("all-day-madrid-to-tokyo", "", MADRID, MADRID, TOKYO),
        switch("all-day-tokyo-to-madrid", "", TOKYO, TOKYO, MADRID),
        switch("all-day-seen-from-madrid-saved-in-tokyo", "", NEW_YORK, MADRID, TOKYO),
        # Controls: the zone did not change.
        switch("timed-same-zone", "09:30", NEW_YORK, NEW_YORK, NEW_YORK),
        switch("all-day-same-zone", "", NEW_YORK, NEW_YORK, NEW_YORK),
    ],
)
def test_a_title_only_save_keeps_the_deadline_after_a_zone_change_with_the_form_open(
    user, due_time, made_in, opened_in, saved_in
):
    # The form shows the stored instant in the zone that opened it. Saved from another
    # zone, the date and time it posted used to be read in that other one: a 09:30 task
    # moved six hours from New York to Madrid after nothing but a new title.
    client, task = create_deadline(user, "2026-06-10", due_time, made_in)
    stored = stored_deadline(task)
    values = open_form(client, task, opened_in)

    assert_hxml(save_form(client, task, saved_in, values, title="Renamed"))

    task.refresh_from_db()
    assert task.title == "Renamed"
    assert (task.due_at, task.due_all_day) == stored


@pytest.mark.parametrize(
    ("due_time", "changes", "due_at", "all_day"),
    [
        (
            "09:30",
            {"due_date": "2026-06-12"},
            datetime(2026, 6, 12, 7, 30, tzinfo=UTC),
            False,
        ),
        (
            "09:30",
            {"due_time": "11:00"},
            datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
            False,
        ),
        (
            "09:30",
            {"due_time": ""},
            datetime(2026, 6, 10, 21, 59, 59, 999999, tzinfo=UTC),
            True,
        ),
        (
            "",
            {"due_date": "2026-06-12"},
            datetime(2026, 6, 12, 21, 59, 59, 999999, tzinfo=UTC),
            True,
        ),
        ("", {"due_time": "09:30"}, datetime(2026, 6, 10, 7, 30, tzinfo=UTC), False),
        ("09:30", {"due_date": "", "due_time": ""}, None, False),
    ],
    ids=[
        "new-date",
        "new-time",
        "time-cleared",
        "new-date-on-all-day",
        "time-added-to-all-day",
        "deadline-cleared",
    ],
)
def test_a_real_change_after_a_zone_change_is_read_in_the_zone_that_saves(
    user, due_time, changes, due_at, all_day
):
    client, task = create_deadline(user, "2026-06-10", due_time, NEW_YORK)
    values = open_form(client, task, NEW_YORK)

    assert_hxml(save_form(client, task, MADRID, values, **changes))

    assert stored_deadline(task) == (due_at, all_day)


def test_the_form_carries_the_schedule_it_shows_in_hidden_fields(user):
    client, task = create_deadline(user, "2026-06-10", "09:30", NEW_YORK)

    in_new_york = open_form(client, task, NEW_YORK)
    in_madrid = open_form(client, task, MADRID)

    assert (in_new_york["due_date_shown"], in_new_york["due_time_shown"]) == (
        "2026-06-10",
        "09:30",
    )
    assert (in_madrid["due_date_shown"], in_madrid["due_time_shown"]) == (
        "2026-06-10",
        "15:30",
    )
    assert in_madrid["due_date_shown"] == in_madrid["due_date"]
    assert in_madrid["due_time_shown"] == in_madrid["due_time"]


def test_the_form_of_a_task_with_no_deadline_carries_empty_hidden_fields(user):
    client, task = create_deadline(user, "", "", NEW_YORK)

    values = open_form(client, task, NEW_YORK)

    assert (values["due_date_shown"], values["due_time_shown"]) == ("", "")


def test_a_refused_save_hands_back_the_schedule_the_form_showed(user):
    # The refusal is drawn in Madrid, but the hidden values must stay the ones New York
    # showed: recomputed in Madrid they would say 15:30 and the next save would move it.
    client, task = create_deadline(user, "2026-06-10", "09:30", NEW_YORK)
    stored = stored_deadline(task)
    values = open_form(client, task, NEW_YORK)

    refused = screen_values(
        save_form(client, task, MADRID, values, title=""), status=422
    )

    assert (refused["due_date_shown"], refused["due_time_shown"]) == (
        values["due_date_shown"],
        values["due_time_shown"],
    )
    assert_hxml(save_form(client, task, MADRID, refused, title="Fixed"))
    assert stored_deadline(task) == stored


def test_a_title_only_save_from_a_stale_form_keeps_the_newer_deadline(user):
    client, task = create_deadline(user, "2026-06-10", "09:30", NEW_YORK)
    values = open_form(client, task, NEW_YORK)
    newer = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)
    # Another device moves the deadline while this form is open.
    Task.objects.filter(pk=task.pk).update(due_at=newer)

    assert_hxml(save_form(client, task, NEW_YORK, values, title="Renamed"))

    assert stored_deadline(task) == (newer, False)


def test_a_stale_form_that_showed_no_deadline_keeps_the_one_set_since(user):
    client, task = create_deadline(user, "", "", NEW_YORK)
    values = open_form(client, task, NEW_YORK)
    newer = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)
    Task.objects.filter(pk=task.pk).update(due_at=newer)

    assert_hxml(save_form(client, task, NEW_YORK, values, title="Renamed"))

    assert stored_deadline(task) == (newer, False)


def test_a_stale_form_still_applies_a_schedule_the_person_changed(user):
    client, task = create_deadline(user, "2026-06-10", "09:30", NEW_YORK)
    values = open_form(client, task, NEW_YORK)
    Task.objects.filter(pk=task.pk).update(
        due_at=datetime(2026, 6, 20, 14, 0, tzinfo=UTC)
    )

    assert_hxml(save_form(client, task, NEW_YORK, values, due_time="11:00"))

    assert stored_deadline(task) == (datetime(2026, 6, 10, 15, 0, tzinfo=UTC), False)


def test_a_new_task_stores_its_deadline_though_the_hidden_values_match(user):
    # A task that is not saved yet already has a primary key (the id has a default), so
    # "has a key" cannot tell a new task from an edited one.
    client = csrf_client()
    client.force_login(user)
    values = screen_values(client.get(reverse("todo:task-new")))
    assert (values["due_date_shown"], values["due_time_shown"]) == ("", "")

    response = client.post(
        reverse("todo:task-new"),
        {
            **values,
            "title": "Pay rent",
            "due_date": "2026-06-10",
            "due_time": "09:30",
            "due_date_shown": "2026-06-10",
            "due_time_shown": "09:30",
        },
    )

    assert_hxml(response, status=201)
    assert stored_deadline(Task.objects.get(user=user)) == (
        datetime(2026, 6, 10, 13, 30, tzinfo=UTC),
        False,
    )


def test_hidden_values_that_equal_a_forged_new_schedule_only_keep_the_stored_one(user):
    client, task = create_deadline(user, "2026-06-10", "09:30", NEW_YORK)
    stored = stored_deadline(task)
    values = open_form(client, task, NEW_YORK)

    assert_hxml(
        save_form(
            client,
            task,
            NEW_YORK,
            values,
            due_date="2026-06-15",
            due_date_shown="2026-06-15",
        )
    )

    assert stored_deadline(task) == stored


def test_hidden_values_that_are_not_a_schedule_fall_back_to_the_visible_fields(user):
    client, task = create_deadline(user, "2026-06-10", "09:30", NEW_YORK)
    values = open_form(client, task, NEW_YORK)

    assert_hxml(
        save_form(
            client,
            task,
            NEW_YORK,
            values,
            due_date="2026-06-16",
            due_time="08:00",
            due_date_shown="not-a-date",
            due_time_shown="zz",
        )
    )

    assert stored_deadline(task) == (datetime(2026, 6, 16, 12, 0, tzinfo=UTC), False)


def test_oversized_hidden_values_are_bounded_and_scrubbed_in_a_refused_form(user):
    client, task = create_deadline(user, "2026-06-10", "09:30", NEW_YORK)
    stored = stored_deadline(task)
    values = open_form(client, task, NEW_YORK)

    refused = screen_values(
        save_form(
            client,
            task,
            NEW_YORK,
            values,
            title="",
            due_date_shown="\x1b" * 5 + "9" * 1_000_000,
            due_time_shown="\x1b" * 50,
        ),
        status=422,
    )

    assert len(refused["due_date_shown"]) <= 65
    assert len(refused["due_time_shown"]) <= 65
    assert not {"\x1b"} & set(refused["due_date_shown"] + refused["due_time_shown"])
    assert stored_deadline(task) == stored
