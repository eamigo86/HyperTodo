"""Authenticated, CSRF-protected Expo destination registration API."""

import json
import re
from uuid import UUID

from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.middleware.csrf import get_token

from .push_registration import (
    DeviceLimitReached,
    RegistrationConflict,
    StaleSession,
    register_device,
    revoke_device,
)

_TOKEN = re.compile(r"(?:Expo|Exponent)PushToken\[[A-Za-z0-9_-]{1,220}\]")
_MAX_BODY = 1024


def _error(code: str, status: int) -> JsonResponse:
    return JsonResponse({"error": code}, status=status)


def _payload(request: HttpRequest, keys: set[str]) -> dict | None:
    if request.content_type != "application/json" or len(request.body) > _MAX_BODY:
        return None
    try:
        value = json.loads(request.body)
    except UnicodeDecodeError, json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or set(value) != keys:
        return None
    return value


def _installation(value: object) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = UUID(value)
    except ValueError:
        return None
    return parsed if parsed.version == 4 and str(parsed) == value else None


def push_registrations(request: HttpRequest) -> HttpResponse:
    """Bootstrap CSRF, register or revoke one session-owned installation."""
    if not getattr(request, "hv_realtime_v1", False):
        return _error("modern-contract-required", 404)
    if not request.user.is_authenticated:
        return _error("authentication-required", 401)
    if request.method == "GET":
        result = {"csrfToken": get_token(request)}
        if request.GET:
            installation_id = _installation(request.GET.get("installationId"))
            if installation_id is None or set(request.GET) != {"installationId"}:
                return _error("invalid-registration", 400)
            from .models import PushDevice

            device = PushDevice.objects.filter(
                user=request.user,
                session_id=request.session.session_key,
                installation_id=installation_id,
            ).first()
            result["registrationVersion"] = (
                str(device.registration_version) if device is not None else None
            )
        return JsonResponse(result)
    if request.method not in ("POST", "DELETE"):
        return HttpResponseNotAllowed(("GET", "POST", "DELETE"))
    keys = (
        {"installationId", "expoPushToken"}
        if request.method == "POST"
        else {"installationId", "registrationVersion"}
    )
    payload = _payload(request, keys)
    if payload is None and request.method == "POST":
        payload = _payload(request, keys | {"registrationVersion"})
    if payload is None:
        return _error("invalid-registration", 400)
    installation_id = _installation(payload["installationId"])
    if installation_id is None:
        return _error("invalid-registration", 400)
    raw_version = payload.get("registrationVersion")
    version = _installation(raw_version) if raw_version is not None else None
    if raw_version is not None and version is None:
        return _error("invalid-registration", 400)
    if request.method == "DELETE":
        if version is None:
            return _error("invalid-registration", 400)
        revoke_device(request, installation_id, version)
        return HttpResponse(status=204)
    token = payload["expoPushToken"]
    if not isinstance(token, str) or _TOKEN.fullmatch(token) is None:
        return _error("invalid-registration", 400)
    try:
        created, new_version = register_device(request, installation_id, token, version)
    except DeviceLimitReached:
        return _error("device-limit-reached", 429)
    except StaleSession:
        return _error("session-binding-mismatch", 409)
    except RegistrationConflict:
        return _error("registration-conflict", 409)
    return JsonResponse(
        {"registered": True, "registrationVersion": str(new_version)},
        status=201 if created else 200,
    )
