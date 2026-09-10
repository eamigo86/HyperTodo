"""Negotiated presentation metadata, never authentication or acknowledgement."""

import re
from urllib.parse import urlencode

from django.http import HttpRequest

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
    return values
