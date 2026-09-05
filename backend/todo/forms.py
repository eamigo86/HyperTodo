"""Forms for authentication and TODO mutations."""

from datetime import datetime

from django import forms
from django.contrib.auth.models import AbstractBaseUser
from django.utils import timezone

from .models import Category, Task


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
            raise forms.ValidationError("A category with this name already exists.")
        return name


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
            self.add_error("due_time", "A due date is required when a time is set.")
        cleaned["due_at"] = (
            timezone.make_aware(
                datetime.combine(due_date, due_time or datetime.min.time())
            )
            if due_date
            else None
        )
        return cleaned
