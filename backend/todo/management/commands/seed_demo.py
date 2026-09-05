"""Create idempotent local demonstration data for HyperTodo."""

import os
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from todo.models import Category, Task


class Command(BaseCommand):
    """Seed local admin and demo users with isolated representative data."""

    help = "Create idempotent admin and demo HyperTodo data."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add optional admin and demo usernames.

        Args:
            parser: Django command argument parser.
        """
        parser.add_argument("--admin-username", default="admin")
        parser.add_argument("--username", default="demo")

    def handle(self, *args: Any, **options: Any) -> None:
        """Create or refresh two deterministic demonstration accounts.

        Args:
            *args: Positional command arguments.
            **options: Parsed command options.

        Raises:
            ValueError: If explicit passwords are absent outside debug mode.
        """
        admin_password = os.environ.get("HYPERTODO_ADMIN_PASSWORD")
        demo_password = os.environ.get("HYPERTODO_DEMO_PASSWORD")
        if settings.DEBUG:
            admin_password = admin_password or "admin123"
            demo_password = demo_password or "demo123"
        if not admin_password or not demo_password:
            raise ValueError(
                "Set both HyperTodo password environment variables outside debug mode."
            )
        now = timezone.now()
        admin = self._seed_account(
            username=options["admin_username"],
            password=admin_password,
            first_name="Admin",
            is_staff=True,
            is_superuser=True,
            palette={
                "Release Engineering": Category.Color.LAVENDER,
                "Operations": Category.Color.GREEN,
                "Personal": Category.Color.YELLOW,
            },
            seeds=(
                ("Review deployment checklist", "Release Engineering", 1, False),
                ("Audit template overrides", "Operations", 24, False),
                ("Rotate development secrets", "Operations", -2, False),
                ("Approve completed migration", "Release Engineering", None, True),
            ),
            now=now,
        )
        demo = self._seed_account(
            username=options["username"],
            password=demo_password,
            first_name="Alex",
            is_staff=False,
            is_superuser=False,
            palette={
                "Work": Category.Color.LAVENDER,
                "Home": Category.Color.YELLOW,
                "Learning": Category.Color.MINT,
                "Personal": Category.Color.PINK,
            },
            seeds=(
                ("Project retrospective", "Work", 2, False),
                ("Evening team meeting", "Work", 5, False),
                ("Create monthly deck", "Learning", 24, False),
                ("Shop for groceries", "Home", -1, False),
                ("Read a chapter", "Personal", None, True),
            ),
            now=now,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data is ready for {admin.username} and {demo.username}."
            )
        )

    def _seed_account(
        self,
        *,
        username: str,
        password: str,
        first_name: str,
        is_staff: bool,
        is_superuser: bool,
        palette: dict[str, str],
        seeds: tuple[tuple[str, str, int | None, bool], ...],
        now: Any,
    ) -> Any:
        user, _ = get_user_model().objects.get_or_create(username=username)
        user.set_password(password)
        user.first_name = first_name
        user.is_staff = is_staff
        user.is_superuser = is_superuser
        user.is_active = True
        user.save(
            update_fields=(
                "password",
                "first_name",
                "is_staff",
                "is_superuser",
                "is_active",
            )
        )

        categories = {}
        for name, color in palette.items():
            category, _ = Category.objects.update_or_create(
                user=user,
                name=name,
                defaults={"color": color},
            )
            categories[name] = category

        for title, category_name, due_hours, completed in seeds:
            Task.objects.update_or_create(
                user=user,
                title=title,
                defaults={
                    "category": categories[category_name],
                    "due_at": (
                        now + timedelta(hours=due_hours)
                        if due_hours is not None
                        else None
                    ),
                    "completed_at": now if completed else None,
                },
            )
        return user
