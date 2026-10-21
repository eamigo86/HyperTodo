"""Bounded, session-authorized Expo ticket and receipt processing."""

import json
import time
from datetime import timedelta
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from django.conf import settings
from django.db import OperationalError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import PushDelivery, PushDevice, Task
from .realtime_auth import fresh_identity

_SEND_URL = "https://exp.host/--/api/v2/push/send"
_RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"
_MAX_RESPONSE_BYTES = 65_536
_MAX_ATTEMPTS = 5
_MAX_AGE = timedelta(hours=24)
_RECEIPT_DELAY = timedelta(minutes=15)
_LEASE = timedelta(seconds=60)


class RetryablePushError(Exception):
    """A bounded retry is appropriate for network, rate or server failure."""


class PermanentPushError(Exception):
    """The response cannot safely be retried without operator correction."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        """Never forward an Expo token to a redirected destination."""
        return None


class PushTransport(Protocol):
    """Injectable delivery boundary for deterministic worker tests."""

    def send(self, token: str, data: dict) -> dict:
        """Return an Expo ticket."""
        ...

    def get_receipt(self, ticket_id: str) -> dict:
        """Return a ticket receipt."""
        ...


class ExpoTransport:
    """Small HTTPS-only Expo client with fixed endpoints and bounded responses."""

    def _request(self, url: str, payload: dict) -> dict:
        request = Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with build_opener(_NoRedirect).open(request, timeout=5) as response:
                if response.status != 200:
                    if response.status == 429 or response.status >= 500:
                        raise RetryablePushError
                    raise PermanentPushError
                body = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            if error.code == 429 or error.code >= 500:
                raise RetryablePushError from error
            raise PermanentPushError from error
        except (URLError, TimeoutError, OSError) as error:
            raise RetryablePushError from error
        if len(body) > _MAX_RESPONSE_BYTES:
            raise PermanentPushError
        try:
            result = json.loads(body)
        except (UnicodeError, ValueError) as error:
            raise PermanentPushError from error
        if not isinstance(result, dict):
            raise PermanentPushError
        return result

    def send(self, token: str, data: dict) -> dict:
        """Return the one-message Expo ticket, not a delivery assertion."""
        result = self._request(
            _SEND_URL,
            {
                "to": token,
                "title": "Task updated",
                "body": "Open HyperTodo to view updates.",
                "data": data,
            },
        )
        ticket = result.get("data")
        if not isinstance(ticket, dict):
            raise PermanentPushError
        return ticket

    def get_receipt(self, ticket_id: str) -> dict:
        """Look up a ticket after the receipt delay."""
        result = self._request(_RECEIPTS_URL, {"ids": [ticket_id]})
        data = result.get("data")
        if not isinstance(data, dict) or not isinstance(data.get(ticket_id), dict):
            raise RetryablePushError
        return data[ticket_id]


def _claim_once() -> PushDelivery | None:
    now = timezone.now()
    with transaction.atomic():
        row = (
            PushDelivery.objects.select_for_update()
            .filter(
                status__in=(PushDelivery.Status.PENDING, PushDelivery.Status.RECEIPT),
                next_attempt_at__lte=now,
            )
            .filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now))
            .order_by("next_attempt_at", "pk")
            .first()
        )
        if row is None:
            return None
        row.lease_id = uuid4()
        row.lease_until = now + _LEASE
        row.attempts += 1
        row.save(update_fields=("lease_id", "lease_until", "attempts"))
        return row


def _claim() -> PushDelivery | None:
    """Retry short shared-cache SQLite lock races without claiming twice."""
    for attempt in range(5):
        try:
            return _claim_once()
        except OperationalError as error:
            if "locked" not in str(error).lower() or attempt == 4:
                raise
            time.sleep(0.02 * (attempt + 1))
    return None


def _finish(
    row: PushDelivery,
    *,
    status: str,
    ticket_id: str = "",
    delay: timedelta | None = None,
) -> None:
    """Apply only this worker's lease; a late worker cannot overwrite another."""
    now = timezone.now()
    updates = {
        "status": status,
        "ticket_id": ticket_id,
        "lease_id": None,
        "lease_until": None,
        "next_attempt_at": now + (delay or timedelta()),
    }
    PushDelivery.objects.filter(pk=row.pk, lease_id=row.lease_id).update(**updates)


def _retry(row: PushDelivery, *, receipt: bool = False) -> None:
    if row.attempts >= _MAX_ATTEMPTS or timezone.now() - row.created_at >= _MAX_AGE:
        _finish(row, status=PushDelivery.Status.DROPPED)
        return
    delay = (
        _RECEIPT_DELAY
        if receipt
        else timedelta(seconds=min(30 * 2 ** (row.attempts - 1), 3600))
    )
    _finish(row, status=row.status, ticket_id=row.ticket_id, delay=delay)


def _authorized_device(row: PushDelivery) -> PushDevice | None:
    device = PushDevice.objects.select_related("user").filter(pk=row.device_id).first()
    if (
        device is None
        or device.registration_version != row.registration_version
        or device.user_id != row.owner_id
        or not device.user.is_active
        or device.auth_hash != device.user.get_session_auth_hash()
        or Task.objects.filter(pk=row.task_id).values_list("user_id", flat=True).first()
        != row.owner_id
    ):
        return None
    identity = fresh_identity(device.session_id)
    if (
        identity is None
        or identity.user_id != str(row.owner_id)
        or identity.using != row._state.db
    ):
        return None
    return device


def _invalid_token(row: PushDelivery) -> None:
    # Never remove a newer token if the installation rotated during HTTP I/O.
    PushDevice.objects.filter(
        pk=row.device_id, registration_version=row.registration_version
    ).delete()
    _finish(row, status=PushDelivery.Status.DROPPED)


def _handle_result(row: PushDelivery, result: dict) -> None:
    if result.get("status") == "ok":
        if row.status == PushDelivery.Status.PENDING:
            ticket_id = result.get("id")
            if not isinstance(ticket_id, str) or not (1 <= len(ticket_id) <= 128):
                _finish(row, status=PushDelivery.Status.DROPPED)
                return
            _finish(
                row,
                status=PushDelivery.Status.RECEIPT,
                ticket_id=ticket_id,
                delay=_RECEIPT_DELAY,
            )
        else:
            _finish(row, status=PushDelivery.Status.DONE, ticket_id=row.ticket_id)
        return
    details = result.get("details")
    error = details.get("error") if isinstance(details, dict) else None
    if error == "DeviceNotRegistered":
        _invalid_token(row)
    elif error == "MessageRateExceeded":
        _retry(row, receipt=row.status == PushDelivery.Status.RECEIPT)
    else:
        _finish(row, status=PushDelivery.Status.DROPPED)


def dispatch_due(*, transport: PushTransport | None = None, limit: int = 20) -> int:
    """Claim and process at most ``limit`` due deliveries; never run in a signal."""
    if not settings.PUSH_NOTIFICATIONS_ENABLED:
        return 0
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    # Retain terminal outcomes briefly. Maintenance must not contend with claims.
    stale = PushDelivery.objects.filter(
        status__in=(PushDelivery.Status.DONE, PushDelivery.Status.DROPPED),
        created_at__lt=timezone.now() - timedelta(days=7),
    )
    try:
        if stale.exists():
            stale.delete()
    except OperationalError as error:
        if "locked" not in str(error).lower():
            raise  # Best-effort retention can wait for the next worker cycle.
    transport = transport or ExpoTransport()
    processed = 0
    for _ in range(limit):
        row = _claim()
        if row is None:
            break
        processed += 1
        if timezone.now() - row.created_at >= _MAX_AGE:
            _finish(row, status=PushDelivery.Status.DROPPED)
            continue
        device = _authorized_device(row)
        if device is None:
            _finish(row, status=PushDelivery.Status.DROPPED)
            continue
        try:
            if row.status == PushDelivery.Status.PENDING:
                result = transport.send(
                    device.expo_token,
                    {
                        "kind": "tasks",
                        "registrationVersion": str(row.registration_version),
                    },
                )
            else:
                result = transport.get_receipt(row.ticket_id)
        except RetryablePushError:
            _retry(row, receipt=row.status == PushDelivery.Status.RECEIPT)
        except PermanentPushError:
            _finish(row, status=PushDelivery.Status.DROPPED)
        else:
            if isinstance(result, dict):
                _handle_result(row, result)
            else:
                _finish(row, status=PushDelivery.Status.DROPPED)
    return processed
