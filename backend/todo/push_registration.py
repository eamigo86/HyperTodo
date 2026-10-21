"""Session-bound persistence for Expo push destinations."""

from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.sessions.models import Session
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from .models import PushDevice
from .realtime_auth import Identity, fresh_identity, same_identity
from .session_contract import session_binding

MAX_DEVICES_PER_USER = 10


class DeviceLimitReached(Exception):
    """The account already has the allowed number of active installations."""


class StaleSession(Exception):
    """The cookie session ceased to authorize registration during this request."""


class RegistrationConflict(Exception):
    """An installation or token is already owned by a different registration."""


def _current_session(request: HttpRequest, user: AbstractBaseUser) -> Session:
    """Recheck current auth using the database, not cached request.user."""
    key = request.session.session_key
    expected = Identity(user._state.db, str(user.pk), session_binding(request))
    if not same_identity(expected, fresh_identity(key)):
        raise StaleSession
    try:
        return Session.objects.get(session_key=key, expire_date__gt=timezone.now())
    except Session.DoesNotExist as error:
        raise StaleSession from error


@transaction.atomic
def register_device(
    request: HttpRequest,
    installation_id: UUID,
    expo_token: str,
    expected_version: UUID | None,
) -> tuple[bool, UUID]:
    """Create or compare-and-swap one installation under the current cookie session.

    Returns:
        A created flag and new opaque registration version.
    """
    user_model = get_user_model()
    try:
        user = user_model.objects.select_for_update().get(pk=request.user.pk)
    except user_model.DoesNotExist as error:
        raise StaleSession from error
    session = _current_session(request, user)
    # A password reset can invalidate sessions without deleting their rows. Prune
    # those dormant registrations before the bounded per-account quota is counted.
    for prior in PushDevice.objects.filter(user=user).only("pk", "session_id"):
        identity = fresh_identity(prior.session_id)
        if identity is None or identity.user_id != str(user.pk):
            prior.delete()
    device = (
        PushDevice.objects.select_for_update()
        .filter(installation_id=installation_id)
        .first()
    )
    if device is not None and fresh_identity(device.session_id) is None:
        device.delete()
        device = None
    if device is not None:
        if (
            device.user_id != user.pk
            or device.session_id != session.session_key
            or expected_version != device.registration_version
        ):
            raise RegistrationConflict
    elif expected_version is not None:
        raise RegistrationConflict
    token_owner = (
        PushDevice.objects.select_for_update()
        .filter(expo_token=expo_token)
        .exclude(installation_id=installation_id)
        .first()
    )
    if token_owner is not None:
        if fresh_identity(token_owner.session_id) is not None:
            raise RegistrationConflict
        token_owner.delete()
    version = uuid4()
    if device is None:
        if PushDevice.objects.filter(user=user).count() >= MAX_DEVICES_PER_USER:
            raise DeviceLimitReached
        PushDevice.objects.create(
            user=user,
            session=session,
            installation_id=installation_id,
            expo_token=expo_token,
            registration_version=version,
            auth_hash=user.get_session_auth_hash(),
        )
        return True, version
    device.expo_token = expo_token
    device.registration_version = version
    device.auth_hash = user.get_session_auth_hash()
    device.save(
        update_fields=("expo_token", "registration_version", "auth_hash", "updated_at")
    )
    return False, version


def revoke_device(request: HttpRequest, installation_id: UUID, version: UUID) -> None:
    """Remove only the exact registration version for this cookie session."""
    PushDevice.objects.filter(
        user=request.user,
        session_id=request.session.session_key,
        installation_id=installation_id,
        registration_version=version,
    ).delete()
