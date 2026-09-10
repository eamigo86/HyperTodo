"""Bounded HTTP and cookie isolation, with an explicit demo-only SSE deadline."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urljoin, urlsplit

from .native_app_evidence import REPORT_PATH, EvidenceCollector
from .native_app_fixture import NativeFixture

ASGICall = Callable[..., Awaitable[None]]


class RejectedRedirect(Exception):
    """Signal an off-origin redirect before response headers reach the client."""


class NativeAppBoundary:
    """Filter unrelated cookies; SSE extension is explicit and exact-route only."""

    def __init__(
        self,
        app: ASGICall,
        fixture: NativeFixture,
        *,
        body_timeout: float = 10,
        response_timeout: float = 15,
        evidence: EvidenceCollector | None = None,
        sse_response_timeout: float | None = None,
    ) -> None:
        """Keep ordinary deadlines unless a demo explicitly enables bounded SSE."""
        if sse_response_timeout is not None and sse_response_timeout != 70:
            raise ValueError("fixture SSE deadline must be 70 seconds")
        self.sse_response_timeout = sse_response_timeout
        self.app = app
        self.fixture = fixture
        self.evidence = evidence
        self.names = {name.encode("ascii") for name in fixture.cookie_names}
        self.body_timeout = body_timeout
        self.response_timeout = response_timeout

    async def __call__(
        self, scope: dict[str, Any], receive: Callable, send: Callable
    ) -> None:
        """Admit only the fresh host, owned cookies and complete bounded HTTP bodies."""
        if scope["type"] != "http":
            raise ValueError("fixture supports ordinary HTTP only")
        headers = scope.get("headers", [])
        hosts = [v for k, v in headers if k.lower() == b"host"]
        host = self.fixture.host.encode()
        if len(hosts) != 1 or hosts[0] not in {
            host,
            host + b":" + str(scope["server"][1]).encode(),
        }:
            await self._error(send, 400)
            return
        report = scope["path"] == REPORT_PATH

        async def reject(status: int, reason: str = "invalid-record") -> None:
            if report and self.evidence is not None:
                self.evidence.reject(reason)
            await self._error(send, status)

        if report:
            if self.evidence is None:
                await self._error(send, 404)
                return
            if scope["method"] != "POST":
                await reject(405)
                return
            types = [v for k, v in headers if k.lower() == b"content-type"]
            if scope.get("query_string", b"") or types != [b"application/json"]:
                await reject(400)
                return
        limit = 2048 if report else 65536
        filtered, cookies, seen = [], [], set()
        for key, value in headers:
            if key.lower() != b"cookie":
                filtered.append((key, value))
                continue
            # Inspect names only; never decode or interpret unknown cookie values.
            for item in value.split(b";"):
                item = item.strip()
                equal = item.find(b"=")
                name = item[:equal].strip() if equal >= 0 else b""
                if name in self.names:
                    if name in seen:
                        await reject(400)
                        return
                    seen.add(name)
                    cookies.append(item)
        if cookies:
            filtered.append((b"cookie", b"; ".join(cookies)))
        lengths = [v for k, v in headers if k.lower() == b"content-length"]
        if lengths and (len(lengths) != 1 or not lengths[0].isdigit()):
            await reject(400)
            return
        if lengths and int(lengths[0]) > limit:
            await reject(413)
            return
        body = bytearray()
        try:
            async with asyncio.timeout(self.body_timeout):
                while True:
                    event = await receive()
                    if event["type"] == "http.disconnect":
                        if report:
                            self.evidence.reject("report-failed")
                        return
                    body.extend(event.get("body", b""))
                    if len(body) > limit:
                        await reject(413)
                        return
                    if not event.get("more_body", False):
                        break
        except TimeoutError:
            await reject(408, "report-failed")
            return
        if lengths and int(lengths[0]) != len(body):
            await reject(400)
            return
        if report:
            try:
                self.evidence.record(bytes(body))
            except ValueError:
                await self._error(send, 400)
                return
            await self._error(send, 204)
            return
        consumed = False
        started = False

        async def replay_receive() -> dict[str, Any]:
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            # Preserve real ASGI disconnect observation; never synthesize an abort.
            return await receive()

        async def safe_send(event: dict[str, Any]) -> None:
            nonlocal started
            if event["type"] == "http.response.start":
                if (
                    self.sse_response_timeout is not None
                    and scope["path"] == "/realtime/events/"
                    and scope["method"] == "GET"
                    and not scope.get("query_string", b"")
                    and event["status"] == 200
                    and [
                        (k.lower(), v)
                        for k, v in event.get("headers", [])
                        if k.lower() == b"content-type"
                    ]
                    == [(b"content-type", b"text/event-stream")]
                ):
                    deadline.reschedule(
                        asyncio.get_running_loop().time() + self.sse_response_timeout
                    )
                outgoing = []
                for key, value in event.get("headers", []):
                    if (
                        key.lower() == b"set-cookie"
                        and value.split(b"=", 1)[0].strip() not in self.names
                    ):
                        continue
                    if key.lower() == b"location":
                        origin = "http://" + hosts[0].decode("ascii")
                        target = urlsplit(
                            urljoin(origin + scope["path"], value.decode("latin1"))
                        )
                        if target.scheme != "http" or target.netloc != hosts[0].decode(
                            "ascii"
                        ):
                            raise RejectedRedirect
                    outgoing.append((key, value))
                event = {**event, "headers": outgoing}
                started = True
            await send(event)

        try:
            async with asyncio.timeout(self.response_timeout) as deadline:
                await self.app(
                    {**scope, "headers": filtered}, replay_receive, safe_send
                )
        except (TimeoutError, RejectedRedirect) as error:
            if started:
                raise
            await self._error(send, 504 if isinstance(error, TimeoutError) else 502)

    @staticmethod
    async def _error(send: Callable, status: int) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-length", b"0"), (b"cache-control", b"no-store")],
            }
        )
        await send({"type": "http.response.body", "body": b""})
