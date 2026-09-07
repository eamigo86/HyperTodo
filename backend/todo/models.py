"""Persistence models for private TODO data."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _


class Category(models.Model):
    """A user-owned task category with a controlled display color."""

    class Color(models.TextChoices):
        """Supported category colors from the HyperTodo visual system."""

        LAVENDER = "lavender", _("Lavender")
        YELLOW = "yellow", _("Yellow")
        MINT = "mint", _("Mint")
        PINK = "pink", _("Pink")
        GREEN = "green", _("Green")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="todo_categories",
    )
    name = models.CharField(max_length=80)
    color = models.CharField(max_length=16, choices=Color, default=Color.LAVENDER)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "user", name="todo_category_user_name_ci_unique"
            )
        ]

    def __str__(self) -> str:
        """Return the category name.

        Returns:
            Human-readable category name.
        """
        return self.name


class Task(models.Model):
    """A user-owned task with an optional deadline and category."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="todo_tasks"
    )
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
    )
    title = models.CharField(max_length=160)
    notes = models.TextField(blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("completed_at", "due_at", "-created_at")
        indexes = [
            models.Index(
                fields=("user", "completed_at", "due_at"),
                name="todo_task_user_state_due",
            ),
            models.Index(fields=("user", "category"), name="todo_task_user_category"),
        ]

    def __str__(self) -> str:
        """Return the task title.

        Returns:
            Human-readable task title.
        """
        return self.title

    @property
    def is_completed(self) -> bool:
        """Report whether the task has a completion timestamp.

        Returns:
            True when the task is complete.
        """
        return self.completed_at is not None

    def clean(self) -> None:
        """Validate ownership relationships.

        Raises:
            ValidationError: If the category belongs to another user.
        """
        super().clean()
        if self.category_id and self.category.user_id != self.user_id:
            raise ValidationError(
                {"category": _("Category must belong to the same user.")}
            )


class BiometricCredential(models.Model):
    """A single device credential that unlocks one account by biometrics.

    Only the SHA-256 digest of the issued token is persisted, so a database
    dump never yields a usable credential.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="biometric_credential",
    )
    # unique=True already builds the index; db_index would only add a second one.
    token_hash = models.CharField(max_length=64, unique=True)
    # Digest of the account password at issue time. A password change is the standard
    # "I think I am compromised" response, so it has to invalidate this credential too;
    # comparing the digest covers set_password, admin resets and changepassword in one
    # place, without a signal that a bulk update would skip.
    password_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        """Return an operator-safe label that omits the credential material.

        Returns:
            Description naming only the owning user.
        """
        return f"Biometric credential for {self.user}"


class Profile(models.Model):
    """One row of per-account presentation preferences.

    Every field is blank by default and blank means "no stated preference", which
    is not decoration: the theme, the language and the avatar share ONE row, so
    writing any one of them materialises the others. A non-empty default on
    language would mean a Spanish phone that switches to dark mode silently gets
    an English app, because the stored preference outranks Accept-Language.
    """

    class Theme(models.TextChoices):
        """Palettes the server can resolve a stylesheet for."""

        LIGHT = "light", "Light"
        DARK = "dark", "Dark"

    class Language(models.TextChoices):
        """Locales the app ships a catalog for."""

        ENGLISH = "en", "English"
        SPANISH = "es", "Español"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    theme = models.CharField(max_length=8, blank=True, default="", choices=Theme)
    language = models.CharField(max_length=10, blank=True, default="", choices=Language)
    # FileField and not ImageField, and NOT for the dependency reason this comment
    # used to give: pyproject pins pillow and todo/forms.py already imports PIL.
    # ImageField would simply buy nothing here. Everything it adds over FileField is
    # a Pillow system check (fields.E210), width/height bookkeeping this model does
    # not declare, and a forms.ImageField that re-verifies an upload -- and no
    # ModelForm ever touches this column. AvatarForm decodes, vets and re-encodes
    # the base64, and todo/services.store_avatar writes those bytes here.
    avatar = models.FileField(upload_to="avatars/", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        """Return an operator-readable label naming the owning user.

        Returns:
            Description of whose preferences these are.
        """
        return f"Preferences for {self.user}"
