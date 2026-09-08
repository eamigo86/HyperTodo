"""Server-driven Hyperview endpoints for the TODO application."""

import re
from collections.abc import Callable
from functools import wraps
from hashlib import sha256
from importlib.metadata import version
from uuid import UUID

from dj_hyperview import (
    HYPERVIEW_FRAGMENT_MEDIA_TYPE,
    HYPERVIEW_SCHEMA_VERSION,
    HyperviewFragmentTemplateResponse,
    HyperviewTemplateResponse,
)
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import AbstractUser
from django.core.cache import cache
from django.core.paginator import EmptyPage, Page, PageNotAnInteger, Paginator
from django.db import transaction
from django.db.models import Count, QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.views.decorators.vary import vary_on_headers

from .context_processors import THEME_COOKIE, THEME_COOKIE_MAX_AGE
from .forms import AvatarForm, CategoryForm, LoginForm, ProfileForm, TaskForm
from .models import Category, Profile, Task
from .selectors import (
    VALID_STATUSES,
    dashboard_summary,
    has_biometric_credential,
    tasks_for_user,
)
from .services import (
    authenticate_biometric_token,
    create_category,
    create_task,
    delete_category,
    delete_task,
    issue_biometric_token,
    revoke_biometric_token,
    set_preference,
    store_avatar,
    toggle_task,
    update_category,
    update_profile,
    update_task,
)

APP_VERSION_HEADER = "X-App-Version"
# The header is attacker-controlled text rendered into the settings document, so it
# is validated at the trust boundary rather than merely escaped on the way out.
APP_VERSION_PATTERN = re.compile(r"[0-9A-Za-z.+-]{1,32}")
# The first client release that ships the generalised swipe-row component.
MIN_SWIPE_ACTIONS_VERSION = (1, 1, 0)
# The first client release that registers the `pick-avatar` behavior.
MIN_AVATAR_UPLOAD_VERSION = (1, 2, 0)
BIOMETRIC_ATTEMPT_LIMIT = 10
BIOMETRIC_ATTEMPT_WINDOW = 300

View = Callable[..., HttpResponse]
PAGE_SIZE = 20


def _paginate(queryset: QuerySet, raw_page: str) -> Page:
    """Return one strictly validated page of results.

    Args:
        queryset: Ordered records to paginate.
        raw_page: Page value supplied by the client.

    Returns:
        Requested page containing at most PAGE_SIZE records.

    Raises:
        EmptyPage: If the requested page has no results.
        PageNotAnInteger: If the page value is not an integer.
    """
    return Paginator(queryset, PAGE_SIZE).page(raw_page)


def _template_response(
    request: HttpRequest,
    template_name: str,
    context: dict[str, object] | None = None,
    *,
    status: int = 200,
) -> HyperviewTemplateResponse:
    """Render a document or validated fragment from the declared endpoint shape.

    Args:
        request: Request whose endpoint decorator declared the response shape.
        template_name: Consumer-owned HXML template name.
        context: Optional rendering context.
        status: HTTP status for the response.

    Returns:
        A document response for navigation or a validated fragment response for
        an in-place update.
    """
    response_class = (
        HyperviewFragmentTemplateResponse
        if request.hv_fragment
        else HyperviewTemplateResponse
    )
    return response_class(request, template_name, context, status=status)


def _error_response(
    request: HttpRequest, message: str, status: int
) -> HyperviewTemplateResponse:
    """Render a failure in the shape the caller's action can actually load.

    A replace/append action reaches the client through loadElement, which
    raises XMLRestrictedElementFound on doc, navigator, screen or body
    (hyperview/src/services/dom/parser.ts:300-366), so a fragment request must
    never be answered with the error document. The fragment carries no style ids
    at all because replace does not rebuild stylesheets and it can land on any
    screen. Its href-less action="reload" is load-bearing: hyperview.tsx:74-82
    resolves a null/empty href to the CURRENT screen URL, which is what lets one
    template recover any endpoint. Re-check that fallback on a hyperview upgrade.

    The fragment's root is <item>, not <view>, because the pagination behaviors
    append it into a <list>: hv-list feeds its FlatList only the <item> children
    it owns (elements/hv-list/index.tsx:184-189, 251), so a <view> landing there
    never mounts and its trigger="load" recovery never fires. HvView registers item
    as an alias (elements/hv-view/index.tsx:38-45), so the same fragment still renders
    identically when it replaces an ordinary view.

    Args:
        request: Request carrying the shape hxml_endpoint resolved for this view.
        message: Copy explaining the failure.
        status: HTTP status for the response.

    Returns:
        Bare error fragment for fragment requests, error screen otherwise.
    """
    template_name = (
        "fragments/error_transition.xml" if request.hv_fragment else "screens/error.xml"
    )
    # The error screen replaces one ROUTE's document, so its way out has to be a
    # screen url. `/hv/` would answer with the root navigator document, which HvDoc
    # cannot merge into a screen route and instead nests as a stack inside it
    # (hv-doc.tsx:120-131). Which screen is "home" depends on the session.
    home_href = "/hv/dashboard/" if request.user.is_authenticated else "/hv/login/"
    return _template_response(
        request,
        template_name,
        {"message": message, "home_href": home_href},
        status=status,
    )


def hxml_endpoint(view: View | None = None, *, fragment: object = False) -> View:
    """Declare a view's response shape and convert lookup failures to HXML.

    Args:
        view: Endpoint implementation when used as a bare decorator.
        fragment: Whether this view owes a bare fragment. Either a bool or a
            predicate taking the request, for views whose shape depends on the
            method or on a query parameter.

    Returns:
        Wrapped endpoint that publishes request.hv_fragment and never redirects
        unauthenticated users.
    """

    def decorate(inner: View) -> View:
        @wraps(inner)
        def wrapped(
            request: HttpRequest, *args: object, **kwargs: object
        ) -> HttpResponse:
            request.hv_fragment = (
                fragment(request) if callable(fragment) else bool(fragment)
            )
            try:
                return inner(request, *args, **kwargs)
            except Http404:
                return _error_response(
                    request, _("The requested item was not found."), 404
                )

        return wrapped

    return decorate(view) if view is not None else decorate


def _is_post(request: HttpRequest) -> bool:
    """Report whether this request is the POST half of a GET/POST endpoint."""
    return request.method == "POST"


def _wants_list_fragment(request: HttpRequest) -> bool:
    """Report whether a list endpoint was asked for a fragment rather than a screen."""
    return "fragment" in request.GET


def _require_user(request: HttpRequest) -> HttpResponse | None:
    if request.user.is_authenticated:
        return None
    if request.hv_fragment:
        return _error_response(request, _("Your session expired. Sign in again."), 401)
    return _template_response(request, "screens/session_expired.xml", status=401)


def _method(request: HttpRequest, *allowed: str) -> HttpResponse | None:
    if request.method in allowed:
        return None
    response = _error_response(
        request, _("This action does not support the requested method."), 405
    )
    response.headers["Allow"] = ", ".join(allowed)
    return response


def _greeting(hour: int) -> str:
    """Pick the salutation matching a local hour of the day.

    Args:
        hour: Local hour in the 0-23 range.

    Returns:
        Morning, afternoon, or evening greeting.
    """
    if hour < 12:
        return _("Good morning")
    if hour < 18:
        return _("Good afternoon")
    return _("Good evening")


def _initials(user: AbstractUser) -> str:
    """Build the avatar initials for one user.

    Args:
        user: Authenticated dashboard owner.

    Returns:
        Upper-cased initials from the full name, or from the username.
    """
    names = (user.first_name.strip(), user.last_name.strip())
    letters = "".join(name[0] for name in names if name)
    return (letters or user.get_username()[:2]).upper()


def _dashboard_context(request: HttpRequest) -> dict[str, object]:
    """Build the shared context for the dashboard screen and its fragment.

    Args:
        request: Incoming authenticated request.

    Returns:
        Counters, day summary, greeting, and avatar initials.
    """
    summary = dashboard_summary(request.user)
    return {
        "counts": summary["counts"],
        "summary": summary,
        "greeting": _greeting(timezone.localtime().hour),
        "initials": _initials(request.user),
    }


def _dashboard_response(
    request: HttpRequest, *, status: int = 200
) -> HyperviewTemplateResponse:
    return _template_response(
        request, "screens/dashboard.xml", _dashboard_context(request), status=status
    )


@hxml_endpoint
def root(request: HttpRequest) -> HttpResponse:
    """Serve the login or dashboard screen without redirects.

    Args:
        request: Incoming Hyperview request.

    Returns:
        Stack navigator targeting login or dashboard for the current session.
    """
    # One stable id in both sessions: `#root-route` in bottom_navigation.xml and
    # side_menu.xml navigates by this literal name, and StackRouter silently returns
    # null for a name it does not know (StackRouter.js:224-227). Only the href moves.
    route_href = "/hv/dashboard/" if request.user.is_authenticated else "/hv/login/"
    return _template_response(
        request,
        "screens/root.xml",
        {"route_id": "root-route", "route_href": route_href},
    )


@hxml_endpoint(fragment=_is_post)
def login_view(request: HttpRequest) -> HttpResponse:
    """Create a Django session from submitted credentials.

    Args:
        request: Incoming login request.

    Returns:
        Login document, form fragment, transition fragment, or method error response.
    """
    if invalid := _method(request, "GET", "POST"):
        return invalid
    if request.method == "POST":
        # Every POST is a `replace target="login-panel"`, so it must exit through the
        # panel fragment. Falling through to the screen document below raised
        # XMLRestrictedElementFound for any invalid form, e.g. an empty submit.
        form = LoginForm(request.POST)
        if form.is_valid():
            user = authenticate(
                request,
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password"],
            )
            if user is not None:
                login(request, user)
                if request.POST.get("enable_biometrics") == "on":
                    token = issue_biometric_token(user=user)
                else:
                    # A password login is authoritative about this device: without the
                    # opt-in the credential is revoked and the transition wipes the
                    # stored key, otherwise an earlier session's token keeps unlocking
                    # that account here.
                    revoke_biometric_token(user=user)
                    token = ""
                return _template_response(
                    request,
                    "fragments/login_transition.xml",
                    {"biometric_token": token},
                )
            form.add_error(None, _("The username or password is incorrect."))
        return _template_response(
            request,
            "fragments/login_panel.xml",
            # Echoed, not reset: the person retrying the password is the person who
            # just flipped this switch, and dropping it silently un-enrolled them on
            # the successful retry. Safe for the same reason _biometric_panel
            # pre-selects it on a rejected token -- and it still enrols nothing on
            # its own, because only a SUCCESSFUL password login reads this key.
            {
                "form": form,
                "optin_default": (
                    "on" if request.POST.get("enable_biometrics") == "on" else "off"
                ),
            },
            status=422,
        )
    return _template_response(
        request, "screens/login.xml", {"form": LoginForm(), "optin_default": "off"}
    )


def _biometric_attempt_key(request: HttpRequest) -> str:
    """Bucket unlock attempts by the credential presented, not by the caller alone.

    REMOTE_ADDR on its own collapses every client behind a proxy or NAT into a single
    counter (nothing here parses X-Forwarded-For), so ten rejected tokens would throttle
    a whole deployment and any success would clear the bucket for everyone. The token is
    256 bits of secrets.token_urlsafe, so a per-token limit is the only one that carries
    information anyway.

    Args:
        request: Incoming biometric login request.

    Returns:
        Cache key scoped to this client and this presented token.
    """
    digest = sha256(
        request.POST.get("biometric_token", "").strip().encode()
    ).hexdigest()
    return f"biometric-attempts:{request.META.get('REMOTE_ADDR', '')}:{digest}"


def _biometric_throttled(request: HttpRequest) -> bool:
    """Report whether this token has already been rejected too many times."""
    return cache.get(_biometric_attempt_key(request), 0) >= BIOMETRIC_ATTEMPT_LIMIT


def _count_biometric_failure(request: HttpRequest) -> None:
    """Count one rejected token; successes reset the counter instead."""
    key = _biometric_attempt_key(request)
    # ponytail: read-modify-write races undercount under concurrency; swap for
    # cache.incr with a seeded key if a real backend makes that worth the round trip.
    cache.set(key, cache.get(key, 0) + 1, timeout=BIOMETRIC_ATTEMPT_WINDOW)


def _biometric_panel(
    request: HttpRequest, message: str, status: int, *, wipe_device: bool
) -> HttpResponse:
    """Render the login panel after a refused biometric attempt.

    Args:
        request: Incoming biometric login request.
        message: Copy explaining the refusal.
        status: HTTP status for the response.
        wipe_device: Whether the panel should clear the device's stored token.
            Only a rejected token justifies that; a throttled request says nothing
            about whether the token is still valid.

    Returns:
        Login panel fragment carrying the error copy.
    """
    return _template_response(
        request,
        "fragments/login_panel.xml",
        {
            "form": LoginForm(),
            "biometric": "reset" if wipe_device else "retry",
            "biometric_error": message,
            # A rejected token is the one signal that the person in front of the
            # phone just asked for biometrics, so it is the only thing allowed to
            # pre-select the switch. The probe never does: a stored token names a
            # device, not a person, and on a shared phone that would enrol whoever
            # signs in next without asking.
            "optin_default": "on" if wipe_device else "off",
        },
        status=status,
    )


@hxml_endpoint(fragment=True)
def biometric_login(request: HttpRequest) -> HttpResponse:
    """Exchange a device token issued to this phone for a Django session.

    Args:
        request: Incoming biometric login request.

    Returns:
        Transition fragment carrying a rotated token, or a reset login panel.
    """
    if invalid := _method(request, "POST"):
        return invalid
    if _biometric_throttled(request):
        return _biometric_panel(
            request,
            _("Too many attempts. Sign in with your password."),
            429,
            wipe_device=False,
        )
    user = authenticate_biometric_token(
        raw_token=request.POST.get("biometric_token", "")
    )
    if user is None:
        _count_biometric_failure(request)
        return _biometric_panel(
            request,
            _("This device is no longer recognised. Sign in to enable it again."),
            401,
            wipe_device=True,
        )
    cache.delete(_biometric_attempt_key(request))
    # authenticate_biometric_token resolves the user itself, so name the backend that
    # would have produced it; without it a second configured backend raises here.
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return _template_response(
        request,
        "fragments/login_transition.xml",
        {"biometric_token": issue_biometric_token(user=user)},
    )


def _app_version(request: HttpRequest) -> str:
    """Report the client version this request announced.

    Args:
        request: Incoming request, which may come from any released binary.

    Returns:
        The announced version, or "unknown" when it is absent or malformed.
    """
    raw = request.headers.get(APP_VERSION_HEADER, "")
    return raw if APP_VERSION_PATTERN.fullmatch(raw) else "unknown"


@hxml_endpoint(fragment=False)
@vary_on_headers(APP_VERSION_HEADER)
def about(request: HttpRequest) -> HttpResponse:
    """Render package and application information for signed-in users.

    Args:
        request: Incoming About screen request.

    Returns:
        Complete About screen HXML document.
    """
    if denied := _require_user(request):
        return denied
    if invalid := _method(request, "GET"):
        return invalid
    return _template_response(
        request,
        "screens/about.xml",
        {
            "app_version": _app_version(request),
            "django_version": version("Django"),
            "dj_hyperview_version": version("dj-hyperview"),
            "hyperview_version": HYPERVIEW_SCHEMA_VERSION,
            "copyright_year": timezone.now().year,
        },
    )


def _client_version(request: HttpRequest) -> tuple[int, ...]:
    """Parse the announced client version into something orderable.

    Args:
        request: Incoming request, which announces its own version or nothing.

    Returns:
        A three-part tuple. "1.1" means 1.1.0 rather than sorting below it, and
        "nightly", "unknown" and anything absent all fall to (0, 0, 0).
    """
    numbers: list[int] = []
    for part in _app_version(request).split("."):
        if not part.isdigit():
            break
        numbers.append(int(part))
    return tuple((numbers + [0, 0, 0])[:3])


def _supports_avatar_upload(request: HttpRequest) -> bool:
    """Report whether this client registers the pick-avatar behavior.

    Rule 11 of this codebase, and the reason this gate exists at all: Hyperview
    silently ignores an action no registered behavior claims, so shipping the row
    to an older binary produces a "Change photo" control that does nothing when
    tapped, with no error anywhere. The endpoint itself is NOT gated -- the gate is
    about a dead control, not about authorisation.

    Args:
        request: Incoming request, which announces its own version or nothing.

    Returns:
        True when the announced version is at least MIN_AVATAR_UPLOAD_VERSION.
    """
    return _client_version(request) >= MIN_AVATAR_UPLOAD_VERSION


def _supports_swipe_actions(request: HttpRequest) -> bool:
    """Report whether this client can render server-declared swipe actions.

    A backend deploy reaches every installed binary at once, and dj-hyperview can
    publish a template straight from the database, so release ordering cannot keep
    the new markup away from an old bundle.

    Only the CATEGORY list still asks. A task row carries both shapes at once and
    needs no gate, but a category row cannot: the pre-1.1.0 component is task-shaped
    and always draws an Edit/Complete/Delete triad, so a category served through it
    would show a Complete button with no toggle-href behind it -- the silent dead
    control this header exists to prevent. Callers must therefore declare
    Vary: X-App-Version, because the response body moves with the request header.

    Args:
        request: Incoming request, which announces its own version or nothing.

    Returns:
        True when the announced version is at least MIN_SWIPE_ACTIONS_VERSION.
    """
    return _client_version(request) >= MIN_SWIPE_ACTIONS_VERSION


def _settings_context(request: HttpRequest, form: ProfileForm) -> dict[str, object]:
    """Build everything the settings screen and its 422 fragment both need.

    Args:
        request: Incoming authenticated settings request.
        form: Bound or unbound profile form to render.

    Returns:
        Context shared by screens/settings.xml and fragments/settings_form_panel.xml.
    """
    return {
        "form": form,
        "app_version": _app_version(request),
        "biometric_enrolled": has_biometric_credential(request.user),
        # Re-armed the same way pending_avatar is. A 422 rebuilds this panel from
        # the database, and the credential is still there because the atomic block
        # never ran, so a hardcoded "on" repainted the switch over a pending
        # revocation: the user fixed the other field, saved, and the DOM serialised
        # "on" again. On a GET there is no POST to read and the switch starts "on",
        # which is the only position an enrolled phone can start from.
        "biometric_switch_value": (
            "off" if request.POST.get(BIOMETRIC_SWITCH) == "off" else "on"
        ),
        **_avatar_context(request),
    }


# The switch is the only thing that can say this, and it says it by VALUE, never
# by absence. getNameValueFormInputValues posts a named input's `value` attribute
# unconditionally (client services/index.ts:292-300), so a native <switch> that is
# on screen is ALWAYS in the body -- unlike an HTML checkbox, where absence means
# off. Absence here means the control was not rendered at all, which is the
# not-enrolled case and is a statement about nothing. Reading absence as "off"
# would let any body that never carried the key revoke a credential.
BIOMETRIC_SWITCH = "biometric_unlock"


@hxml_endpoint(fragment=_is_post)
@vary_on_headers(APP_VERSION_HEADER)
def settings_view(request: HttpRequest) -> HttpResponse:
    """Show the account settings screen, and commit all of it in one request.

    The photo, the profile fields and the biometric switch are one form with one
    Save button. They used to be three writers plus the preference switcher, each
    committing on its own tap, which is how a user could mistype an email, pick a
    photo, tap Save, and get the photo stored and the email refused with nothing
    on screen saying which half had happened.

    Args:
        request: Incoming settings request.

    Returns:
        Settings document, form fragment at 422, or a saved-settings transition.
    """
    if denied := _require_user(request):
        return denied
    if invalid := _method(request, "GET", "POST"):
        return invalid
    if request.method == "GET":
        return _template_response(
            request,
            "screens/settings.xml",
            _settings_context(request, ProfileForm(instance=request.user)),
        )
    # Not `request.POST or None`: every profile field is optional, so a fully blank
    # POST is a valid "clear my profile" and an unbound form would answer 422 with
    # no errors.
    form = ProfileForm(request.POST, instance=request.user)
    # Only when something was actually picked. The hidden field is always in the
    # DOM, so it is always serialised, and binding an AvatarForm to the empty
    # string would answer "That is not an image" on every plain profile save.
    posted = request.POST.get("avatar_data", "")
    avatar = AvatarForm(request.POST) if posted else None
    if form.is_valid() and (avatar is None or avatar.is_valid()):
        # Database transactions cannot roll back object storage. Keep the name of
        # the new file so any later failure can compensate without touching the
        # previous avatar, whose deletion remains deferred until commit.
        stored_avatar = None
        try:
            with transaction.atomic():
                update_profile(
                    user=request.user,
                    first_name=form.cleaned_data["first_name"],
                    last_name=form.cleaned_data["last_name"],
                    email=form.cleaned_data["email"],
                )
                if avatar is not None:
                    stored_avatar = store_avatar(
                        user=request.user,
                        data=avatar.cleaned_data["avatar_data"],
                    ).avatar
                forgotten = request.POST.get(BIOMETRIC_SWITCH) == "off"
                if forgotten:
                    revoke_biometric_token(user=request.user)
        except Exception:
            if stored_avatar is not None:
                stored_avatar.storage.delete(stored_avatar.name)
            raise
        return _template_response(
            request,
            "fragments/settings_transition.xml",
            {"biometrics_forgotten": forgotten},
        )
    error = avatar.errors.get("avatar_data", [None])[0] if avatar is not None else None
    return _template_response(
        request,
        "fragments/settings_form_panel.xml",
        {
            **_settings_context(request, form),
            "avatar_error": error,
            # The RAW posted string, re-armed only when the photo itself was fine
            # and something else refused the save. Re-arming a payload that just
            # failed only queues the same refusal behind the next tap.
            "pending_avatar": posted if avatar is not None and not error else "",
            "pending_avatar_mime": (
                f"image/{avatar.source_format.lower()}"
                if avatar is not None and not error
                else ""
            ),
        },
        status=422,
    )


@hxml_endpoint(fragment=True)
def logout_view(request: HttpRequest) -> HttpResponse:
    """End a Django session and reload the guest root document.

    Args:
        request: Incoming logout request.

    Returns:
        Logout transition fragment or method error response.
    """
    if invalid := _method(request, "POST"):
        return invalid
    # Deliberately does NOT revoke: the enrolment belongs to the device, not to the
    # session. It ends with the TTL, with the biometric switch in
    # partials/security_card.xml saved through settings_view, or with a password
    # login whose opt-in switch is off.
    logout(request)
    response = _template_response(request, "fragments/logout_transition.xml")
    # The preference mirrors are per-DEVICE, and an explicit sign-out hands the device
    # to somebody else. A blank profile does not override either channel, so the next
    # account to sign in would inherit the previous one's language from
    # LocaleMiddleware's cookie and its palette from the context processor's fallback.
    # An EXPIRED session does not come through here, so the sign-in screen a user
    # returns to at night still reads the palette they left -- which is the only thing
    # these cookies exist for.
    response.delete_cookie(THEME_COOKIE)
    response.delete_cookie(settings.LANGUAGE_COOKIE_NAME)
    return response


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


# One endpoint for every stored presentation preference, because a theme and a
# language differ only in the column they write. The TARGET value rides in the
# query string, so the server always writes absolute state and a double tap or a
# retried request cannot flip anything back.
#
# NOT a <switch>, even though that is the natural control for a binary and the
# client ships one. HvSwitch's onChange clones the element before triggering
# (elements/hv-switch/index.tsx:58-61) and a clone has no parentNode, so
# ComponentRegistry.getFormData walks up to nothing (services/components/index.ts:64-71
# via services/index.ts:274-287) and hyperview.tsx:365 posts a NULL body: no
# csrfmiddlewaretoken, no field. Django would reject every tap at the CSRF check.
# Worse, RN's Switch calls onChange BEFORE onValueChange (Switch.js:203-205) and it
# is onValueChange that swaps the new `value` in, so even a body that did arrive
# would carry the state the user was LEAVING. A view inside a <form>, which is the
# shape sign-out and forget-biometrics already ship, passes the live element and
# therefore the real form.
PREFERENCE_FIELDS = {
    "theme": Profile.Theme.values,
    "language": Profile.Language.values,
}


@hxml_endpoint(fragment=True)
def preferences(request: HttpRequest) -> HttpResponse:
    """Store one presentation preference and repaint the screen that asked.

    Args:
        request: Incoming preference request naming exactly one field.

    Returns:
        Transition fragment, or an error fragment in the caller's own shape.
    """
    if denied := _require_user(request):
        return denied
    if invalid := _method(request, "POST"):
        return invalid
    stated = [name for name in PREFERENCE_FIELDS if name in request.GET]
    if len(stated) != 1:
        return _error_response(request, _("Name exactly one preference."), 400)
    field = stated[0]
    value = request.GET[field]
    if value not in PREFERENCE_FIELDS[field]:
        return _error_response(request, _("Unknown preference value."), 400)
    set_preference(user=request.user, field=field, value=value)
    if field == "language":
        # The middleware resolved the language before this write, so without an
        # explicit activate the confirmation arrives in the OLD language while the
        # screen behind it repaints in the new one.
        translation.activate(value)
        request.LANGUAGE_CODE = value
        message = _("Language updated.")
    else:
        message = _("Appearance updated.")
    response = _template_response(
        request, "fragments/preference_transition.xml", {"notice_message": message}
    )
    _remember_preference(response, field, value)
    return response


def _avatar_context(request: HttpRequest) -> dict[str, object]:
    """Build the context partials/avatar_panel.xml needs on every host.

    The photo itself is NOT in here. The templates read
    request.user.profile.avatar directly, which is safe for an account that
    predates migration 0003 because RelatedObjectDoesNotExist inherits from
    AttributeError and the template engine resolves that to an empty value -- the
    same fallback todo/context_processors.py already documents.

    Args:
        request: Incoming authenticated request.

    Returns:
        The initials shown while no photo exists, and whether this client can pick.
    """
    return {
        "initials": _initials(request.user),
        "avatar_upload_supported": _supports_avatar_upload(request),
    }


def _remember_preference(response: HttpResponse, field: str, value: str) -> None:
    """Mirror the preference into a cookie so the signed-out screens can read it.

    The login and session-expired documents render for an anonymous request, so
    there is no profile to consult and a dark-mode user whose session lapses would
    otherwise be handed a full-brightness white screen. The profile always wins
    while one exists, so this can never override a preference set elsewhere.

    Args:
        response: Response about to be returned.
        field: Preference that was written.
        value: Value that was written.
    """
    name = THEME_COOKIE if field == "theme" else settings.LANGUAGE_COOKIE_NAME
    response.set_cookie(
        name,
        value,
        max_age=THEME_COOKIE_MAX_AGE,
        samesite="Lax",
        secure=not settings.DEBUG,
    )


@hxml_endpoint(fragment=True)
def menu(request: HttpRequest) -> HttpResponse:
    """Render the authenticated side-menu fragment.

    Args:
        request: Incoming side-menu request.

    Returns:
        Open side-menu fragment, session-expired response, or method error.
    """
    if denied := _require_user(request):
        return denied
    if invalid := _method(request, "GET"):
        return invalid
    active_nav = request.GET.get("active", "")
    return _template_response(
        request,
        "fragments/side_menu.xml",
        {"active_nav": active_nav, "initials": _initials(request.user)},
    )


@hxml_endpoint(fragment=True)
def menu_close(request: HttpRequest) -> HttpResponse:
    """Render an empty side-menu host to close the overlay.

    Args:
        request: Incoming side-menu close request.

    Returns:
        Empty side-menu host, session-expired response, or method error.
    """
    if denied := _require_user(request):
        return denied
    if invalid := _method(request, "GET"):
        return invalid
    return _template_response(request, "fragments/side_menu_host.xml")


@hxml_endpoint(fragment=_wants_list_fragment)
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
        return _error_response(request, _("Unknown task filter."), 400)
    category = None
    category_id = request.GET.get("category")
    if category_id:
        try:
            category_pk = UUID(category_id)
        except ValueError:
            # UUIDField.to_python raises ValidationError, not Http404, so an
            # unparseable id from a stale deep link escapes hxml_endpoint and 500s.
            # The client renders nothing at all for a 5xx (parser.ts:180-190 throws
            # ServerError), so this has to come back as a 400 in the caller's shape.
            return _error_response(request, _("Unknown category filter."), 400)
        category = get_object_or_404(Category, pk=category_pk, user=request.user)
    fragment = request.GET.get("fragment")
    templates = {
        None: "screens/tasks.xml",
        "list": "fragments/task_list.xml",
        "items": "fragments/task_items.xml",
    }
    if fragment not in templates:
        return _error_response(request, _("Unknown task-list fragment."), 400)
    try:
        page_obj = _paginate(
            tasks_for_user(request.user, status=status_filter, category=category),
            request.GET.get("page", "1"),
        )
    except EmptyPage, PageNotAnInteger:
        return _error_response(request, _("Unknown task-list page."), 400)
    context = {
        "tasks": page_obj.object_list,
        "categories": Category.objects.filter(user=request.user),
        "status_filter": status_filter,
        "selected_category": category,
        "page_obj": page_obj,
    }
    return _template_response(request, templates[fragment], context)


def _task_form_response(
    request: HttpRequest, form: TaskForm, *, task: Task | None = None, status: int = 200
) -> HyperviewTemplateResponse:
    template_name = (
        "fragments/task_form_panel.xml"
        if request.method == "POST"
        else "screens/task_form.xml"
    )
    return _template_response(
        request,
        template_name,
        {
            "form": form,
            "task": task,
            "header_title": _("Edit task") if task else _("New task"),
        },
        status=status,
    )


@hxml_endpoint(fragment=_is_post)
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
        return _template_response(
            request,
            "fragments/task_transition.xml",
            {"notice_message": _("Task created.")},
            status=201,
        )
    return _task_form_response(
        request, form, status=422 if request.method == "POST" else 200
    )


@hxml_endpoint(fragment=_is_post)
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
        return _template_response(
            request,
            "fragments/task_transition.xml",
            {"notice_message": _("Task updated.")},
        )
    return _task_form_response(
        request, form, task=task, status=422 if request.method == "POST" else 200
    )


@hxml_endpoint(fragment=True)
def task_toggle(request: HttpRequest, task_id: UUID) -> HttpResponse:
    """Toggle an owned task and return the private task list.

    Args:
        request: Incoming mutation request.
        task_id: Task identifier from the route.

    Returns:
        Dashboard content fragment when toggled from the dashboard panel,
        otherwise the task-list reload transition fragment.
    """
    if denied := _require_user(request):
        return denied
    if invalid := _method(request, "POST"):
        return invalid
    task = toggle_task(user=request.user, task_id=task_id)
    if request.GET.get("panel") == "dashboard":
        return _template_response(
            request,
            "fragments/dashboard_content.xml",
            _dashboard_context(request),
        )
    message = _("Task completed.") if task.is_completed else _("Task reopened.")
    return _template_response(
        request,
        "fragments/task_list_transition.xml",
        {"notice_message": message},
    )


@hxml_endpoint(fragment=True)
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
    return _template_response(
        request,
        "fragments/task_list_transition.xml",
        {"notice_message": _("Task deleted.")},
    )


@hxml_endpoint(fragment=_wants_list_fragment)
@vary_on_headers(APP_VERSION_HEADER)
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
    fragment = request.GET.get("fragment")
    templates = {
        None: "screens/categories.xml",
        "list": "fragments/category_list.xml",
        "items": "fragments/category_items.xml",
    }
    if fragment not in templates:
        return _error_response(request, _("Unknown category-list fragment."), 400)
    try:
        page_obj = _paginate(
            Category.objects.filter(user=request.user)
            .annotate(task_count=Count("tasks"))
            .order_by("name"),
            request.GET.get("page", "1"),
        )
    except EmptyPage, PageNotAnInteger:
        return _error_response(request, _("Unknown category-list page."), 400)
    return _template_response(
        request,
        templates[fragment],
        {
            "categories": page_obj.object_list,
            "page_obj": page_obj,
            "swipe_actions": _supports_swipe_actions(request),
        },
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
    return _template_response(
        request,
        template_name,
        {
            "form": form,
            "category": category,
            "header_title": _("Edit category") if category else _("New category"),
        },
        status=status,
    )


@hxml_endpoint(fragment=_is_post)
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
        return _template_response(
            request,
            "fragments/category_transition.xml",
            {"notice_message": _("Category created.")},
            status=201,
        )
    return _category_form_response(
        request, form, status=422 if request.method == "POST" else 200
    )


@hxml_endpoint(fragment=_is_post)
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
        return _template_response(
            request,
            "fragments/category_transition.xml",
            {"notice_message": _("Category updated.")},
        )
    return _category_form_response(
        request,
        form,
        category=category,
        status=422 if request.method == "POST" else 200,
    )


@hxml_endpoint(fragment=True)
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
    return _template_response(
        request,
        "fragments/category_list_transition.xml",
        {"notice_message": _("Category deleted.")},
    )


def csrf_failure(request: HttpRequest, reason: str = "") -> HyperviewTemplateResponse:
    """Return CSRF rejection using the Hyperview media contract.

    Args:
        request: Rejected request.
        reason: Internal Django rejection reason, deliberately not exposed.

    Returns:
        Generic HXML CSRF error.
    """
    # The ONLY place that sniffs Accept. CsrfViewMiddleware runs before any view, so
    # hxml_endpoint has not set request.hv_fragment yet. Substring membership only,
    # never first-match negotiation: the client sends "application/xml" FIRST in both
    # fragment and document loads (hyperview/src/services/dom/parser.ts:120), so the
    # first acceptable type is always the wrong signal. Do not copy this into
    # _error_response or _require_user: no test sends an Accept header, so every one
    # of them would silently flip to the document branch and hide this bug class.
    request.hv_fragment = HYPERVIEW_FRAGMENT_MEDIA_TYPE in request.headers.get(
        "Accept", ""
    )
    return _error_response(
        request, _("Security validation failed. Reload and try again."), 403
    )


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
    return _template_response(request, "screens/source_probe.xml")
