"""Independent bounded wire-v1 collector; never a native acceptance authority."""

import json
import os
import re
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .native_app_fixture import report_root

REPORT_PATH = "/__native__/report/"
KEYS = frozenset(
    {
        "v",
        "run",
        "sequence",
        "platform",
        "case",
        "kind",
        "operation",
        "route",
        "outcome",
        "reason",
    }
)
CASES = frozenset(
    {
        "startup",
        "auth",
        "resources",
        "form",
        "append-race",
        "post-race",
        "lifecycle",
        "refusal",
        "cleanup",
    }
)
KINDS = frozenset(
    {
        "ready",
        "terminal",
        "http-get",
        "http-post",
        "http-response",
        "held",
        "released",
        "hint",
        "paused",
        "foreground",
        "diagnostic",
        "cleanup",
        "complete",
        "inconclusive",
    }
)
OUTCOMES = frozenset({"ack", "no-document", "error", "cancelled", "dropped"})
TERMINAL_REASONS = frozenset(
    {
        "owner-unavailable",
        "sync-drop",
        "sync-replaced",
        "sdk-on-end",
        "once",
        "missing-target",
        "removed-delayed-origin",
        "missing-local-source",
        "parser-no-op",
        "empty-response",
        "request-error",
        "local-layout",
        "remote-layout",
        "caller-error",
        "uncorrelated-result",
        "reload-layout",
        "unsupported-document",
        "navigation-changed",
        "navigation-no-op",
        "missing-destination",
        "auth-transition",
        "auth-panel-layout",
        "auth-refused",
        "auth-busy",
        "auth-uncertain",
    }
)
DIAGNOSTICS = frozenset(
    {
        "sdk-error",
        "request-failed",
        "hold-timeout",
        "report-failed",
        "overflow",
        "invalid-record",
        "cleanup-failed",
    }
)
LAYOUT = frozenset(
    {"local-layout", "remote-layout", "reload-layout", "auth-panel-layout"}
)
HTTP_KINDS = frozenset({"http-get", "http-post", "http-response", "held", "released"})
RUN = re.compile(r"[a-f0-9]{32}")
OPERATION = re.compile(r"gate-(?:0|[1-9][0-9]*)-(?:0|[1-9][0-9]*)-(?:0|[1-9][0-9]*)")


def _integer(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("invalid-record")
    return value


def validate_record(payload: bytes | dict, run: str, sequence: int) -> MappingProxyType:
    """Validate exact scalar keys/enums; return a detached immutable projection."""
    try:
        if isinstance(payload, bytes):
            if len(payload) > 2048:
                raise ValueError
            value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique)
        else:
            value = payload
        if (
            not isinstance(value, dict)
            or set(value) != KEYS
            or len(json.dumps(value).encode()) > 2048
        ):
            raise ValueError
        if (
            not isinstance(run, str)
            or RUN.fullmatch(run) is None
            or value["run"] != run
        ):
            raise ValueError
        if (
            not _integer(value["v"], 1, 1)
            or not _integer(sequence, 1, 500)
            or not _integer(value["sequence"], sequence, sequence)
        ):
            raise ValueError
        if (
            value["platform"] not in {"ios", "android"}
            or value["case"] not in CASES
            or value["kind"] not in KINDS
        ):
            raise ValueError
        operation, route, outcome, reason, kind = (
            value[k] for k in ("operation", "route", "outcome", "reason", "kind")
        )
        if operation is not None and (
            not isinstance(operation, str)
            or len(operation) > 80
            or OPERATION.fullmatch(operation) is None
        ):
            raise ValueError
        if route is not None and not _integer(route, 1, 256):
            raise ValueError
        if outcome is not None and outcome not in OUTCOMES:
            raise ValueError
        if kind == "ready":
            if (
                route is None
                or operation is not None
                or outcome is not None
                or reason is not None
            ):
                raise ValueError
        elif kind == "terminal":
            if (
                route is None
                or outcome is None
                or reason not in TERMINAL_REASONS
                or (outcome == "ack" and reason not in LAYOUT)
            ):
                raise ValueError
        else:
            if route is not None or outcome is not None:
                raise ValueError
            if kind in HTTP_KINDS:
                if reason is not None:
                    raise ValueError
            elif operation is not None:
                raise ValueError
            if kind in {"diagnostic", "inconclusive"}:
                if reason not in DIAGNOSTICS:
                    raise ValueError
            elif reason is not None:
                raise ValueError
        return MappingProxyType(dict(value))
    except ValueError, TypeError, UnicodeError, RecursionError:
        raise ValueError("invalid-record") from None


class EvidenceCollector:
    """Persist at most500 sanitized records and a sticky inconclusive status."""

    def __init__(self, run: str, path: Path) -> None:
        """Create only new explicit evidence files; never overwrite prior proof."""
        self.run = run
        if not isinstance(run, str) or RUN.fullmatch(run) is None:
            raise ValueError("invalid-record")
        path = path.absolute()
        status = Path(str(path) + ".status.json")
        for candidate in (path, status):
            if (
                not candidate.is_relative_to(report_root())
                or candidate.resolve() != candidate
                or candidate.exists()
            ):
                raise ValueError("new isolated evidence path required")
        self._state, self._reason, self._count = "recording", None, 0
        self._last: MappingProxyType | None = None
        self._closed = False
        self._stream = open(path, "x", opener=lambda p, f: os.open(p, f, 0o600))
        try:
            self._status = open(status, "x", opener=lambda p, f: os.open(p, f, 0o600))
        except BaseException:
            self._stream.close()
            raise
        try:
            self._persist_status()
        except BaseException:
            self._stream.close()
            self._status.close()
            self._closed = True
            raise

    def snapshot(self) -> dict[str, object]:
        """Return upload status only, without native PASS or any session authority."""
        return {"state": self._state, "reason": self._reason, "records": self._count}

    def reject(self, reason: str) -> None:
        """Make bounded schema/upload/cleanup failures sticky without raw logging."""
        if reason not in DIAGNOSTICS:
            raise ValueError("invalid-record")
        self._state = "inconclusive"
        self._reason = self._reason or reason
        if not self._closed:
            self._persist_status()

    def record(self, payload: bytes) -> None:
        """Append the next record, or acknowledge only the exact valid last record."""
        if self._closed or self._state == "inconclusive":
            self.reject("invalid-record")
            raise ValueError("invalid-record")
        try:
            repeated = validate_record(payload, self.run, self._count)
        except ValueError:
            repeated = None
        if repeated is not None:
            if repeated == self._last:
                return
            self.reject("invalid-record")
            raise ValueError("invalid-record")
        if self._count >= 500:
            self.reject("overflow")
            raise ValueError("overflow")
        if self._state == "recorded":
            self.reject("invalid-record")
            raise ValueError("invalid-record")
        try:
            value = validate_record(payload, self.run, self._count + 1)
        except ValueError:
            self.reject("invalid-record")
            raise
        try:
            self._stream.write(json.dumps(dict(value), separators=(",", ":")) + "\n")
            self._stream.flush()
        except OSError:
            self.reject("report-failed")
            raise ValueError("report-failed") from None
        self._count += 1
        self._last = value
        if value["kind"] == "inconclusive":
            self.reject(value["reason"])
        elif value["kind"] == "complete" and self._state != "inconclusive":
            self._state = "recorded"
        self._persist_status()

    def _persist_status(self) -> None:
        try:
            self._status.seek(0)
            self._status.truncate()
            json.dump(self.snapshot(), self._status)
            self._status.flush()
        except OSError:
            # A status I/O failure cannot recursively attempt the same write.
            self._state = "inconclusive"
            self._reason = self._reason or "report-failed"
            raise ValueError("report-failed") from None

    def close(self, *, cleanup_ok: bool = True) -> None:
        """Finalize status; missing complete or failed cleanup stays inconclusive."""
        if self._closed:
            return
        try:
            if not cleanup_ok:
                self.reject("cleanup-failed")
            elif self._state != "recorded":
                self.reject("report-failed")
            self._persist_status()
        finally:
            try:
                try:
                    self._stream.close()
                except OSError:
                    self.reject("cleanup-failed")
                    self._persist_status()
                    raise
            finally:
                try:
                    self._status.close()
                finally:
                    self._closed = True
