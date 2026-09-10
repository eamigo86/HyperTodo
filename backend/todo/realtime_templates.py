"""Negotiated presentation metadata, never authentication or acknowledgement."""

import json
import re
from urllib.parse import urlencode

from django.http import HttpRequest

from .realtime_changes import capture_entities, negotiated

_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,80}", re.ASCII)
_SCREENS = {
    "tasks": ("task-list", "tasks categories ui"),
    "categories": ("category-list", "tasks categories ui"),
    "dashboard": ("dashboard-screen", "tasks categories ui"),
    "task_form": ("task-form-screen", "tasks categories ui"),
    "category_form": ("category-form-screen", "categories ui"),
    "settings": ("settings-screen", "ui"),
    "about": ("about-screen", "ui"),
    "login": ("login-screen", "ui"),
    "error": ("error-screen", "ui"),
    "session_expired": ("session-expired-screen", "ui"),
    "source_probe": ("filesystem-probe", "ui"),
}


def realtime_context(
    request: HttpRequest, template_name: str, context: dict[str, object]
) -> dict[str, object]:
    """Provide guard-owned capability and bounded, escaped correlation metadata.

    Args:
        request: Request that has already passed the modern session guard.
        template_name: Selected source; includes do not create new boundaries.
        context: Existing view context, used for already-validated task filters.

    Returns:
        Presentation-only values. An absent/invalid request ID is inert and does
        not change HTTP status or manufacture a client operation acknowledgement.
    """
    enabled = getattr(request, "hv_realtime_v1", False) is True
    values: dict[str, object] = {"realtime_enabled": enabled}
    if not enabled:
        return values
    request_id = request.headers.get("X-HyperTodo-Request-ID", "")
    name = template_name.removeprefix("screens/").removesuffix(".xml")
    target, resources = _SCREENS.get(name, ("", "ui"))
    refresh_href = request.get_full_path()
    if name == "tasks":
        filters = [("status", str(context["status_filter"]))]
        category = context.get("selected_category")
        if category is not None:
            filters.append(("category", str(category.pk)))
        filters.append(("fragment", "list"))
        refresh_href = "/hv/tasks/?" + urlencode(filters)
    elif name == "categories":
        refresh_href = "/hv/categories/?fragment=list"
    values.update(
        realtime_request_id=request_id
        if _REQUEST_ID.fullmatch(request_id)
        else "untracked",
        realtime_fragment=template_name if request.hv_fragment else "",
        realtime_target=target,
        realtime_resources=resources,
        realtime_mode="list" if name in {"tasks", "categories"} else "notice",
        realtime_refresh_href=refresh_href,
    )
    if negotiated(request) and request.user.is_authenticated:
        values["realtime_changes"] = True
        if name in {"dashboard", "about"}:
            values["realtime_mode"] = "readonly"
        form_name = {
            "fragments/task_form_panel": "task_form",
            "fragments/category_form_panel": "category_form",
            "fragments/settings_form_panel": "settings",
        }.get(name, name)
        if form_name in {"task_form", "category_form", "settings"}:
            values["realtime_mode"] = "form"
            using = request.user._state.db
            rows = [("ui", request.user.pk)]
            entity = context.get("task" if form_name == "task_form" else "category")
            if entity is not None:
                rows.append(
                    ("tasks" if form_name == "task_form" else "categories", entity.pk)
                )
            metadata = capture_entities(using, rows)
            values["realtime_entities"] = json.dumps(
                metadata.payload, separators=(",", ":")
            )
            if form_name == "task_form":
                # Form values remain actual authorized selector values. Tokens
                # identify the CURRENT choice's change dependency, never access.
                for option in context["form"].fields["category"].queryset:
                    option_metadata = capture_entities(
                        using, [("categories", option.pk)]
                    ).payload
                    option.realtime_entity_key = option_metadata["items"][0]["key"]
                    option.realtime_entity_epoch = option_metadata["epoch"]
    return values
