"""Transactional mutation boundary for private TODO data."""

import hashlib
import secrets
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from django.contrib.auth.models import AbstractBaseUser
from django.core.files.base import ContentFile
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import BiometricCredential, Category, Profile, Task

BIOMETRIC_TOKEN_TTL = timedelta(days=30)


def _biometric_hash(raw_token: str) -> str:
    # Plain SHA-256 is deliberate: the token is 256 bits of secrets.token_urlsafe,
    # so a slow KDF adds no brute-force resistance and only hands attackers a
    # CPU-exhaustion lever on an unauthenticated endpoint.
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _password_fingerprint(user: AbstractBaseUser) -> str:
    # user.password is already a salted PBKDF2 digest; hashing it again only keeps the
    # stored hash out of a second table.
    return hashlib.sha256(user.password.encode()).hexdigest()


PROFILE_FIELDS = ("first_name", "last_name", "email")


@transaction.atomic
def update_profile(
    *, user: AbstractBaseUser, first_name: str, last_name: str, email: str
) -> AbstractBaseUser:
    """Save the account details the settings screen owns.

    Args:
        user: Account being edited.
        first_name: Replacement given name, possibly empty.
        last_name: Replacement family name, possibly empty.
        email: Replacement address, possibly empty.

    Returns:
        The same user instance, updated.

    Raises:
        ValidationError: If the account data is invalid.
    """
    user.first_name = first_name
    user.last_name = last_name
    user.email = email
    # Only the fields this service writes. A bare full_clean() re-validates the
    # WHOLE row, so an account whose stored username predates
    # UnicodeUsernameValidator would 500 here on every save, on a field the
    # settings form does not even expose.
    user.full_clean(
        exclude=[
            field.name
            for field in user._meta.fields
            if field.name not in PROFILE_FIELDS
        ]
    )
    user.save(update_fields=PROFILE_FIELDS)
    return user


@transaction.atomic
def create_category(*, user: AbstractBaseUser, name: str, color: str) -> Category:
    """Create a validated category for one user.

    Args:
        user: Category owner.
        name: Display name.
        color: Supported color value.

    Returns:
        Persisted category.

    Raises:
        ValidationError: If category data is invalid.
    """
    category = Category(user=user, name=name, color=color)
    category.full_clean()
    category.save()
    return category


@transaction.atomic
def update_category(
    *, user: AbstractBaseUser, category_id: UUID, name: str, color: str
) -> Category:
    """Update an owned category.

    Args:
        user: Category owner.
        category_id: Category identifier.
        name: Replacement display name.
        color: Replacement supported color.

    Returns:
        Updated category.

    Raises:
        Http404: If the category is not owned by the user.
        ValidationError: If category data is invalid.
    """
    category = get_object_or_404(Category, pk=category_id, user=user)
    category.name = name
    category.color = color
    category.full_clean()
    category.save(update_fields=("name", "color", "updated_at"))
    return category


@transaction.atomic
def delete_category(*, user: AbstractBaseUser, category_id: UUID) -> None:
    """Delete an owned category while preserving its tasks.

    Args:
        user: Category owner.
        category_id: Category identifier.

    Raises:
        Http404: If the category is not owned by the user.
    """
    get_object_or_404(Category, pk=category_id, user=user).delete()


@transaction.atomic
def create_task(
    *,
    user: AbstractBaseUser,
    title: str,
    notes: str,
    category: Category | None,
    due_at: datetime | None,
) -> Task:
    """Create a validated task for one user.

    Args:
        user: Task owner.
        title: Task title.
        notes: Optional details.
        category: Optional category owned by the user.
        due_at: Optional timezone-aware deadline.

    Returns:
        Persisted task.

    Raises:
        ValidationError: If task data is invalid.
    """
    task = Task(user=user, title=title, notes=notes, category=category, due_at=due_at)
    task.full_clean()
    task.save()
    return task


@transaction.atomic
def update_task(
    *,
    user: AbstractBaseUser,
    task_id: UUID,
    title: str,
    notes: str,
    category: Category | None,
    due_at: datetime | None,
) -> Task:
    """Update an owned task.

    Args:
        user: Task owner.
        task_id: Task identifier.
        title: Replacement title.
        notes: Replacement details.
        category: Replacement optional category.
        due_at: Replacement optional deadline.

    Returns:
        Updated task.

    Raises:
        Http404: If the task is not owned by the user.
        ValidationError: If task data is invalid.
    """
    task = get_object_or_404(Task, pk=task_id, user=user)
    task.title = title
    task.notes = notes
    task.category = category
    task.due_at = due_at
    task.full_clean()
    task.save(update_fields=("title", "notes", "category", "due_at", "updated_at"))
    return task


@transaction.atomic
def toggle_task(*, user: AbstractBaseUser, task_id: UUID) -> Task:
    """Toggle completion for an owned task.

    Args:
        user: Task owner.
        task_id: Task identifier.

    Returns:
        Updated task.

    Raises:
        Http404: If the task is not owned by the user.
    """
    task = get_object_or_404(Task, pk=task_id, user=user)
    task.completed_at = None if task.completed_at else timezone.now()
    task.save(update_fields=("completed_at", "updated_at"))
    return task


@transaction.atomic
def delete_task(*, user: AbstractBaseUser, task_id: UUID) -> None:
    """Delete an owned task.

    Args:
        user: Task owner.
        task_id: Task identifier.

    Raises:
        Http404: If the task is not owned by the user.
    """
    get_object_or_404(Task, pk=task_id, user=user).delete()


@transaction.atomic
def issue_biometric_token(*, user: AbstractBaseUser) -> str:
    """Issue a fresh device token and store only its digest.

    Any previously issued token for the user stops working. Rotation deliberately
    keeps created_at: the credential lifetime is absolute from the first opt-in,
    so BIOMETRIC_TOKEN_TTL forces a password sign-in even on a device used daily.

    Args:
        user: Account the device may unlock.

    Returns:
        Raw token, the only copy that ever exists outside the device.
    """
    raw_token = secrets.token_urlsafe(32)
    BiometricCredential.objects.update_or_create(
        user=user,
        defaults={
            "token_hash": _biometric_hash(raw_token),
            "password_hash": _password_fingerprint(user),
        },
    )
    return raw_token


@transaction.atomic
def authenticate_biometric_token(*, raw_token: str) -> AbstractBaseUser | None:
    """Resolve a device token to its issuing user.

    Args:
        raw_token: Token presented by the device.

    Returns:
        Issuing user, or None when the token is blank, unknown, expired, or issued
        against a password that has since been changed.
    """
    raw_token = raw_token.strip()
    if not raw_token:
        return None
    credential = BiometricCredential.objects.filter(
        token_hash=_biometric_hash(raw_token)
    ).first()
    if credential is None:
        return None
    if credential.created_at < timezone.now() - BIOMETRIC_TOKEN_TTL:
        credential.delete()
        return None
    if credential.password_hash != _password_fingerprint(credential.user):
        # Changing the password is what a user does when they think the account is
        # compromised, and Django's session auth hash already ends every live session.
        # Without this the stolen phone keeps unlocking, and rotation renews it.
        credential.delete()
        return None
    credential.last_used_at = timezone.now()
    credential.save(update_fields=("last_used_at",))
    return credential.user


@transaction.atomic
def revoke_biometric_token(*, user: AbstractBaseUser) -> None:
    """Delete the user's device credential if one exists.

    Args:
        user: Account whose device credential is withdrawn.
    """
    BiometricCredential.objects.filter(user=user).delete()


def set_preference(*, user: AbstractBaseUser, field: str, value: str) -> Profile:
    """Write one presentation preference as absolute state.

    update_or_create rather than a read-modify-write: the switcher carries the
    TARGET value in its href, so a double tap or a retried request lands on the
    same row with the same value instead of flipping it back.

    Args:
        user: Account stating the preference.
        field: Column to write, either theme or language.
        value: Value already validated against that field's choices.

    Returns:
        The stored preferences row, created on first use.
    """
    profile, _created = Profile.objects.update_or_create(
        user=user, defaults={field: value}
    )
    # The same reverse-cache repair store_avatar already documents, for the same
    # reason. ProfileLanguageMiddleware reads `request.user.profile` on EVERY
    # request, so by the time this runs the request's user is holding the row as it
    # was BEFORE the write; update_or_create fetched a different instance and left
    # that cache alone. Without this, the theme context processor and
    # ThemeHeaderMiddleware both re-read the stale copy and the response that
    # changed the palette is stamped X-HyperTodo-Theme with the OLD one.
    user.profile = profile
    return profile


@transaction.atomic
def store_avatar(*, user: AbstractBaseUser, data: bytes) -> Profile:
    """Replace one account's avatar with already-normalised image bytes.

    The endpoint carries no user id at all, so ownership is structural: the row
    written is the row belonging to request.user and there is no identifier an
    attacker could substitute.

    The stored name is a fresh uuid4 rather than anything derived from the user.
    It has to be unguessable, because the file is served straight from MEDIA_URL
    with no authentication, and a fresh name per upload also busts React Native's
    URI-keyed <Image> cache, which would otherwise keep showing the old photo.

    Args:
        user: Account the photo belongs to.
        data: JPEG bytes already vetted and re-encoded by AvatarForm.

    Returns:
        The stored preferences row, created on first use.
    """
    profile, _created = Profile.objects.get_or_create(user=user)
    previous = profile.avatar.name
    try:
        profile.avatar.save(f"{uuid4().hex}.jpg", ContentFile(data), save=True)
    except Exception:
        # FileField writes storage before saving the model. If that database save
        # fails, compensate immediately or the new file has no row that can find it.
        if profile.avatar.name and profile.avatar.name != previous:
            profile.avatar.storage.delete(profile.avatar.name)
        raise
    if previous:
        # Django does not delete the file a FileField stops pointing at, so every
        # re-upload would otherwise leave an orphan behind forever. on_commit, so a
        # rolled-back transaction cannot delete a file the database still names.
        transaction.on_commit(lambda: profile.avatar.storage.delete(previous))
    # Django caches a reverse one-to-one on the instance that walked it, and the
    # theme context processor reads `request.user.profile` on EVERY render, so by
    # the time this runs the request's user is already holding a stale copy.
    # `get_or_create` returned a different instance, so without this assignment the
    # response -- which is the `replace` payload for the panel -- would re-render
    # from the stale one and show the PREVIOUS photo. Assigning through the
    # descriptor updates the caches on both sides, so every later read in this
    # request sees the new row, not just the one template that prompted the fix.
    user.profile = profile
    return profile
