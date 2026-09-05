"""Create idempotent local demonstration data for HyperTodo."""

import os
from datetime import timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from todo.models import Category, Task


class Command(BaseCommand):
    """Seed a local user, pastel categories, and representative tasks."""

    help = "Create idempotent HyperTodo demonstration data."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add the optional demo username.

        Args:
            parser: Django command argument parser.
        """
        parser.add_argument("--username", default="demo")

    def handle(self, *args: Any, **options: Any) -> None:
        """Create or refresh deterministic demonstration records.

        Args:
            *args: Positional command arguments.
            **options: Parsed command options.

        Raises:
            ValueError: If the local password environment variable is absent.
        """
        password = os.environ.get("HYPERTODO_DEMO_PASSWORD")
        if not password:
            raise ValueError("Set HYPERTODO_DEMO_PASSWORD before seeding demo data.")
        user, _ = get_user_model().objects.get_or_create(username=options["username"])
        user.set_password(password)
        user.first_name = "Alex"
        user.save(update_fields=("password", "first_name"))

        palette = {
            "Work": Category.Color.LAVENDER,
            "Home": Category.Color.YELLOW,
            "Learning": Category.Color.MINT,
            "Personal": Category.Color.PINK,
        }
        categories = {}
        for name, color in palette.items():
            category, _ = Category.objects.update_or_create(
                user=user, name=name, defaults={"color": color}
            )
            categories[name] = category

        now = timezone.now()
        seeds = (
            ("Project retrospective", "Work", now + timedelta(hours=2), False),
            ("Evening team meeting", "Work", now + timedelta(hours=5), False),
            ("Create monthly deck", "Learning", now + timedelta(days=1), False),
            ("Shop for groceries", "Home", now - timedelta(hours=1), False),
            ("Read a chapter", "Personal", None, True),
        )
        for title, category_name, due_at, completed in seeds:
            Task.objects.update_or_create(
                user=user,
                title=title,
                defaults={
                    "category": categories[category_name],
                    "due_at": due_at,
                    "completed_at": now if completed else None,
                },
            )
        self.stdout.write(
            self.style.SUCCESS(f"Demo data is ready for {user.username}.")
        )
