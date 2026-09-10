"""Thin cookie-authenticated SSE endpoint; no HXML or presentation metadata."""

import asyncio
import logging

from dj_hyperview.realtime import sse_response
from django.http import HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
from django.utils.cache import patch_vary_headers

from .realtime_auth import RealtimeDenied, authorize
from .realtime_config import RealtimeConfig
from .realtime_stream import Broker, open_stream
from .session_contract import (
    CLIENT_CONTRACT_HEADER,
    EXPECTED_SESSION_HEADER,
    SESSION_BINDING_HEADER,
)

logger = logging.getLogger(__name__)


def _broker(config: RealtimeConfig) -> Broker:
    from dj_hyperview.realtime import RedisBroker

    return RedisBroker(config.redis_url, namespace=config.namespace)


def _failure(status: int) -> JsonResponse:
    response = JsonResponse({"error": "realtime-unavailable"}, status=status)
    response["Cache-Control"] = "no-store"
    if status == 405:
        response["Allow"] = "GET"
    patch_vary_headers(
        response, ["Cookie", "Origin", CLIENT_CONTRACT_HEADER, EXPECTED_SESSION_HEADER]
    )
    return response


async def events(request: HttpRequest) -> HttpResponse | StreamingHttpResponse:
    """Acquire fresh authority and ACKed subscription before transferring ownership.

    Args:
        request: Incoming GET, with the actual Django session cookie.

    Returns:
        Owned SSE stream or a bounded non-HTML error without identity metadata.
    """
    stream = None
    try:
        access = await authorize(request)
        stream = await open_stream(access, _broker(access.config))
        response = sse_response(stream, aclose=stream.aclose)
        response[SESSION_BINDING_HEADER] = access.identity.binding
        response["Cache-Control"] = "no-store, no-transform"
        patch_vary_headers(
            response,
            ["Cookie", "Origin", CLIENT_CONTRACT_HEADER, EXPECTED_SESSION_HEADER],
        )
        return response
    except BaseException as error:
        if stream is not None:
            await stream.aclose()
        if isinstance(error, asyncio.CancelledError):
            raise
        if isinstance(error, RealtimeDenied):
            return _failure(error.status)
        if not isinstance(error, Exception):
            raise
        logger.warning("realtime-request-failed")
        return _failure(503)
