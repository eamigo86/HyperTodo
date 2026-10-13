"""Django admin registrations for HyperTodo."""

from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.views.decorators.debug import sensitive_variables

from .models import BiometricCredential, Category, Profile, Task
from .throttle import claim_password_attempt, release_password_attempts


class ThrottledAdminAuthenticationForm(AdminAuthenticationForm):
    """Admin login form that spends the sign-in budget before checking a password.

    The Admin is a second door to the same accounts. It draws on the same address and
    account budgets as the app's own login, otherwise it is an unthrottled password
    oracle standing next to a throttled one.
    """

    @sensitive_variables()
    def clean(self) -> dict[str, object]:
        """Refuse an over-budget attempt before authenticate runs.

        Returns:
            The cleaned data, with the authenticated user cached on the form.

        Raises:
            ValidationError: If the attempt is over budget or the credentials fail.
        """
        username = self.cleaned_data.get("username")
        if (
            username is not None
            and self.cleaned_data.get("password")
            and not claim_password_attempt(self.request, username)
        ):
            raise ValidationError(
                _("Too many sign-in attempts. Try again later."), code="throttled"
            )
        cleaned = super().clean()
        if self.user_cache is not None:
            release_password_attempts(self.request, username)
        return cleaned


admin.site.login_form = ThrottledAdminAuthenticationForm


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Admin configuration for user-owned categories."""

    list_display = ("name", "user", "color", "updated_at")
    list_filter = ("color",)
    search_fields = ("name", "user__username")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    """Admin configuration for user-owned tasks."""

    list_display = ("title", "user", "category", "due_at", "completed_at")
    list_filter = ("completed_at", "category")
    search_fields = ("title", "notes", "user__username")


@admin.register(BiometricCredential)
class BiometricCredentialAdmin(admin.ModelAdmin):
    """Read-only enrolment list so an operator can revoke a lost or stolen device.

    Without this the only revocation paths are on the enrolled phone itself, which
    is exactly the device the user no longer has.
    """

    list_display = ("user", "created_at", "last_used_at")
    search_fields = ("user__username",)
    readonly_fields = ("user", "created_at", "last_used_at")
    # Never surface the credential material, and never let the admin mint one.
    exclude = ("token_hash", "password_hash")

    def has_add_permission(self, request: object) -> bool:
        """Report that credentials are issued by the device flow, never by hand.

        Args:
            request: Incoming admin request.

        Returns:
            Always False.
        """
        return False


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    """Operator view of the stored presentation preferences.

    Support needs a way to read and clear a preference that has a user stuck --
    the only other channel is the phone the user is complaining about.
    """

    list_display = ("user", "theme", "language", "updated_at")
    list_filter = ("theme", "language")
    search_fields = ("user__username",)
