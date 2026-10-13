"""Reject unsupported SSE methods before CSRF, without bypassing any GET guard."""

from collections.abc import Awaitable, Callable

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import get_script_prefix, reverse

from .realtime_config import get_realtime_config

# The name config/urls.py gives the route; the path itself is written only there.
STREAM_URL_NAME = "realtime-events"


def is_stream_request(request: HttpRequest) -> bool:
    """Tell whether a request is for the SSE route, wherever the site is mounted.

    The route is found by its URL name. reverse() answers with the script prefix in
    front (SCRIPT_NAME, or FORCE_SCRIPT_NAME), while path_info is the path below
    it, so the prefix comes off before the two are compared. Comparing request.path
    with a literal only matched a site served from the root.

    Args:
        request: Incoming request.

    Returns:
        True for the exact stream route, whatever the method.
    """
    return request.path_info == "/" + reverse(STREAM_URL_NAME).removeprefix(
        get_script_prefix()
    )


class RealtimeMethodMiddleware:
    """Exact-path method rejection only; never inspect auth or session cookies."""

    sync_capable = True
    async_capable = True

    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponse | Awaitable[HttpResponse]],
    ) -> None:
        """Preserve the downstream callable and its public async capability.

        Args:
            get_response: Remaining Django middleware/view chain.
        """
        self.get_response = get_response
        self.is_async = iscoroutinefunction(get_response)
        if self.is_async:
            markcoroutinefunction(self)

    def _reject(self, request: HttpRequest) -> HttpResponse | None:
        if request.method == "GET" or not is_stream_request(request):
            return None
        enabled = get_realtime_config() is not None
        response = JsonResponse(
            {"error": "realtime-unavailable"}, status=405 if enabled else 404
        )
        response["Cache-Control"] = "no-store"
        if enabled:
            response["Allow"] = "GET"
        return response

    def __call__(self, request: HttpRequest) -> HttpResponse | Awaitable[HttpResponse]:
        """Reject only unsupported methods on the exact SSE route.

        Args:
            request: Incoming request, with no auth or cookie access here.

        Returns:
            Downstream response or a method/disabled rejection.
        """
        if self.is_async:
            return self._async(request)
        response = self._reject(request)
        return response if response is not None else self.get_response(request)

    async def _async(self, request: HttpRequest) -> HttpResponse:
        response = self._reject(request)
        return response if response is not None else await self.get_response(request)
