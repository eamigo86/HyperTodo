# Generation-owned SSE transport

Normal App now wires the parser and connection controller through the explicit
`expo/fetch` export. It opens one connection only after authenticated session
confirmation and the first real focused Root layout. This integration has real
App/public-SDK JS tests and a **limited native SSE demo accepted on 2026-09-10
(UTC)**: normal DefaultApp in disposable iOS26.5 Simulator / Expo Go57.0.9.
An actual Admin rename appeared automatically on authenticated A's Tasks page1,
without an injected hint, manual reload, navigation or other client interaction.
One OS background/foreground cycle preserved that screen without reauthentication;
the owned Redis subscriber count changed 1 → 0 → 1.

Run `8fedb272794b44ccaa57c8a3e25d0523` has before/after screenshots and separate
Admin/CSRF and subscriber evidence in
`evidence/environment/sse-demo-8fedb272794b44ccaa57c8a3e25d0523/` and
`evidence/environment/sse-demo-backend-retry-20260910/`. This is not an Android,
physical-iPhone, concurrent-B-client or exhaustive native transport claim.

`AppSessionOptions.stream = {fetch, clock?}` is internal dependency injection,
not a user feature flag. Historical isolated fixtures without that port do not
open SSE. A native SSE fixture must explicitly supply the same `expo/fetch`
transport; a fixture's earlier HTTP-only acceptance is not SSE evidence.

## Connection ownership

`createEventStream({origin, fetch, clock?})` returns `setOwner(owner | null)` and
`dispose()`. App must inject **the explicit `expo/fetch` export**; a different
fetch implementation is used only by controlled tests. The optional clock has
`now(): number`, `schedule(callback, milliseconds): cancel` and `random(): number`.
It is an internal test seam, not a user setting.

An immutable `StreamOwner` captures `generation`, `binding`, `isCurrent`,
`receive(resources, cause)` and `onAuthRequired`. `isCurrent()` must check the
authenticated identity, exact generation, foreground and real Root readiness.
A resource receiver alone is not proof of authentication. The controller copies
the owner and checks its authority again after every awaited fetch/read.

Keep the same owner object while that authority is unchanged. An initial resync,
resource reload, layout ACK or theme update must not create another owner and
reopen the connection. Pass `null` on pause, auth admission, logout, account
change or disposal; a stale response cannot notify a newer owner.

App creates that owner in `onIdentity`. Session `rootReady` is sticky for that
identity: ordinary HTTP reloads, hints and theme updates do not clear it. Pause
retires the connection, not the Root/draft; confirmed foreground reactivates the
same owner's authority. Auth admission, account transition, uncertainty and
disposal synchronously retire it. A current stream auth refusal calls the
existing supervisor invalidation path without clearing stored credentials or
replaying an auth POST. The legacy snapshot field `resources: "connected"`
describes the existing resource dispatch seam, **not live SSE connection state**.

## Closed wire and HTTP boundary

Only `GET /realtime/events/` at the configured HTTP(S) origin is allowed, with
`credentials: include`, `redirect: error`, no-store, `Accept: text/event-stream`,
`X-HyperTodo-Client-Contract: realtime-v1` and the captured
`X-HyperTodo-Expected-Session`. This binding is not a bearer credential. A 200
response must have the exact endpoint URL, the captured `X-HyperTodo-Session-Binding`,
and `Content-Type: text/event-stream` before its body is read.

| SSE event | Exact JSON fields |
| --- | --- |
| `invalidate` | `{"version":1,"resources":["tasks"]}` |
| `resync` | `{"version":1}` |
| `auth-required` | `{"version":1}` |

Resources are a nonempty ordered subset of `tasks`, `categories`, `ui`: the same
seven combinations accepted by boundary metadata. No extra fields, duplicate
resources, `id`, `retry`, URLs, topics, identities or markup are accepted.
Heartbeat comments never invalidate resources. Resync passes all three resources
with cause `resync`; it asks to reconcile current HTTP state, not assert a change.

`captureResources()` and the published captured receiver accept an optional
second argument `"invalidate" | "resync"` (default `"invalidate"`). Both use the
same dependency filtering, canonical page1 document reload and real layout ACK.
Forms and multipage lists retain persistent translated notices and drafts until
deliberate Update. Separate per-resource change/reconciliation versions prevent
a later resync from hiding a still-pending invalidation. The matching layout ACK
only covers the versions captured when its HTTP request was admitted; later
hints remain pending. Once that change has been acknowledged, a remaining
resync uses the neutral reconciliation copy rather than claiming another change.

The incremental decoder handles LF/CRLF/CR, split UTF-8 and a leading BOM. It
rejects malformed UTF-8, JSON over 4096 UTF-8 bytes and a pending SSE frame over
8192 encoded bytes. A large native chunk is processed incrementally; the limits
are protocol bounds, not a claim about total native allocation. EOF does not
fabricate an event. Neither fetch, parsing nor timers can acknowledge XML layout.

## Failure and cleanup

- A current 401/403 or `auth-required` closes the stream and calls only the
  captured owner's auth callback. It does not clear credentials or send logout.
- Network, body, protocol or response-boundary failures close the stream and
  retry with exponential backoff and jitter bounded to 1–30 seconds. Only a
  valid resync resets backoff. Ordinary HTTP, drafts and admitted POSTs remain
  outside this controller.
- The 45-second activity watchdog covers stalled response headers and reads.
  Bytes reset that watchdog; no heartbeat can extend the 60-second connection
  lifetime. Reconnection after renewal uses the same bounded backoff.
- 404 means disabled for this activation: no retry until `null` then a new owner
  activation. Repeating `setOwner` with the same object is a no-op.
- Closing aborts the request, cancels the reader and owned timers, and releases
  the reader lock. Late settlement after abort cannot regain authority.

## Verification and remaining scope

Permanent tests cover closed fields, all resource combinations, one-byte UTF-8
and CRLF fragmentation, byte limits, immutable delivery, stale owners, fixed
metadata, response rejection, auth outcomes, disabled endpoint, backoff,
watchdog, renewal and disposal. They use genuine controlled Response/stream
objects and an injected clock; this is **JS evidence, not native network proof**.

Expo 57's installed `winter/runtime.native.ts` installs its TextDecoder, whose
fatal and BOM semantics are exercised by a compatibility control against that
actual installed implementation. The production parser uses the public global,
not an SDK-private import. Previous native I/O already exercised getReader and
abort, but did not test malformed UTF-8 or this controller.

Actual App tests additionally exercise resync → held HTTP → public layout without
another connection; pending change/resync ordering and version ACKs; preserved
filters, page1/manual notices and drafts; real logout/B transition; stale A401 and
an already-settling A read; background confirmation; current auth refusal and
404/network failure with ordinary HTTP still usable. Native seams are explicit
test shims, not evidence of physical transport.

The native demo used the real backend publisher/broker and normal Admin HTTP/CSRF
save on a disposable synthetic database. Deployment and broader native fault
coverage remain separate from this bounded acceptance. No native SDK or original
checkout was changed, and the historical unscoped `gate.invalidate()` is not wired
as a production fallback.
