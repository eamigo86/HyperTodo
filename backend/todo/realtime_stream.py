"""Bounded worker admission and fresh authorization around broker frames."""

import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Protocol

from .realtime_auth import (
    Access,
    Identity,
    RealtimeDenied,
    fresh_identity_async,
    same_identity,
    topics_for,
)

logger = logging.getLogger(__name__)
HEARTBEAT = 15.0
LIFETIME = 60.0
BROKER_TIMEOUT = 2.0
_RESOURCES = ("tasks", "categories", "ui")


class Subscription(Protocol):
    """Package subscription contract after every selected topic is acknowledged."""

    def __aiter__(self) -> AsyncIterator[Mapping[str, object]]:
        """Return the acknowledged subscription iterator."""
        ...

    async def __anext__(self) -> Mapping[str, object]:
        """Wait for the next broker envelope; cancellation preserves ownership."""
        ...

    async def aclose(self) -> None:
        """Release the subscription and wake outstanding reads."""
        ...


class Broker(Protocol):
    """Minimal package broker surface used by this controller."""

    async def subscribe(self, topics: tuple[str, ...]) -> Subscription:
        """Return only after every requested topic is acknowledged."""
        ...


class _Admission:
    def __init__(self, pool: Admissions, key: tuple[str, str]) -> None:
        self.pool = pool
        self.key = key
        self.released = False

    def release(self) -> None:
        with self.pool.lock:
            if not self.released:
                self.released = True
                self.pool.counts[self.key] -= 1
                if self.pool.counts[self.key] == 0:
                    del self.pool.counts[self.key]
                self.pool.total -= 1


class Admissions:
    """Fixed process-local 256-total / 4-per-principal stream capacity."""

    def __init__(self) -> None:
        """Start an empty, thread-safe worker capacity counter."""
        self.lock = threading.Lock()
        self.total = 0
        self.counts: dict[tuple[str, str], int] = {}

    def acquire(self, identity: Identity) -> _Admission:
        """Reserve only an authenticated server-side principal.

        Args:
            identity: Freshly verified principal, including its actual alias.

        Returns:
            Idempotently releasable admission lease.

        Raises:
            RealtimeDenied: If either worker-local capacity is exhausted.
        """
        key = (identity.using, identity.user_id)
        with self.lock:
            if self.total >= 256 or self.counts.get(key, 0) >= 4:
                raise RealtimeDenied(503)
            self.total += 1
            self.counts[key] = self.counts.get(key, 0) + 1
        return _Admission(self, key)


admissions = Admissions()


def _event(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {"event", "data"}:
        raise ValueError("invalid-realtime-event")
    name, data = value["event"], value["data"]
    if (
        not isinstance(data, Mapping)
        or type(data.get("version")) is not int
        or data["version"] != 1
    ):
        raise ValueError("invalid-realtime-event")
    if name in {"resync", "auth-required"} and set(data) == {"version"}:
        return {"event": name, "data": {"version": 1}}
    if name == "invalidate" and set(data) == {"version", "resources"}:
        resources = data["resources"]
        if (
            isinstance(resources, list)
            and resources
            and resources == [r for r in _RESOURCES if r in resources]
        ):
            return {"event": name, "data": {"version": 1, "resources": list(resources)}}
    raise ValueError("invalid-realtime-event")


class OwnedStream:
    """Own an acquired subscription and admission even before first iteration."""

    def __init__(
        self,
        access: Access,
        subscription: Subscription,
        admission: _Admission,
        fresh: Callable[[str], Awaitable[Identity | None]],
        heartbeat: float,
        lifetime: float,
    ) -> None:
        """Capture acquired resources and their finite connection deadline.

        Args:
            access: Immutable actual-cookie authority.
            subscription: Already acknowledged broker subscription.
            admission: Acquired capacity lease.
            fresh: Session resolver called before every frame.
            heartbeat: Comment interval.
            lifetime: Maximum connection lifetime.
        """
        self.access = access
        self.subscription = subscription
        self.admission = admission
        self.fresh = fresh
        self.heartbeat = heartbeat
        self.deadline = asyncio.get_running_loop().time() + lifetime
        self.closed = False
        self._read: asyncio.Task | None = None
        self._cleanup: asyncio.Task | None = None

    def __aiter__(self) -> OwnedStream:
        """Return this single-consumer owned iterator."""
        return self

    async def __anext__(self) -> dict[str, object] | None:
        """Return one freshly authorized frame or close the finite stream."""
        if self.closed:
            raise StopAsyncIteration
        remaining = self.deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            await self.aclose()
            raise StopAsyncIteration
        try:
            self._read = asyncio.create_task(anext(self.subscription))
            try:
                value = await asyncio.wait_for(
                    self._read, min(remaining, self.heartbeat)
                )
                event = _event(value)
            except TimeoutError:
                event = None
            if asyncio.get_running_loop().time() >= self.deadline:
                await self.aclose()
                raise StopAsyncIteration
            actual = await self.fresh(self.access.session_key)
            if self.closed or asyncio.get_running_loop().time() >= self.deadline:
                await self.aclose()
                raise StopAsyncIteration
            if not same_identity(self.access.identity, actual):
                await self.aclose()
                return {"event": "auth-required", "data": {"version": 1}}
            if event is not None and event["event"] == "auth-required":
                await self.aclose()
            return event
        except asyncio.CancelledError:
            await self.aclose()
            raise
        except StopAsyncIteration:
            await self.aclose()
            raise
        except Exception:
            logger.warning("realtime-stream-failed")
            await self.aclose()
            raise StopAsyncIteration from None

    async def _finish(self) -> None:
        try:
            if self._read is not None and not self._read.done():
                self._read.cancel()
                await asyncio.gather(self._read, return_exceptions=True)
            await asyncio.wait_for(self.subscription.aclose(), BROKER_TIMEOUT)
        except Exception:
            logger.warning("realtime-cleanup-failed")
        finally:
            self.admission.release()

    async def aclose(self) -> None:
        """Release owned resources once, including never-iterated responses."""
        self.closed = True
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(self._finish())
        await asyncio.shield(self._cleanup)


async def open_stream(
    access: Access,
    broker: Broker,
    *,
    admissions: Admissions = admissions,
    fresh: Callable[[str], Awaitable[Identity | None]] = fresh_identity_async,
    heartbeat: float = HEARTBEAT,
    lifetime: float = LIFETIME,
) -> OwnedStream:
    """Acquire ACKed broker ownership then recheck auth before response creation.

    Args:
        access: Already verified actual-cookie authority.
        broker: Package broker whose subscribe waits for all topic ACKs.
        admissions: Worker capacity owner.
        fresh: Fresh session resolver; injectable only for controller tests.
        heartbeat: Comment interval in seconds.
        lifetime: Finite connection lifetime in seconds.

    Returns:
        Owned iterator with an explicit idempotent cleanup callback.

    Raises:
        RealtimeDenied: On exhaustion, broker failure or preheader auth loss.
    """
    admission = admissions.acquire(access.identity)
    stream = None
    try:
        subscription = await asyncio.wait_for(
            broker.subscribe(topics_for(access.identity)), BROKER_TIMEOUT
        )
        stream = OwnedStream(
            access, subscription, admission, fresh, heartbeat, lifetime
        )
        actual = await fresh(access.session_key)
        if actual is None:
            raise RealtimeDenied(401)
        if not same_identity(access.identity, actual):
            raise RealtimeDenied(403)
        return stream
    except BaseException as error:
        if stream is not None:
            await stream.aclose()
        else:
            admission.release()
        if isinstance(error, (RealtimeDenied, asyncio.CancelledError)):
            raise
        logger.warning("realtime-subscription-failed")
        raise RealtimeDenied(503) from None
