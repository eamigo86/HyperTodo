"""Reject unsupported SSE methods before CSRF, without bypassing any GET guard."""

from collections.abc import Awaitable, Callable

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.http import HttpRequest, HttpResponse, JsonResponse

from .realtime_config import get_realtime_config


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
        if request.path != "/realtime/events/" or request.method == "GET":
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
