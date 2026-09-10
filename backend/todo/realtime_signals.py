"""Observe normal ORM mutations without altering service or Admin behavior."""

from dataclasses import dataclass

from dj_hyperview.signals import TemplateInvalidation, template_invalidated
from django.apps import apps
from django.db.models import Model
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save

from .models import Category, Task
from .realtime_config import RealtimeConfig, get_realtime_config
from .realtime_notifications import notify_after_commit, notify_template_commit


@dataclass(frozen=True, slots=True)
class _Snapshot:
    config: RealtimeConfig
    owners: frozenset[object]


def _owners(sender: type[Model], instance: Model, using: str) -> frozenset[object]:
    owners = set(
        sender._base_manager.using(using)
        .filter(pk=instance.pk)
        .values_list("user_id", flat=True)
    )
    if sender is Category:
        # Collector's SET_NULL updates do not emit Task.post_save. Also preserve
        # prior Task owners if an Admin transferred the Category independently.
        owners.update(
            Task._base_manager.using(using)
            .filter(category_id=instance.pk)
            .values_list("user_id", flat=True)
            .distinct()
        )
    return frozenset(owners)


def _before(
    sender: type[Model],
    instance: Model,
    using: str,
    raw: bool = False,
    **kwargs: object,
) -> None:
    instance.__dict__.pop("_realtime_snapshot", None)
    if raw:
        return
    config = get_realtime_config()
    if config is not None:
        instance.__dict__["_realtime_snapshot"] = _Snapshot(
            config, _owners(sender, instance, using)
        )


def _saved(sender: type[Model], instance: Model, using: str, **kwargs: object) -> None:
    snapshot = instance.__dict__.pop("_realtime_snapshot", None)
    if snapshot is None:
        return
    # Reading persisted values handles update_fields, deferred fields, generator
    # normalization in Django.save and in-memory owner edits excluded from SQL.
    owners = snapshot.owners | _owners(sender, instance, using)
    notify_after_commit(
        using=using,
        owners=owners,
        resources=("categories",) if sender is Category else ("tasks",),
        config=snapshot.config,
    )


def _deleted(
    sender: type[Model], instance: Model, using: str, **kwargs: object
) -> None:
    snapshot = instance.__dict__.pop("_realtime_snapshot", None)
    if snapshot is not None:
        notify_after_commit(
            using=using,
            owners=snapshot.owners,
            resources=("tasks", "categories") if sender is Category else ("tasks",),
            config=snapshot.config,
        )


def _template_changed(sender: type[Model], event: object, **kwargs: object) -> None:
    if isinstance(event, TemplateInvalidation):
        notify_template_commit(using=event.using)


def connect_realtime_signals() -> None:
    """Register idempotent ORM receivers without Redis, SQL or cache work."""
    get_realtime_config()
    for model in (Task, Category):
        for signal, receiver in (
            (pre_save, _before),
            (pre_delete, _before),
            (post_save, _saved),
            (post_delete, _deleted),
        ):
            signal.connect(
                receiver,
                sender=model,
                weak=False,
                dispatch_uid=f"todo.realtime.{model._meta.label_lower}.{receiver.__name__}.{id(signal)}",
            )
    if apps.is_installed("dj_hyperview.contrib.database"):
        template_invalidated.connect(
            _template_changed,
            sender=apps.get_model("dj_hyperview_database", "HyperviewTemplate"),
            weak=False,
            dispatch_uid="todo.realtime.template",
        )
