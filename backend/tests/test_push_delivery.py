"""Transactional Task alerts and bounded Expo delivery; no external requests."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import transaction
from django.test import Client, override_settings
from django.utils import timezone

from todo.models import PushDelivery, PushDevice, Task
from todo.push_delivery import dispatch_due

pytestmark = pytest.mark.django_db(transaction=True)


class FakeTransport:
    def __init__(self, *, ticket=None, receipt=None):
        self.ticket = ticket or {"status": "ok", "id": "ticket-1"}
        self.receipt = receipt or {"status": "ok"}
        self.sent = []
        self.polled = []

    def send(self, token, data):
        self.sent.append((token, data))
        return self.ticket

    def get_receipt(self, ticket_id):
        self.polled.append(ticket_id)
        return self.receipt


def registered(user, token="ExpoPushToken[test_one]"):
    client = Client()
    client.force_login(user)
    device = PushDevice.objects.create(
        user=user,
        session_id=client.session.session_key,
        installation_id=uuid4(),
        expo_token=token,
        auth_hash=user.get_session_auth_hash(),
    )
    return client, device


@override_settings(PUSH_NOTIFICATIONS_ENABLED=True)
def test_task_update_outbox_is_transactional_and_ignores_create_noop_raw(user):
    from todo.realtime_config import get_realtime_config

    assert get_realtime_config() is None  # Push remains independent of Redis/SSE.
    _, device = registered(user)
    task = Task.objects.create(user=user, title="Private title")
    assert not PushDelivery.objects.exists()
    task.save(update_fields=("title",))
    assert not PushDelivery.objects.exists()
    with pytest.raises(RuntimeError), transaction.atomic():
        task.title = "Changed"
        task.save(update_fields=("title",))
        assert PushDelivery.objects.filter(device=device).count() == 1
        raise RuntimeError("rollback")
    assert not PushDelivery.objects.exists()
    task.title = "Changed again"
    task.save(update_fields=("title",))
    delivery = PushDelivery.objects.get()
    assert delivery.owner_id == user.pk
    assert delivery.registration_version == device.registration_version


@override_settings(PUSH_NOTIFICATIONS_ENABLED=True)
def test_send_receipt_and_generic_payload(user):
    _, device = registered(user)
    task = Task.objects.create(user=user, title="Secret title", notes="Private notes")
    task.title = "Changed secret"
    task.save(update_fields=("title",))
    transport = FakeTransport()
    assert dispatch_due(transport=transport, limit=1) == 1
    delivery = PushDelivery.objects.get()
    assert delivery.status == PushDelivery.Status.RECEIPT
    assert delivery.ticket_id == "ticket-1"
    assert transport.sent[0][0] == device.expo_token
    data = transport.sent[0][1]
    assert data == {
        "kind": "tasks",
        "registrationVersion": str(device.registration_version),
    }
    assert "Secret" not in str(data) and str(task.pk) not in str(data)
    assert dispatch_due(transport=transport, limit=1) == 0
    delivery.next_attempt_at = timezone.now() - timedelta(seconds=1)
    delivery.save(update_fields=("next_attempt_at",))
    assert dispatch_due(transport=transport, limit=1) == 1
    delivery.refresh_from_db()
    assert delivery.status == PushDelivery.Status.DONE
    assert transport.polled == ["ticket-1"]


@override_settings(PUSH_NOTIFICATIONS_ENABLED=True)
def test_stale_owner_session_and_registration_never_send(user, other_user):
    client, device = registered(user)
    task = Task.objects.create(user=user, title="First")
    task.title = "Second"
    task.save(update_fields=("title",))
    transport = FakeTransport()
    task.user = other_user
    task.save(update_fields=("user",))
    assert dispatch_due(transport=transport, limit=10) >= 1
    assert transport.sent == []
    task.user = user
    task.save(update_fields=("user",))
    client.logout()
    assert dispatch_due(transport=transport, limit=10) >= 1
    assert transport.sent == []
    assert not PushDevice.objects.filter(pk=device.pk).exists()


@override_settings(PUSH_NOTIFICATIONS_ENABLED=True)
def test_invalid_ticket_revokes_only_matching_registration_version(user):
    _, device = registered(user)
    task = Task.objects.create(user=user, title="First")
    task.title = "Second"
    task.save(update_fields=("title",))
    transport = FakeTransport(
        ticket={"status": "error", "details": {"error": "DeviceNotRegistered"}}
    )
    assert dispatch_due(transport=transport, limit=1) == 1
    assert not PushDevice.objects.filter(pk=device.pk).exists()
    assert PushDelivery.objects.get().status == PushDelivery.Status.DROPPED


def test_disabled_setting_produces_no_outbox_or_transport(user):
    _, device = registered(user)
    task = Task.objects.create(user=user, title="First")
    task.title = "Second"
    task.save(update_fields=("title",))
    transport = FakeTransport()
    assert not PushDelivery.objects.exists()
    assert dispatch_due(transport=transport) == 0
    assert transport.sent == []
    assert PushDevice.objects.filter(pk=device.pk).exists()


@override_settings(PUSH_NOTIFICATIONS_ENABLED=True)
def test_raw_save_and_queryset_update_do_not_emit_alerts(user):
    registered(user)
    task = Task.objects.create(user=user, title="First")
    task.title = "Raw fixture"
    task.save_base(raw=True, force_update=True)
    Task.objects.filter(pk=task.pk).update(title="Bulk update")
    assert not PushDelivery.objects.exists()


@override_settings(PUSH_NOTIFICATIONS_ENABLED=True)
def test_changed_password_expired_session_and_token_rotation_drop_pending(user):
    client, device = registered(user)
    task = Task.objects.create(user=user, title="First")
    task.title = "Second"
    task.save(update_fields=("title",))
    transport = FakeTransport()
    user.set_password("different-password")
    user.save(update_fields=("password",))
    assert dispatch_due(transport=transport, limit=1) == 1
    assert transport.sent == []
    assert PushDelivery.objects.get().status == PushDelivery.Status.DROPPED
    # The session row still exists, but fresh auth must refuse its old hash.
    assert client.session.session_key
    device.refresh_from_db()


@override_settings(PUSH_NOTIFICATIONS_ENABLED=True)
def test_late_invalid_ticket_cannot_delete_rotated_token(user):
    _, device = registered(user)
    task = Task.objects.create(user=user, title="First")
    task.title = "Second"
    task.save(update_fields=("title",))

    class RotatingTransport(FakeTransport):
        def send(self, token, data):
            self.sent.append((token, data))
            PushDevice.objects.filter(pk=device.pk).update(
                expo_token="ExpoPushToken[new_token]", registration_version=uuid4()
            )
            return {"status": "error", "details": {"error": "DeviceNotRegistered"}}

    transport = RotatingTransport()
    assert dispatch_due(transport=transport, limit=1) == 1
    assert PushDevice.objects.filter(pk=device.pk).exists()
    assert PushDelivery.objects.get().status == PushDelivery.Status.DROPPED


@override_settings(PUSH_NOTIFICATIONS_ENABLED=True)
def test_transient_failure_retries_with_bounds(user):
    registered(user)
    task = Task.objects.create(user=user, title="First")
    task.title = "Second"
    task.save(update_fields=("title",))

    class Unavailable(FakeTransport):
        def send(self, token, data):
            from todo.push_delivery import RetryablePushError

            raise RetryablePushError

    transport = Unavailable()
    for attempt in range(1, 6):
        assert dispatch_due(transport=transport, limit=1) == 1
        delivery = PushDelivery.objects.get()
        assert delivery.attempts == attempt
        if attempt < 5:
            assert delivery.status == PushDelivery.Status.PENDING
            assert delivery.next_attempt_at > timezone.now()
            delivery.next_attempt_at = timezone.now() - timedelta(seconds=1)
            delivery.save(update_fields=("next_attempt_at",))
    assert PushDelivery.objects.get().status == PushDelivery.Status.DROPPED
    assert dispatch_due(transport=transport, limit=1) == 0


@override_settings(PUSH_NOTIFICATIONS_ENABLED=True)
def test_receipt_invalid_token_revokes_and_missing_receipt_retries(user):
    _, device = registered(user)
    task = Task.objects.create(user=user, title="First")
    task.title = "Second"
    task.save(update_fields=("title",))
    transport = FakeTransport(
        receipt={"status": "error", "details": {"error": "DeviceNotRegistered"}}
    )
    assert dispatch_due(transport=transport, limit=1) == 1
    delivery = PushDelivery.objects.get()
    delivery.next_attempt_at = timezone.now() - timedelta(seconds=1)
    delivery.save(update_fields=("next_attempt_at",))
    assert dispatch_due(transport=transport, limit=1) == 1
    assert not PushDevice.objects.filter(pk=device.pk).exists()
    assert PushDelivery.objects.get().status == PushDelivery.Status.DROPPED


@override_settings(PUSH_NOTIFICATIONS_ENABLED=True)
def test_command_defaults_to_preview_and_requires_explicit_send(
    user, monkeypatch, capsys
):
    from django.core.management import call_command

    registered(user)
    task = Task.objects.create(user=user, title="First")
    task.title = "Second"
    task.save(update_fields=("title",))
    calls = []
    monkeypatch.setattr(
        "todo.management.commands.dispatch_push.dispatch_due",
        lambda **kw: calls.append(kw) or 1,
    )
    call_command("dispatch_push")
    assert "1 due" in capsys.readouterr().out
    assert calls == []
    call_command("dispatch_push", send=True, limit=3)
    assert calls == [{"limit": 3}]


def test_expo_transport_uses_fixed_https_endpoint_and_bounded_body(monkeypatch):
    from todo.push_delivery import ExpoTransport, PermanentPushError

    seen = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, amount):
            seen.append(amount)
            return b'{"data":{"status":"ok","id":"ticket"}}'

    class Opener:
        def open(self, request, *, timeout):
            seen.append((request.full_url, timeout))
            return Response()

    monkeypatch.setattr("todo.push_delivery.build_opener", lambda *_: Opener())
    assert (
        ExpoTransport().send("ExpoPushToken[safe]", {"kind": "tasks"})["id"] == "ticket"
    )
    assert seen == [("https://exp.host/--/api/v2/push/send", 5), 65_537]

    class Oversized(Response):
        def read(self, amount):
            return b"x" * amount

    monkeypatch.setattr(
        "todo.push_delivery.build_opener",
        lambda *_: type("O", (), {"open": lambda *a, **kw: Oversized()})(),
    )
    with pytest.raises(PermanentPushError):
        ExpoTransport().send("ExpoPushToken[safe]", {"kind": "tasks"})


@override_settings(PUSH_NOTIFICATIONS_ENABLED=True)
def test_parallel_workers_claim_distinct_rows_on_sqlite(user):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    registered(user)
    for index in range(2):
        task = Task.objects.create(user=user, title=f"Task {index}")
        task.title = f"Updated {index}"
        task.save(update_fields=("title",))
    barrier = Barrier(2)

    class ParallelTransport(FakeTransport):
        def send(self, token, data):
            barrier.wait(timeout=5)
            return super().send(token, data)

    transport = ParallelTransport()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(dispatch_due, transport=transport, limit=1) for _ in range(2)
        ]
        results = [f.result() for f in futures]
    assert results == [1, 1]
    assert len(transport.sent) == 2
    assert PushDelivery.objects.filter(status=PushDelivery.Status.RECEIPT).count() == 2


@override_settings(PUSH_NOTIFICATIONS_ENABLED=True)
def test_expired_session_and_preexisting_rotation_drop_without_send(user):
    from django.contrib.sessions.models import Session

    _, device = registered(user)
    task = Task.objects.create(user=user, title="First")
    task.title = "Second"
    task.save(update_fields=("title",))
    transport = FakeTransport()
    Session.objects.filter(pk=device.session_id).update(
        expire_date=timezone.now() - timedelta(seconds=1)
    )
    assert dispatch_due(transport=transport, limit=1) == 1
    assert transport.sent == []
    assert PushDelivery.objects.get().status == PushDelivery.Status.DROPPED

    # A fresh login can create a newer registration; old queued work is not adopted.
    _, second = registered(user, token="ExpoPushToken[second]")
    task.title = "Third"
    task.save(update_fields=("title",))
    second.registration_version = uuid4()
    second.save(update_fields=("registration_version",))
    assert dispatch_due(transport=transport, limit=10) >= 1
    assert transport.sent == []


@override_settings(PUSH_NOTIFICATIONS_ENABLED=True)
def test_missing_receipt_is_retryable_not_claimed_as_delivery(user):
    from todo.push_delivery import RetryablePushError

    registered(user)
    task = Task.objects.create(user=user, title="First")
    task.title = "Second"
    task.save(update_fields=("title",))

    class MissingReceipt(FakeTransport):
        def get_receipt(self, ticket_id):
            self.polled.append(ticket_id)
            raise RetryablePushError

    transport = MissingReceipt()
    assert dispatch_due(transport=transport, limit=1) == 1
    delivery = PushDelivery.objects.get()
    delivery.next_attempt_at = timezone.now() - timedelta(seconds=1)
    delivery.save(update_fields=("next_attempt_at",))
    assert dispatch_due(transport=transport, limit=1) == 1
    delivery.refresh_from_db()
    assert delivery.status == PushDelivery.Status.RECEIPT
    assert delivery.next_attempt_at > timezone.now()
    assert delivery.attempts == 2
    assert transport.polled == ["ticket-1"]


def test_send_command_refuses_disabled_configuration():
    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="disabled"):
        call_command("dispatch_push", send=True)


@override_settings(PUSH_NOTIFICATIONS_ENABLED=True)
def test_dispatch_prunes_terminal_rows_after_seven_days(user):
    registered(user)
    task = Task.objects.create(user=user, title="First")
    task.title = "Second"
    task.save(update_fields=("title",))
    old = PushDelivery.objects.get()
    PushDelivery.objects.filter(pk=old.pk).update(
        status=PushDelivery.Status.DONE,
        created_at=timezone.now() - timedelta(days=8),
    )
    assert dispatch_due(transport=FakeTransport(), limit=1) == 0
    assert not PushDelivery.objects.exists()


@pytest.mark.parametrize("status", [429, 503])
def test_expo_rate_and_server_errors_are_retryable(monkeypatch, status):
    from urllib.error import HTTPError

    from todo.push_delivery import ExpoTransport, RetryablePushError

    class Opener:
        def open(self, request, *, timeout):
            raise HTTPError(request.full_url, status, "unavailable", None, None)

    monkeypatch.setattr("todo.push_delivery.build_opener", lambda *_: Opener())
    with pytest.raises(RetryablePushError):
        ExpoTransport().send("ExpoPushToken[safe]", {"kind": "tasks"})
