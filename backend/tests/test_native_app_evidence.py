"""Bounded wire evidence, not a native acceptance authority."""

import asyncio
import importlib
import json
from pathlib import Path

import pytest

from tests.test_native_app_fixture import fixture_module

VECTORS = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "mobile/test-support/native-app/report-vectors.json"
    ).read_text()
)
RUN = VECTORS["run"]


def module():
    return importlib.import_module("test_support.native_app_evidence")


def record(**updates):
    return {**VECTORS["valid"][0], **updates}


@pytest.mark.parametrize("value", VECTORS["valid"])
def test_shared_positive_wire_vectors(value):
    assert dict(module().validate_record(value, RUN, 1)) == value


@pytest.mark.parametrize("value", VECTORS["invalid"])
def test_shared_negative_wire_vectors(value):
    with pytest.raises(ValueError, match="invalid-record"):
        module().validate_record(value, RUN, 1)


def test_backend_literal_enums_match_contract_without_runtime_mobile_imports():
    assert set(module().TERMINAL_REASONS) == set(VECTORS["terminalReasons"])
    assert set(module().DIAGNOSTICS) == set(VECTORS["diagnostics"])


@pytest.mark.parametrize("payload", [b"\xff", b"{}" * 1025, b'{"v":1,"v":1}', b"[]"])
def test_raw_invalid_records_are_not_decoded_or_logged(payload):
    with pytest.raises(ValueError, match="invalid-record"):
        module().validate_record(payload, RUN, 1)


@pytest.mark.parametrize(
    "change",
    [
        {"v": True},
        {"route": True},
        {"route": []},
        {"operation": "gate-1-1-" + "9" * 80},
        {"reason": {"cookie": "private"}},
        {"platform": "web"},
    ],
)
def test_wire_scalar_types_are_strict(change):
    with pytest.raises(ValueError, match="invalid-record"):
        module().validate_record(record(**change), RUN, 1)


def test_collector_rejects_conflicting_sequence_and_stops_after_failure(tmp_path):
    path = tmp_path / "events.jsonl"
    collector = module().EvidenceCollector(RUN, path)
    collector.record(json.dumps(record()).encode())
    with pytest.raises(ValueError):
        collector.record(json.dumps(record(route=2)).encode())
    with pytest.raises(ValueError):
        collector.record(
            json.dumps(record(sequence=2, kind="complete", route=None)).encode()
        )
    assert collector.snapshot() == {
        "state": "inconclusive",
        "reason": "invalid-record",
        "records": 1,
    }
    collector.close()
    saved = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row["sequence"] for row in saved] == [1]
    assert (
        json.loads(Path(str(path) + ".status.json").read_text())["state"]
        == "inconclusive"
    )


def test_complete_is_upload_only_and_incomplete_close_is_not_recorded(tmp_path):
    collector = module().EvidenceCollector(RUN, tmp_path / "complete.jsonl")
    collector.record(json.dumps(record(kind="complete", route=None)).encode())
    assert collector.snapshot()["state"] == "recorded"
    assert "passed" not in collector.snapshot()
    collector.close()
    incomplete = module().EvidenceCollector(RUN, tmp_path / "incomplete.jsonl")
    incomplete.close()
    assert incomplete.snapshot()["state"] == "inconclusive"


def test_record_capacity_never_truncates_to_success(tmp_path):
    collector = module().EvidenceCollector(RUN, tmp_path / "bounded.jsonl")
    for sequence in range(1, 501):
        collector.record(json.dumps(record(sequence=sequence)).encode())
    with pytest.raises(ValueError):
        collector.record(
            json.dumps(record(sequence=501, kind="complete", route=None)).encode()
        )
    assert collector.snapshot() == {
        "state": "inconclusive",
        "reason": "overflow",
        "records": 500,
    }
    collector.close()


def test_evidence_path_must_be_new_and_scoped(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text("existing")
    with pytest.raises((ValueError, FileExistsError)):
        module().EvidenceCollector(RUN, path)
    assert path.read_text() == "existing"
    with pytest.raises(ValueError):
        module().EvidenceCollector(RUN, Path("/outside-fixture/events.jsonl"))


async def upload(
    fixture,
    collector,
    *,
    payload=b"{}",
    host=None,
    method="POST",
    query=b"",
    events=None,
    content_type=b"application/json",
    lose_response=False,
):
    from test_support.native_app_boundary import NativeAppBoundary

    async def forbidden(*args):
        pytest.fail("report must not reach Django/business app")

    app = NativeAppBoundary(forbidden, fixture, evidence=collector, body_timeout=0.01)
    queue = asyncio.Queue()
    for event in events or [{"type": "http.request", "body": payload}]:
        queue.put_nowait(event)
    sent = []

    async def send(event):
        if lose_response and event["type"] == "http.response.start":
            raise OSError("synthetic response lost after acceptance")
        sent.append(event)

    await app(
        {
            "type": "http",
            "method": method,
            "path": "/__native__/report/",
            "query_string": query,
            "server": ("127.0.0.1", 8788),
            "headers": [
                (b"host", host or fixture.host.encode()),
                (b"content-type", content_type),
                (b"cookie", b"theme=unrelated-private"),
            ],
        },
        queue.get,
        send,
    )
    return sent


def test_report_endpoint_is_inactive_by_default_and_accepts_only_its_run(tmp_path):
    fixture = fixture_module().create_fixture(tmp_path)
    assert asyncio.run(upload(fixture, None))[0]["status"] == 404
    collector = module().EvidenceCollector(fixture.run_id, tmp_path / "events.jsonl")
    response = asyncio.run(
        upload(
            fixture, collector, payload=json.dumps(record(run=fixture.run_id)).encode()
        )
    )
    assert response[0]["status"] == 204
    assert collector.snapshot()["records"] == 1
    collector.close()


@pytest.mark.parametrize(
    "change,status",
    [
        ({"host": b"original.example"}, 400),
        ({"method": "GET"}, 405),
        ({"query": b"anything=1"}, 400),
        ({"payload": b"x" * 2049}, 413),
        ({"content_type": b"text/plain"}, 400),
        ({"events": [{"type": "http.request", "body": b"{", "more_body": True}]}, 408),
    ],
)
def test_report_endpoint_keeps_host_method_body_and_deadline_guards(
    tmp_path, change, status
):
    fixture = fixture_module().create_fixture(tmp_path)
    collector = module().EvidenceCollector(fixture.run_id, tmp_path / "events.jsonl")
    response = asyncio.run(upload(fixture, collector, **change))
    assert response[0]["status"] == status
    assert collector.snapshot()["records"] == 0
    collector.close()
    assert collector.snapshot()["state"] == "inconclusive"


def test_status_write_failure_cannot_leave_recorded_or_leak_handles(
    tmp_path, monkeypatch
):
    collector = module().EvidenceCollector(RUN, tmp_path / "write.jsonl")
    status = collector._status

    def broken_flush():
        raise OSError("synthetic status failure")

    monkeypatch.setattr(status, "flush", broken_flush)
    with pytest.raises(ValueError, match="report-failed"):
        collector.record(json.dumps(record(kind="complete", route=None)).encode())
    assert collector.snapshot()["state"] == "inconclusive"
    monkeypatch.undo()
    collector.close()
    assert collector._stream.closed and status.closed


def test_initial_status_failure_closes_both_owned_files(tmp_path, monkeypatch):
    import builtins

    streams = []
    original = builtins.open

    def track(*args, **kwargs):
        stream = original(*args, **kwargs)
        streams.append(stream)
        return stream

    def fail(self):
        raise ValueError("report-failed")

    monkeypatch.setattr(builtins, "open", track)
    monkeypatch.setattr(module().EvidenceCollector, "_persist_status", fail)
    with pytest.raises(ValueError, match="report-failed"):
        module().EvidenceCollector(RUN, tmp_path / "setup.jsonl")
    assert len(streams) == 2 and all(stream.closed for stream in streams)


def test_cleanup_failure_overrides_completed_upload(tmp_path):
    collector = module().EvidenceCollector(RUN, tmp_path / "cleanup.jsonl")
    collector.record(json.dumps(record(kind="complete", route=None)).encode())
    collector.close(cleanup_ok=False)
    assert collector.snapshot() == {
        "state": "inconclusive",
        "reason": "cleanup-failed",
        "records": 1,
    }


def test_stream_close_failure_still_finalizes_status_as_inconclusive(
    tmp_path, monkeypatch
):
    path = tmp_path / "closing.jsonl"
    collector = module().EvidenceCollector(RUN, path)
    collector.record(json.dumps(record(kind="complete", route=None)).encode())
    real_close = collector._stream.close

    def fail_close():
        real_close()
        raise OSError("synthetic close failure")

    monkeypatch.setattr(collector._stream, "close", fail_close)
    with pytest.raises(OSError, match="synthetic close failure"):
        collector.close()
    assert collector._status.closed and collector._closed
    assert collector.snapshot()["state"] == "inconclusive"
    assert (
        json.loads(Path(str(path) + ".status.json").read_text())["reason"]
        == "cleanup-failed"
    )


def test_first_rejection_is_persisted_immediately_and_retained_after_close(tmp_path):
    path = tmp_path / "first-rejection.jsonl"
    collector = module().EvidenceCollector(RUN, path)
    status_path = Path(str(path) + ".status.json")
    try:
        collector.record(json.dumps(record()).encode())
        collector.reject("invalid-record")
        expected = {"state": "inconclusive", "reason": "invalid-record", "records": 1}
        assert json.loads(status_path.read_text()) == expected
        collector.reject("report-failed")
        assert json.loads(status_path.read_text()) == expected
        collector.close()
        assert json.loads(status_path.read_text()) == expected
        assert len(path.read_text().splitlines()) == 1
    finally:
        collector.close()


def test_rejection_status_failure_is_finite_and_preserves_first_reason(
    tmp_path, monkeypatch
):
    collector = module().EvidenceCollector(RUN, tmp_path / "failed-rejection.jsonl")
    calls = 0

    def broken_flush():
        nonlocal calls
        calls += 1
        raise OSError("synthetic write failure")

    monkeypatch.setattr(collector._status, "flush", broken_flush)
    try:
        with pytest.raises(ValueError, match="report-failed"):
            collector.reject("invalid-record")
        assert calls == 1
        assert collector.snapshot() == {
            "state": "inconclusive",
            "reason": "invalid-record",
            "records": 0,
        }
    finally:
        monkeypatch.undo()
        collector.close()
    assert collector._stream.closed and collector._status.closed


def test_close_status_failure_still_closes_both_handles(tmp_path, monkeypatch):
    collector = module().EvidenceCollector(RUN, tmp_path / "close-status.jsonl")

    def broken_flush():
        raise OSError("synthetic status failure")

    monkeypatch.setattr(collector._status, "flush", broken_flush)
    with pytest.raises((ValueError, OSError)):
        collector.close()
    assert collector._closed and collector._stream.closed and collector._status.closed


@pytest.mark.parametrize("kind,route", [("ready", 1), ("complete", None)])
def test_lost_ack_retries_exact_last_record_without_appending(tmp_path, kind, route):
    from test_support.native_app_fixture import NativeFixture

    fixture = NativeFixture(tmp_path / "unused", RUN, "unused")
    path = tmp_path / "retry-last.jsonl"
    collector = module().EvidenceCollector(RUN, path)
    body = json.dumps(record(kind=kind, route=route)).encode()
    try:
        with pytest.raises(OSError, match="synthetic response lost"):
            asyncio.run(upload(fixture, collector, payload=body, lose_response=True))
        before = collector.snapshot()
        persisted = path.read_bytes()
        response = asyncio.run(upload(fixture, collector, payload=body))
        assert response[0]["status"] == 204
        assert response[1]["body"] == b""
        assert collector.snapshot() == before
        assert path.read_bytes() == persisted
        assert before["records"] == 1
    finally:
        collector.close()


def test_duplicate_is_compared_as_validated_closed_fields(tmp_path):
    collector = module().EvidenceCollector(RUN, tmp_path / "canonical.jsonl")
    first = record()
    try:
        collector.record(json.dumps(first).encode())
        reordered = dict(reversed(list(first.items())))
        collector.record(json.dumps(reordered, separators=(",", ":")).encode())
        assert collector.snapshot() == {
            "state": "recording",
            "reason": None,
            "records": 1,
        }
    finally:
        collector.close()


@pytest.mark.parametrize(
    "change",
    [
        {"route": 2},
        {"run": "0" * 32},
        {"extra": "not-allowed"},
        {"sequence": True},
        {"route": True},
        {"platform": "web"},
    ],
)
def test_changed_or_invalid_last_record_never_gets_duplicate_ack(tmp_path, change):
    collector = module().EvidenceCollector(RUN, tmp_path / "invalid-duplicate.jsonl")
    try:
        collector.record(json.dumps(record()).encode())
        with pytest.raises(ValueError):
            collector.record(json.dumps(record(**change)).encode())
        assert collector.snapshot() == {
            "state": "inconclusive",
            "reason": "invalid-record",
            "records": 1,
        }
        with pytest.raises(ValueError):
            collector.record(json.dumps(record()).encode())
        assert collector.snapshot()["records"] == 1
    finally:
        collector.close()


def test_older_accepted_record_is_not_a_replay_history(tmp_path):
    collector = module().EvidenceCollector(RUN, tmp_path / "older.jsonl")
    try:
        collector.record(json.dumps(record()).encode())
        collector.record(json.dumps(record(sequence=2)).encode())
        with pytest.raises(ValueError):
            collector.record(json.dumps(record()).encode())
        assert collector.snapshot()["records"] == 2
    finally:
        collector.close()


def test_duplicate_complete_does_not_reopen_or_clear_a_later_failure(tmp_path):
    collector = module().EvidenceCollector(RUN, tmp_path / "complete-retry.jsonl")
    complete = json.dumps(record(kind="complete", route=None)).encode()
    try:
        collector.record(complete)
        collector.record(complete)
        assert collector.snapshot() == {
            "state": "recorded",
            "reason": None,
            "records": 1,
        }
        with pytest.raises(ValueError):
            collector.record(json.dumps(record(sequence=2)).encode())
        with pytest.raises(ValueError):
            collector.record(complete)
        assert collector.snapshot() == {
            "state": "inconclusive",
            "reason": "invalid-record",
            "records": 1,
        }
    finally:
        collector.close()


def test_record500_duplicate_does_not_consume_capacity_or_bypass_body_bound(tmp_path):
    collector = module().EvidenceCollector(RUN, tmp_path / "capacity-retry.jsonl")
    try:
        for sequence in range(1, 501):
            collector.record(json.dumps(record(sequence=sequence)).encode())
        last = json.dumps(record(sequence=500)).encode()
        collector.record(last)
        assert collector.snapshot() == {
            "state": "recording",
            "reason": None,
            "records": 500,
        }
        with pytest.raises(ValueError):
            collector.record(last + b" " * 2048)
        assert collector.snapshot()["records"] == 500
    finally:
        collector.close()
