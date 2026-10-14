"""Forms for authentication and TODO mutations."""

import binascii
import logging
from base64 import b64decode
from datetime import date, datetime, time
from io import BytesIO
from traceback import walk_tb

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.forms.utils import ErrorList
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from PIL import Image, ImageOps

from .models import Category, Task
from .validators import REPLACEMENT, scrub_xml, xml_safe_text

logger = logging.getLogger(__name__)

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
# it is no ceiling for this app. The cap is on AREA because memory follows the area: a
# solid 4096x4096 PNG is 56KB on the wire and still raised resident memory by about
# 200MB while it was decoded and converted to RGBA. The client always posts a 512px
# JPEG (mobile/src/behaviors/owned-native.ts), a sixteenth of this.
MAX_SOURCE_PIXELS = 2048 * 2048
# The client always posts JPEG. Every other entry in Pillow's 43-format OPEN registry
# is decoder surface this app has no use for.
ALLOWED_IMAGE_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
NOT_AN_IMAGE = _("That file is not an image.")
TOO_LARGE = _("That photo is too large. Pick a smaller one.")
DUPLICATE_CATEGORY = _("A category with this name already exists.")
# Far enough out for any real plan, near enough that every instant converts to UTC and
# fits a database datetime column: 9999-12-31 raised OverflowError and answered a 500.
FIRST_DUE_YEAR = 2000
LAST_DUE_YEAR = 2100
# A refused form hands the submission back, and a bound form returns it RAW.
# dj-hyperview refuses a document over 1 MB, so a megabyte posted into any echoed field
# turned the refusal into a 500. A field is echoed up to its own max_length; the ones
# that state none (a date, a time, a choice) up to this many characters, far more than
# any of them needs. Either way one character more is kept, so a value over the limit
# comes back over it.
MAX_ECHO_CHARS = 64
# Django's copy for a bad choice quotes the submitted value, so error text is bounded.
MAX_ERROR_CHARS = 300
# The last instant of a day. fold=1 takes the later reading of 23:59:59.999999 on a
# night the clocks go back (Santiago, Cairo, Beirut, Nuuk) and the instant before the
# jump on a night they go forward (Nuuk), where fold=0 ended the day an hour early or
# on the next day. A date that never happened (Pacific/Apia, 2011-12-30) has no last
# instant and lands on the end of the day before it.
END_OF_DAY = time.max.replace(fold=1)


class XmlSafeBoundField(forms.BoundField):
    """Render a field's submission and error copy as bounded text XML 1.0 can carry.

    The validators refuse forbidden characters, but a refused form is re-rendered
    with the raw submission (and a choice error quotes it), and dj-hyperview rejects
    the whole document when a single such character reaches it, or when the document
    outgrows its size cap.
    """

    def value(self) -> object:
        """Return the value to render, bounded and with forbidden characters replaced.

        Only a submission is bounded. An initial value comes from storage, where the
        field's own validation already held it to its limit.

        A field that strips is echoed stripped, because that is the text Django
        validated: cutting the raw submission would drop valid text that sat behind
        leading whitespace. Dates and times strip when they are parsed without saying
        so, and are treated alike; cut raw, "9:30" behind 62 spaces would come back as
        "9:3", which reads as another time. The cut falls one character past the limit,
        so an over-long value is echoed still over-long and a second Save refuses it
        again instead of storing the cut text. A date or a time ends in U+FFFD there
        instead: its extra characters may be spaces, which the next parse strips, and
        no format accepts the replacement character.

        Returns:
            The bound submission or initial value, made XML-safe when it is text.
        """
        value = super().value()
        if not isinstance(value, str):
            return value
        if self.form.is_bound:
            temporal = isinstance(self.field, forms.fields.BaseTemporalField)
            if getattr(self.field, "strip", False) or temporal:
                value = value.strip()
            limit = getattr(self.field, "max_length", None) or MAX_ECHO_CHARS
            if temporal and len(value) > limit:
                value = value[:limit] + REPLACEMENT
            value = value[: limit + 1]
        return scrub_xml(value)

    @property
    def errors(self) -> ErrorList:
        """Return the error messages to render, bounded and made XML-safe.

        Returns:
            The field's errors with forbidden characters replaced.
        """
        errors = super().errors
        return self.form.error_class(
            [scrub_xml(message[:MAX_ERROR_CHARS]) for message in errors],
            renderer=self.form.renderer,
        )


class XmlSafeFormMixin:
    """Mixin for forms whose submission is echoed back into an HXML document."""

    bound_field_class = XmlSafeBoundField


class LoginForm(XmlSafeFormMixin, forms.Form):
    """Collect credentials for Django session authentication."""

    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)


class CategoryForm(XmlSafeFormMixin, forms.ModelForm):
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
            raise forms.ValidationError(DUPLICATE_CATEGORY)
        return name


class ProfileForm(XmlSafeFormMixin, forms.ModelForm):
    """Validate the account details the settings screen lets a user edit."""

    class Meta:
        model = get_user_model()
        fields = ("first_name", "last_name", "email")

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Hold every account field to the XML-safe text rule.

        auth.User is not ours to change, so the rule lives on the form. Every field
        here is rendered into a Hyperview document, and an email can carry control
        characters inside a quoted local part that Django still accepts.

        Args:
            *args: Positional arguments forwarded to ModelForm.
            **kwargs: Keyword arguments forwarded to ModelForm.
        """
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.validators.append(xml_safe_text)

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


class TaskForm(XmlSafeFormMixin, forms.ModelForm):
    """Validate task input and combine separate deadline fields."""

    due_date = forms.DateField(required=False, input_formats=("%Y-%m-%d",))
    due_time = forms.TimeField(required=False, input_formats=("%H:%M",))
    # The date and time the form showed when it was drawn, carried in hidden inputs.
    # They are plain fields on purpose: a value that is not a schedule means "an older
    # screen", never an error the person cannot see or fix. So no max_length and no
    # CharField null-character validator: the echo of a refused form is bounded and
    # scrubbed by XmlSafeBoundField instead.
    due_date_shown = forms.Field(required=False)
    due_time_shown = forms.Field(required=False)

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
        if not self.is_bound and (shown := self._shown_schedule()):
            self.initial.setdefault("due_date", shown[0])
            if shown[1] is not None:
                self.initial.setdefault("due_time", shown[1])
            self.initial.setdefault("due_date_shown", shown[0].isoformat())
            self.initial.setdefault(
                "due_time_shown", "" if shown[1] is None else shown[1].strftime("%H:%M")
            )

    def _shown_schedule(self) -> tuple[date, time | None] | None:
        """Return the date and time this form shows for the stored deadline.

        Read in the zone that is active now. An all-day deadline is stored as the last
        instant of its day, and showing that as 23:59 would put a time in a field the
        person never filled in, so its time is None.

        Returns:
            The (date, time) pair, or None when the task has no deadline.
        """
        if not (self.instance.pk and self.instance.due_at):
            return None
        local_due = timezone.localtime(self.instance.due_at)
        if self.instance.due_all_day:
            return local_due.date(), None
        return local_due.date(), local_due.time().replace(second=0, microsecond=0)

    def _posted_shown_schedule(self) -> tuple[date | None, time | None] | None:
        """Return the date and time the form showed, as the client posted them back.

        They were read in the zone that drew the form, which may not be the one that
        saves it, so they are the only reliable record of what the person saw.

        Returns:
            The (date, time) pair, (None, None) for a form that showed no deadline, or
            None when the client sent none or sent something that is not a schedule.
        """
        if not {"due_date_shown", "due_time_shown"} <= self.data.keys():
            return None
        try:
            return (
                self.fields["due_date"].to_python(
                    self.cleaned_data.get("due_date_shown")
                ),
                self.fields["due_time"].to_python(
                    self.cleaned_data.get("due_time_shown")
                ),
            )
        except forms.ValidationError:
            return None

    def clean_due_date(self) -> date | None:
        """Keep the deadline inside the years the app can store and convert.

        Returns:
            The date, or None when no deadline was given.

        Raises:
            ValidationError: If the year is outside FIRST_DUE_YEAR..LAST_DUE_YEAR.
        """
        due_date = self.cleaned_data["due_date"]
        if (
            due_date is not None
            and not FIRST_DUE_YEAR <= due_date.year <= LAST_DUE_YEAR
        ):
            raise forms.ValidationError(
                _("Choose a due date between %(first)s and %(last)s."),
                code="out_of_range",
                params={"first": FIRST_DUE_YEAR, "last": LAST_DUE_YEAR},
            )
        return due_date

    def clean(self) -> dict[str, object]:
        """Combine validated deadline components.

        A date with no time is a deadline for the whole day, stored as the last
        instant of that local day so the task is not overdue while the day is still
        going. A time of 00:00 typed on purpose is a time like any other. When an
        existing task is saved with the very schedule the form showed for it, its stored
        deadline is kept as it is.

        Returns:
            Cleaned form data with a timezone-aware due_at value and the due_all_day
            flag that says whether a time was left out.
        """
        cleaned = super().clean()
        due_date = cleaned.get("due_date")
        due_time = cleaned.get("due_time")
        # A date that failed its own field was given, just not usably: say that once,
        # under the date, and not also that it is missing.
        if due_time and not due_date and "due_date" not in self.errors:
            self.add_error("due_time", _("A due date is required when a time is set."))
        # What the form showed: as it was drawn when the client says so, else as it
        # would be drawn here and now, which is all an older screen allows.
        shown = self._posted_shown_schedule() or self._shown_schedule()
        if shown == (due_date, due_time) and not self.instance._state.adding:
            # The person posted back what the form showed. Rebuilding the instant from
            # it would move the deadline: the date was read in the zone that drew the
            # form, which need not be the zone that saves it, and a wall-clock time
            # inside a repeated hour names the wrong one of its two instants. A form
            # that showed no deadline keeps the stored one too, which another device
            # may have set since. (Not `instance.pk`: the id has a default, so a task
            # that is not saved yet already has one.)
            cleaned["due_at"] = self.instance.due_at
            cleaned["due_all_day"] = self.instance.due_all_day
            return cleaned
        cleaned["due_all_day"] = bool(due_date) and due_time is None
        cleaned["due_at"] = (
            timezone.make_aware(
                datetime.combine(due_date, END_OF_DAY if due_time is None else due_time)
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
                supported image, or holds more than MAX_SOURCE_PIXELS pixels.
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
            # pixel is decoded and the area guard below is a real refusal, not a
            # post-mortem.
            source = Image.open(BytesIO(raw))
            if source.format not in ALLOWED_IMAGE_FORMATS:
                raise forms.ValidationError(NOT_AN_IMAGE)
            if source.width * source.height > MAX_SOURCE_PIXELS:
                raise forms.ValidationError(TOO_LARGE)
            # Named, not assumed. The 422 path echoes the RAW posted base64 back
            # into an <image source="data:..."> preview, and PNG and WEBP are both
            # accepted here, so hardcoding image/jpeg there would hand the client a
            # data URI whose declared type contradicts its bytes.
            self.source_format = source.format
            # Only a JPEG decoder can scale while it decodes, by 1/2, 1/4 or 1/8, and
            # draft() asks for the largest reduction that still covers the stored
            # size. It is a no-op for every other format, so the area cap above is
            # the only bound those get.
            source.draft("RGB", (AVATAR_PIXELS, AVATAR_PIXELS))
            return _normalised_avatar(source)
        except forms.ValidationError:
            # The guards above already chose their copy; the arm below must not
            # relabel a too-large photo as "not an image".
            raise
        except Image.DecompressionBombError as error:
            # Above 2x Image.MAX_IMAGE_PIXELS, Image.open refuses the header itself
            # and the MAX_SOURCE_PIXELS guard above never runs. This error is a plain
            # Exception, not an OSError, so without its own arm it escapes
            # form.is_valid() and the endpoint answers 500 instead of a refusal.
            raise forms.ValidationError(TOO_LARGE) from error
        except MemoryError, RecursionError:
            # These say something about the server, not about the file: the decode or
            # the re-encode ran out of memory or stack. Calling that "not an image"
            # would hide it from everyone, so it surfaces as the server error it is.
            raise
        except Exception as error:
            # Pillow has no single error for a damaged file, and a list of the types
            # seen so far only ever lags behind the next one. UnidentifiedImageError
            # and a truncated stream are OSError, the PNG plugin raises SyntaxError
            # ("broken PNG file (chunk ...)") and ValueError ("APNG contains truncated
            # fcTL chunk") on purpose, a missing frame is an EOFError, and its chunk
            # and EXIF code unpacks untrusted bytes without checking them, which
            # surfaces as struct.error, IndexError, TypeError or AttributeError.
            # Each of them used to escape form.is_valid() and answer a 500 the client
            # cannot parse. This form is the trust boundary for these bytes, so
            # whatever the decode or the re-encode raises means one thing to the
            # person who picked the file.
            #
            # What differs is the log. A failure raised inside Pillow is the file's
            # fault, whatever its type, and any upload can repeat it at will, so it is
            # traced at DEBUG only. The same net also catches a bug in our own
            # re-encode, which the person would only ever see as a photo that is "not
            # an image" -- and AttributeError, TypeError and IndexError are exactly
            # what such a bug raises. That one keeps its WARNING. Where the exception
            # was raised tells the two apart and a list of types could not. Both
            # records name the failure and carry its traceback, and none of the
            # upload: the payload and the decoded bytes never reach the log.
            logger.log(
                logging.DEBUG if _raised_inside_pillow(error) else logging.WARNING,
                "The avatar upload was refused: %s while decoding it.",
                type(error).__name__,
                exc_info=True,
            )
            raise forms.ValidationError(NOT_AN_IMAGE) from error


def _raised_inside_pillow(error: BaseException) -> bool:
    """Tell whether Pillow's own code raised a failure, rather than ours.

    Args:
        error: The exception being handled, with its traceback.

    Returns:
        True when the innermost frame of the traceback belongs to the PIL package.
    """
    *_, (frame, _line) = walk_tb(error.__traceback__)
    return frame.f_globals.get("__name__", "").startswith("PIL.")


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
