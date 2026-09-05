"""Django admin registrations for HyperTodo."""

from django.contrib import admin

from .models import Category, Task


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
