"""Persist Task push intent independently of optional SSE configuration."""

from django.conf import settings
from django.db.models.signals import post_save, pre_save

from .models import PushDelivery, PushDevice, Task

_FIELDS = (
    "user_id",
    "category_id",
    "title",
    "notes",
    "due_at",
    "due_all_day",
    "completed_at",
)


def _before(
    sender: type[Task],
    instance: Task,
    using: str,
    raw: bool = False,
    **kwargs: object,
) -> None:
    instance.__dict__.pop("_push_before", None)
    if raw or not settings.PUSH_NOTIFICATIONS_ENABLED or instance._state.adding:
        return
    instance.__dict__["_push_before"] = (
        Task.objects.using(using).filter(pk=instance.pk).values_list(*_FIELDS).first()
    )


def _after(
    sender: type[Task],
    instance: Task,
    created: bool,
    using: str,
    raw: bool = False,
    **kwargs: object,
) -> None:
    before = instance.__dict__.pop("_push_before", None)
    if raw or created or before is None or not settings.PUSH_NOTIFICATIONS_ENABLED:
        return
    after = (
        Task.objects.using(using).filter(pk=instance.pk).values_list(*_FIELDS).first()
    )
    if after is None or before == after:
        return
    # The new current owner is the only recipient. Dispatch repeats this check.
    devices = (
        PushDevice.objects.using(using)
        .filter(user_id=after[0])
        .values_list("pk", "registration_version")
    )
    PushDelivery.objects.using(using).bulk_create(
        [
            PushDelivery(
                task_id=instance.pk,
                owner_id=after[0],
                device_id=device_id,
                registration_version=version,
            )
            for device_id, version in devices
        ]
    )


def connect_push_signals() -> None:
    """Attach idempotent Task observers without database or network startup work."""
    pre_save.connect(_before, sender=Task, weak=False, dispatch_uid="todo.push.before")
    post_save.connect(_after, sender=Task, weak=False, dispatch_uid="todo.push.after")
