# Disposable normal-App SSE demo

> Current portable installed-package commands and provenance are described in
> [installed adoption](installed-adoption.md). Machine-specific paths below are
> historical evidence, not defaults required to run HyperTodo.

**Use a fresh fixture and the real HyperTodo App/Admin, not the Gate0 toolbar.**
This launcher prepares source-level software checks; it does not certify native
SSE delivery by itself. A limited recorded native run is summarized below.
Do not start LAN/DNS/Metro or a simulator until the coordinating
review has accepted the package, backend and mobile freezes.

## Prepare and run

Use the verified existing Python3.14/Django6.1.1 interpreter with `-B` and the
candidate package source plus its pyproject-derived source METADATA fixture in
`PYTHONPATH`. This is not an installation or deployable artifact. Run from this
isolated backend only; the launcher checks provenance before allocating a DB.

```sh
python -B -m test_support.sse_demo --check-only \
  --parent /private/tmp/djhv-sse-20260908/runtime-private/demo-check \
  --report /private/tmp/djhv-sse-20260908/evidence/environment/demo-check.json
```

For the later coordinated run, omit `--check-only`, supply `--seconds 600`,
`--bind <exact-private-IPv4>` and `--port <owned-unprivileged-port>` (placeholders
must be replaced). Default binding is loopback, port8788; no wildcard or fallback.
`--paginated` is optional: default is2 tasks per owner; explicit paginated mode
creates22 tasks for A and2 for B. No `seed_demo` or live database is used.

The closed `demo-prepared` stdout record supplies only `run` and `apiOrigin`.
It is not a readiness or DNS assertion: verify the served payload separately.
The independently owned mobile launcher takes that origin and sets only
`extra.apiUrl = apiOrigin + '/hv/'` in the normal DefaultApp entry. Its Metro host
must be a different fresh `hvtm-<run>.local` hostname. Ports do not isolate cookies.
No credential, binding, database path or secret belongs in a bundle or QR.

## Isolation and lifetime

- New0700 `native-app-*` directory,0600 SQLite/config/credentials, fictional A/B/admin.
  Existing migrations apply only to this new SQLite. Read synthetic credentials
  through a separate private host-side channel, never stdout/public reports.
- Only allowlisted `test_support.sse_demo_settings` enables the fixed loopback
  Redis14 endpoint and unique `hypertodo-demo-<run>` namespace. Ordinary fixture
  settings explicitly force realtime off. Seeding temporarily disables hints.
  Redis database numbers do not isolate PubSub; the unique namespace does.
- Fresh `hvt-<run>.local`, unique session/CSRF/language names, no cookie domains.
  The boundary whitelists only those names before Django, rejects other Hosts and
  off-origin redirects, and filters unrelated outgoing cookies. It does not read,
  clear or assert emptiness of a user's shared cookie jar.
- Ordinary body/response budgets remain10s/15s. Only an exact query-free GET
  `/realtime/events/` whose real app returns200 `text/event-stream` gets70s after
  its response headers. Authentication and fresh-session checks remain in the
  actual endpoint; the preheader budget stays15s, and per-stream renewal remains60s.
- Reuse the finite existing Uvicorn asyncio/h11 runner with read-only append-last
  dependency provenance: the isolated verification reuses existing Uvicorn 0.34.0
  and h11 0.14.0 via read-only append-last imports. This is not a normal supported
  installation recipe or a dependency/pin change. Server lifetime is at most600s,
  one worker, no websockets,
  access logs, build, install or collectstatic. No report collector or mutation API.
- Normal stop/error closes owned server resources and Django connections, then
  removes only the validated private fixture tree. No Redis flush or global cleanup.
  Final sanitized report distinguishes fixture checks from native acceptance.

## Verification boundary

`tests/test_sse_demo_fixture.py` covers fail-closed settings/lifetime, real new-DB
initialization with network denied, private credential modes and cleanup, public
handoff fields, factory wiring and exact timeout selection. Deadline-selection
controls inject only the fixture clock; they are not Django/native transport proof.
Existing ordinary fixture, cookie, redirect, finite-loopback and collector tests
remain unchanged. Real Redis/Admin/ASGI acceptance lives in
`tests/test_realtime_redis.py`; native observation is separate from these checks.

## Recorded limited native example

The isolated run `8fedb272794b44ccaa57c8a3e25d0523` passed one normal-App example
on a disposable iOS simulator. Root observed A task2 change from
`Fictional owner_a task 2` to `SSE renamed from Admin` after one genuine Admin
HTTP/CSRF save, without manual navigation, refresh or injected hints. A subsequent
OS background/foreground cycle retained the updated Tasks screen; the own-topic
subscriber count went1→0→1. The server then stopped, count returned0, and private
SQLite/credentials were removed. No executable source changed for the run.

Local execution report: [limited native proof](../../../evidence/environment/sse-demo-backend-retry-20260910/report.md).
This worktree-only evidence link is not a published artifact or a promise that the
example is still running. It does not claim Android native SSE, every race or a
production deployment; the full automated gates remain separate evidence.
