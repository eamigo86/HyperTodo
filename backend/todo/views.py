"""Server-driven Hyperview endpoints for the TODO application."""

from collections.abc import Callable
from functools import wraps
from uuid import UUID

from dj_hyperview import HyperviewResponse, HyperviewTemplateResponse
from django.contrib.auth import authenticate, login, logout
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404

from .forms import CategoryForm, LoginForm, TaskForm
from .models import Category, Task
from .selectors import VALID_STATUSES, dashboard_counts, tasks_for_user
from .services import (
    create_category,
    create_task,
    delete_category,
    delete_task,
    toggle_task,
    update_category,
    update_task,
)

View = Callable[..., HttpResponse]


def _error_response(message: str, status: int) -> HyperviewResponse:
    escaped = (
        message.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return HyperviewResponse(
        f'<doc xmlns="https://hyperview.org/hyperview"><screen id="error-screen">'
        f'<body><view style="error-card"><text>{escaped}</text>'
        '<view href="/hv/" action="replace"><text>Return home</text></view>'
        "</view></body></screen></doc>",
        status=status,
    )


def hxml_endpoint(view: View) -> View:
    """Convert authentication, method, and lookup failures to HXML.

    Args:
        view: Endpoint implementation.

    Returns:
        Wrapped endpoint that never redirects unauthenticated users.
    """

    @wraps(view)
    def wrapped(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        try:
            return view(request, *args, **kwargs)
        except Http404:
            return _error_response("The requested item was not found.", 404)

    return wrapped


def _require_user(request: HttpRequest) -> HttpResponse | None:
    if request.user.is_authenticated:
        return None
    return HyperviewTemplateResponse(request, "screens/session_expired.xml", status=401)


def _method(request: HttpRequest, *allowed: str) -> HttpResponse | None:
    if request.method in allowed:
        return None
    response = _error_response(
        "This action does not support the requested method.", 405
    )
    response.headers["Allow"] = ", ".join(allowed)
    return response


def _dashboard_response(
    request: HttpRequest, *, status: int = 200
) -> HyperviewTemplateResponse:
    context = {
        "counts": dashboard_counts(request.user),
        "tasks": tasks_for_user(request.user, status="today")[:6],
        "categories": Category.objects.filter(user=request.user),
    }
    return HyperviewTemplateResponse(
        request, "screens/dashboard.xml", context, status=status
    )


@hxml_endpoint
def root(request: HttpRequest) -> HttpResponse:
    """Serve the login or dashboard screen without redirects.

    Args:
        request: Incoming Hyperview request.

    Returns:
        Stack navigator targeting login or dashboard for the current session.
    """
    if request.user.is_authenticated:
        route_id = "dashboard-route"
        route_href = "/hv/dashboard/"
    else:
        route_id = "login-route"
        route_href = "/hv/login/"
    return HyperviewTemplateResponse(
        request,
        "screens/root.xml",
        {"route_id": route_id, "route_href": route_href},
    )


@hxml_endpoint
def login_view(request: HttpRequest) -> HttpResponse:
    """Create a Django session from submitted credentials.

    Args:
        request: Incoming login request.

    Returns:
        Login document, form fragment, transition fragment, or method error response.
    """
    if invalid := _method(request, "GET", "POST"):
        return invalid
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = authenticate(
            request,
            username=form.cleaned_data["username"],
            password=form.cleaned_data["password"],
        )
        if user is not None:
            login(request, user)
            return HyperviewTemplateResponse(
                request, "fragments/login_transition.xml"
            )
        form.add_error(None, "The username or password is incorrect.")
        return HyperviewTemplateResponse(
            request, "fragments/login_panel.xml", {"form": form}, status=422
        )
    return HyperviewTemplateResponse(
        request, "screens/login.xml", {"form": form}
    )


@hxml_endpoint
def logout_view(request: HttpRequest) -> HttpResponse:
    """End a Django session and reload the guest root document.

    Args:
        request: Incoming logout request.

    Returns:
        Logout transition fragment or method error response.
    """
    if invalid := _method(request, "POST"):
        return invalid
    logout(request)
    return HyperviewTemplateResponse(request, "fragments/logout_transition.xml")


@hxml_endpoint
def dashboard(request: HttpRequest) -> HttpResponse:
    """Render private dashboard counters and today's tasks.

    Args:
        request: Incoming screen request.

    Returns:
        Dashboard or session-expired HXML response.
    """
    if denied := _require_user(request):
        return denied
    if invalid := _method(request, "GET"):
        return invalid
    return _dashboard_response(request)


@hxml_endpoint
def task_list(request: HttpRequest) -> HttpResponse:
    """Render a filtered private task list.

    Args:
        request: Incoming screen request with optional filters.

    Returns:
        Filtered task screen or an HXML error response.
    """
    if denied := _require_user(request):
        return denied
    if invalid := _method(request, "GET"):
        return invalid
    status_filter = request.GET.get("status", "all")
    if status_filter not in VALID_STATUSES:
        return _error_response("Unknown task filter.", 400)
    category = None
    category_id = request.GET.get("category")
    if category_id:
        category = get_object_or_404(Category, pk=category_id, user=request.user)
    context = {
        "tasks": tasks_for_user(request.user, status=status_filter, category=category),
        "categories": Category.objects.filter(user=request.user),
        "status_filter": status_filter,
        "selected_category": category,
    }
    return HyperviewTemplateResponse(request, "screens/tasks.xml", context)


def _task_form_response(
    request: HttpRequest, form: TaskForm, *, task: Task | None = None, status: int = 200
) -> HyperviewTemplateResponse:
    template_name = (
        "fragments/task_form_panel.xml"
        if request.method == "POST"
        else "screens/task_form.xml"
    )
    return HyperviewTemplateResponse(
        request, template_name, {"form": form, "task": task}, status=status
    )


@hxml_endpoint
def task_new(request: HttpRequest) -> HttpResponse:
    """Create a task owned by the authenticated user.

    Args:
        request: Incoming task form request.

    Returns:
        Task form document, form fragment, or list transition HXML.
    """
    if denied := _require_user(request):
        return denied
    if invalid := _method(request, "GET", "POST"):
        return invalid
    form = TaskForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        create_task(
            user=request.user,
            title=form.cleaned_data["title"],
            notes=form.cleaned_data["notes"],
            category=form.cleaned_data["category"],
            due_at=form.cleaned_data["due_at"],
        )
        return HyperviewTemplateResponse(
            request, "fragments/task_transition.xml", status=201
        )
    return _task_form_response(
        request, form, status=422 if request.method == "POST" else 200
    )


@hxml_endpoint
def task_edit(request: HttpRequest, task_id: UUID) -> HttpResponse:
    """Edit a task owned by the authenticated user.

    Args:
        request: Incoming task form request.
        task_id: Task identifier from the route.

    Returns:
        Task form document, form fragment, or list transition HXML.
    """
    if denied := _require_user(request):
        return denied
    if invalid := _method(request, "GET", "POST"):
        return invalid
    task = get_object_or_404(Task, pk=task_id, user=request.user)
    form = TaskForm(request.POST or None, instance=task, user=request.user)
    if request.method == "POST" and form.is_valid():
        update_task(
            user=request.user,
            task_id=task.pk,
            title=form.cleaned_data["title"],
            notes=form.cleaned_data["notes"],
            category=form.cleaned_data["category"],
            due_at=form.cleaned_data["due_at"],
        )
        return HyperviewTemplateResponse(
            request, "fragments/task_transition.xml"
        )
    return _task_form_response(
        request, form, task=task, status=422 if request.method == "POST" else 200
    )


@hxml_endpoint
def task_toggle(request: HttpRequest, task_id: UUID) -> HttpResponse:
    """Toggle an owned task and return the private task list.

    Args:
        request: Incoming mutation request.
        task_id: Task identifier from the route.

    Returns:
        Task-list reload transition fragment.
    """
    if denied := _require_user(request):
        return denied
    if invalid := _method(request, "POST"):
        return invalid
    toggle_task(user=request.user, task_id=task_id)
    return HyperviewTemplateResponse(
        request, "fragments/task_list_transition.xml"
    )


@hxml_endpoint
def task_delete(request: HttpRequest, task_id: UUID) -> HttpResponse:
    """Delete an owned task and return the private task list.

    Args:
        request: Incoming mutation request.
        task_id: Task identifier from the route.

    Returns:
        Task-list reload transition fragment.
    """
    if denied := _require_user(request):
        return denied
    if invalid := _method(request, "POST"):
        return invalid
    delete_task(user=request.user, task_id=task_id)
    return HyperviewTemplateResponse(
        request, "fragments/task_list_transition.xml"
    )


@hxml_endpoint
def category_list(request: HttpRequest) -> HttpResponse:
    """Render categories owned by the authenticated user.

    Args:
        request: Incoming category screen request.

    Returns:
        Category list HXML.
    """
    if denied := _require_user(request):
        return denied
    if invalid := _method(request, "GET"):
        return invalid
    return HyperviewTemplateResponse(
        request,
        "screens/categories.xml",
        {"categories": Category.objects.filter(user=request.user)},
    )


def _category_form_response(
    request: HttpRequest,
    form: CategoryForm,
    *,
    category: Category | None = None,
    status: int = 200,
) -> HyperviewTemplateResponse:
    template_name = (
        "fragments/category_form_panel.xml"
        if request.method == "POST"
        else "screens/category_form.xml"
    )
    return HyperviewTemplateResponse(
        request,
        template_name,
        {"form": form, "category": category},
        status=status,
    )


@hxml_endpoint
def category_new(request: HttpRequest) -> HttpResponse:
    """Create a category owned by the authenticated user.

    Args:
        request: Incoming category form request.

    Returns:
        Category form document, form fragment, or list transition HXML.
    """
    if denied := _require_user(request):
        return denied
    if invalid := _method(request, "GET", "POST"):
        return invalid
    form = CategoryForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        create_category(
            user=request.user,
            name=form.cleaned_data["name"],
            color=form.cleaned_data["color"],
        )
        return HyperviewTemplateResponse(
            request,
            "fragments/category_transition.xml",
            status=201,
        )
    return _category_form_response(
        request, form, status=422 if request.method == "POST" else 200
    )


@hxml_endpoint
def category_edit(request: HttpRequest, category_id: UUID) -> HttpResponse:
    """Edit a category owned by the authenticated user.

    Args:
        request: Incoming category form request.
        category_id: Category identifier from the route.

    Returns:
        Category form document, form fragment, or list transition HXML.
    """
    if denied := _require_user(request):
        return denied
    if invalid := _method(request, "GET", "POST"):
        return invalid
    category = get_object_or_404(Category, pk=category_id, user=request.user)
    form = CategoryForm(request.POST or None, instance=category, user=request.user)
    if request.method == "POST" and form.is_valid():
        update_category(
            user=request.user,
            category_id=category.pk,
            name=form.cleaned_data["name"],
            color=form.cleaned_data["color"],
        )
        return HyperviewTemplateResponse(
            request,
            "fragments/category_transition.xml",
        )
    return _category_form_response(
        request,
        form,
        category=category,
        status=422 if request.method == "POST" else 200,
    )


@hxml_endpoint
def category_delete(request: HttpRequest, category_id: UUID) -> HttpResponse:
    """Delete an owned category and return the private category list.

    Args:
        request: Incoming mutation request.
        category_id: Category identifier from the route.

    Returns:
        Category-list reload transition fragment.
    """
    if denied := _require_user(request):
        return denied
    if invalid := _method(request, "POST"):
        return invalid
    delete_category(user=request.user, category_id=category_id)
    return HyperviewTemplateResponse(
        request,
        "fragments/category_list_transition.xml",
    )


def csrf_failure(request: HttpRequest, reason: str = "") -> HyperviewResponse:
    """Return CSRF rejection using the Hyperview media contract.

    Args:
        request: Rejected request.
        reason: Internal Django rejection reason, deliberately not exposed.

    Returns:
        Generic HXML CSRF error.
    """
    return _error_response("Security validation failed. Reload and try again.", 403)


@hxml_endpoint
def source_probe(request: HttpRequest) -> HttpResponse:
    """Render the source-precedence acceptance template.

    Args:
        request: Incoming acceptance request.

    Returns:
        Template resolved from database or filesystem sources.
    """
    if invalid := _method(request, "GET"):
        return invalid
    return HyperviewTemplateResponse(request, "screens/source_probe.xml")
