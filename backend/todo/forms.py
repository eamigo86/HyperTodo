"""Forms for authentication and TODO mutations."""

import binascii
from base64 import b64decode
from datetime import datetime
from io import BytesIO

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from PIL import Image, ImageOps

from .models import Category, Task

# The whole payload rides in a form FIELD, and django/http/multipartparser.py:243-250
# counts non-file field bytes against DATA_UPLOAD_MAX_MEMORY_SIZE (2.5MB), raising a
# SuspiciousOperation that Django renders as plain HTML -- which the Hyperview client
# cannot parse at all. So the ceiling has to sit well under that, and be OURS, so the
# refusal comes back as a fragment the panel can actually show. A 512px q0.8 JPEG is
# 40-90KB, so this is roughly an order of magnitude of headroom.
MAX_AVATAR_BYTES = 600_000
# base64 is exactly 4 characters per 3 bytes, so the encoded length is checked instead
# of the decoded one: it is the cheaper test and it is the same test.
MAX_AVATAR_B64 = 4 * ((MAX_AVATAR_BYTES + 2) // 3)
AVATAR_PIXELS = 256
# Pillow's own bomb check only WARNS between 1x and 2x MAX_IMAGE_PIXELS (89478485), so
# a 5000x5000 PNG -- a few KB on the wire -- passes it and allocates ~100MB on decode.
MAX_SOURCE_EDGE = 4096
# The client always posts JPEG. Every other entry in Pillow's 43-format OPEN registry
# is decoder surface this app has no use for.
ALLOWED_IMAGE_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
NOT_AN_IMAGE = _("That file is not an image.")
TOO_LARGE = _("That photo is too large. Pick a smaller one.")


class LoginForm(forms.Form):
    """Collect credentials for Django session authentication."""

    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)


class CategoryForm(forms.ModelForm):
    """Validate a category within one user's namespace."""

    class Meta:
        model = Category
        fields = ("name", "color")

    def __init__(self, *args: object, user: AbstractBaseUser, **kwargs: object) -> None:
        """Initialize the form for a specific owner.

        Args:
            *args: Positional arguments forwarded to ModelForm.
            user: User who owns the category.
            **kwargs: Keyword arguments forwarded to ModelForm.
        """
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_name(self) -> str:
        """Normalize and validate a user-scoped category name.

        Returns:
            Trimmed category name.

        Raises:
            ValidationError: If the user already owns the name.
        """
        name = self.cleaned_data["name"].strip()
        matches = Category.objects.filter(user=self.user, name__iexact=name)
        if self.instance.pk:
            matches = matches.exclude(pk=self.instance.pk)
        if matches.exists():
            raise forms.ValidationError(_("A category with this name already exists."))
        return name


class ProfileForm(forms.ModelForm):
    """Validate the account details the settings screen lets a user edit."""

    class Meta:
        model = get_user_model()
        fields = ("first_name", "last_name", "email")

    def clean_email(self) -> str:
        """Normalize the address and keep it unique across accounts.

        Email is optional because AbstractUser.email is blank=True, but the
        moment one exists it is the de-facto recovery key, so two accounts must
        not share it.

        Returns:
            Normalized address, or an empty string when none was given.

        Raises:
            ValidationError: If another account already holds the address.
        """
        model = get_user_model()
        email = model.objects.normalize_email(self.cleaned_data["email"].strip())
        if not email:
            return ""
        # ponytail: form-level only. auth.User has no unique constraint, so two
        # concurrent saves can still land the same address; adding the constraint
        # needs a swapped user model. Do that if collisions ever show up.
        clash = model.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if clash.exists():
            # Accepted risk, decided deliberately: this tells an authenticated
            # caller whether an address has an account. Softening the copy would
            # be theatre, because 422-vs-200 leaks the same bit, and the real
            # mitigation (throttling the settings POST) buys nothing here - the
            # address is optional, drives no recovery flow and unlocks nothing.
            # Revisit if email ever becomes a login or password-reset key.
            raise forms.ValidationError(_("This email is already in use."))
        return email


class TaskForm(forms.ModelForm):
    """Validate task input and combine separate deadline fields."""

    due_date = forms.DateField(required=False, input_formats=("%Y-%m-%d",))
    due_time = forms.TimeField(required=False, input_formats=("%H:%M",))

    class Meta:
        model = Task
        fields = ("title", "notes", "category")

    def __init__(self, *args: object, user: AbstractBaseUser, **kwargs: object) -> None:
        """Initialize fields for one user and optional task instance.

        Args:
            *args: Positional arguments forwarded to ModelForm.
            user: User who owns the task and selectable categories.
            **kwargs: Keyword arguments forwarded to ModelForm.
        """
        self.user = user
        super().__init__(*args, **kwargs)
        # Task.clean() compares category.user_id against the instance's user_id, so an
        # unsaved instance must know its owner or every create with a category fails.
        self.instance.user = user
        self.fields["category"].queryset = Category.objects.filter(user=user)
        if not self.is_bound and self.instance.pk and self.instance.due_at:
            local_due = timezone.localtime(self.instance.due_at)
            self.initial.setdefault("due_date", local_due.date())
            self.initial.setdefault(
                "due_time", local_due.time().replace(second=0, microsecond=0)
            )

    def clean(self) -> dict[str, object]:
        """Combine validated deadline components.

        Returns:
            Cleaned form data with a timezone-aware due_at value.
        """
        cleaned = super().clean()
        due_date = cleaned.get("due_date")
        due_time = cleaned.get("due_time")
        if due_time and not due_date:
            self.add_error("due_time", _("A due date is required when a time is set."))
        cleaned["due_at"] = (
            timezone.make_aware(
                datetime.combine(due_date, due_time or datetime.min.time())
            )
            if due_date
            else None
        )
        return cleaned


class AvatarForm(forms.Form):
    """Decode, vet, and re-encode the base64 image a device pastes into a text field.

    No file part ever crosses a Hyperview form: the client registry serialises a
    field's value ATTRIBUTE as a string (services/index.ts:292-300), so base64 in
    a hidden <text-field hide="true"> is the only transport there is. That makes
    this form the entire trust boundary for attacker-supplied bytes, and the reason
    the server never stores what it was sent: it stores what it re-encoded.
    """

    avatar_data = forms.CharField()
    # The format the posted bytes actually announced, set by clean_avatar_data.
    source_format = ""

    def clean_avatar_data(self) -> bytes:
        """Turn a posted base64 string into the exact JPEG that will be stored.

        Returns:
            A 256x256 RGB JPEG carrying no metadata of any kind.

        Raises:
            ValidationError: If the payload is oversized, not base64, not a
                supported image, or larger than MAX_SOURCE_EDGE on either side.
        """
        value = self.cleaned_data["avatar_data"]
        if len(value) > MAX_AVATAR_B64:
            raise forms.ValidationError(TOO_LARGE)
        try:
            raw = b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise forms.ValidationError(NOT_AN_IMAGE) from error
        try:
            # Image.open reads the header only, so `size` is known before a single
            # pixel is decoded and the edge guard below is a real refusal, not a
            # post-mortem. UnidentifiedImageError subclasses OSError, and so does a
            # truncated file blowing up later in the pipeline.
            source = Image.open(BytesIO(raw))
            if source.format not in ALLOWED_IMAGE_FORMATS:
                raise forms.ValidationError(NOT_AN_IMAGE)
            if max(source.size) > MAX_SOURCE_EDGE:
                raise forms.ValidationError(TOO_LARGE)
            # Named, not assumed. The 422 path echoes the RAW posted base64 back
            # into an <image source="data:..."> preview, and PNG and WEBP are both
            # accepted here, so hardcoding image/jpeg there would hand the client a
            # data URI whose declared type contradicts its bytes.
            self.source_format = source.format
            return _normalised_avatar(source)
        except Image.DecompressionBombError as error:
            # Above 2x Image.MAX_IMAGE_PIXELS, Image.open refuses the header itself
            # and the MAX_SOURCE_EDGE guard above never runs. This error is a plain
            # Exception, not an OSError, so without its own arm it escapes
            # form.is_valid() and the endpoint answers 500 instead of a refusal.
            raise forms.ValidationError(TOO_LARGE) from error
        except OSError as error:
            raise forms.ValidationError(NOT_AN_IMAGE) from error


def _normalised_avatar(source: Image.Image) -> bytes:
    """Re-encode one decoded image as the single shape this app stores.

    Args:
        source: Image opened from the posted bytes.

    Returns:
        JPEG bytes, square, fixed size, opaque, and metadata-free.

    Note:
        Order matters three times. exif_transpose runs FIRST, because it is the
        only thing that reads the Orientation tag and every iPhone portrait lands
        sideways without it. The white canvas is what flattens alpha: a plain
        convert("RGB") composites transparency onto BLACK, which would put a black
        square inside a white avatar disc. And save is called with NO exif=
        kwarg, which -- measured on Pillow 12.3.0 -- is what actually drops the GPS
        coordinates and camera make that exif_transpose leaves untouched.
    """
    fitted = ImageOps.fit(
        ImageOps.exif_transpose(source).convert("RGBA"),
        (AVATAR_PIXELS, AVATAR_PIXELS),
    )
    canvas = Image.new("RGB", fitted.size, (255, 255, 255))
    canvas.paste(fitted, mask=fitted)
    buffer = BytesIO()
    canvas.save(buffer, "JPEG", quality=85, optimize=True)
    return buffer.getvalue()
