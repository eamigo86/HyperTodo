"""Django admin registrations for HyperTodo."""

from django.contrib import admin

from .models import BiometricCredential, Category, Profile, Task


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
