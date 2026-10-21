"""Explicit, bounded Expo delivery worker; default invocation is read-only."""

import time
from argparse import ArgumentParser
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from todo.models import PushDelivery
from todo.push_delivery import dispatch_due


class Command(BaseCommand):
    """Preview or dispatch a bounded batch of durable Task alerts."""

    help = "Preview due Task alerts, or explicitly send a bounded batch via Expo"

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Expose only bounded preview and explicit send modes."""
        parser.add_argument(
            "--send", action="store_true", help="Enable outbound Expo HTTPS"
        )
        parser.add_argument(
            "--limit", type=int, default=20, help="Rows per cycle (1–100)"
        )
        parser.add_argument(
            "--watch", action="store_true", help="Repeat bounded cycles"
        )
        parser.add_argument("--cycles", type=int, default=1, help="Watch cycles (1–20)")
        parser.add_argument(
            "--interval", type=int, default=30, help="Seconds between cycles (1–60)"
        )

    def handle(self, *args: object, **options: Any) -> None:
        """Preview rows or send one to twenty bounded cycles."""
        limit = options["limit"]
        cycles = options["cycles"]
        interval = options["interval"]
        if not 1 <= limit <= 100 or not 1 <= cycles <= 20 or not 1 <= interval <= 60:
            raise CommandError(
                "limit, cycles or interval is outside its documented bound"
            )
        if options["watch"] and not options["send"]:
            raise CommandError("--watch requires explicit --send")
        if not options["send"]:
            now = timezone.now()
            due = (
                PushDelivery.objects.filter(
                    status__in=(
                        PushDelivery.Status.PENDING,
                        PushDelivery.Status.RECEIPT,
                    ),
                    next_attempt_at__lte=now,
                )
                .filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now))
                .count()
            )
            self.stdout.write(f"{due} due Task alerts (preview only)")
            return
        if not settings.PUSH_NOTIFICATIONS_ENABLED:
            raise CommandError("Task push dispatch is disabled by configuration")
        repeats = cycles if options["watch"] else 1
        for cycle in range(repeats):
            processed = dispatch_due(limit=limit)
            self.stdout.write(f"Processed {processed} Task alerts")
            if cycle + 1 < repeats:
                time.sleep(interval)
