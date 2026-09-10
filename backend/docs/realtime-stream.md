# Cookie-authenticated realtime stream

**The app endpoint owns authentication and topic selection.** The public package
broker provides Redis subscription and publication. Controlled broker ports in
unit tests are not proof of working Redis or a native SSE demo; those have their
own integration evidence.

## Enable and serve

Keep `HYPERVIEW["REALTIME"] = None` or omit the section for rollback: the endpoint
returns 404 and normal HTTP/HXML remains available. To enable, preserve the rest
of `HYPERVIEW` and set its central section:

```python
HYPERVIEW["REALTIME"] = {
    "REDIS_URL": "redis://127.0.0.1:6379/14",
    "NAMESPACE": "hypertodo-dev",
}
```

Delete the old top-level `HYPERTODO_REALTIME` setting, even if it was `None`;
HyperTodo rejects its presence rather than keeping two sources of truth. The
package validates transport settings once and exposes `get_settings().realtime`.
There is no cache-alias adapter; Redis PubSub isolation requires the namespace.
HyperTodo requires `django.contrib.sessions.backends.db` while enabled, so real
session deletion is observable; this does not claim that signed-cookie sessions
can be revoked server-side. No new session setting or migration is introduced.

Serve the ASGI application in `config/asgi.py`. It composes the public package
`realtime_asgi(get_asgi_application())` wrapper once. This owns cleanup for the
**actual HTTP request**, including sync/async middleware adaptation; completing
an adapted view task must not close a response before its first frame. WSGI is
not an SSE deployment path. None of this disables mandatory XSD validation for
ordinary Hyperview documents/fragments.

## Request and response contract

Exact route: **GET `/realtime/events/`**, with no query string. Require the actual
Django session cookie plus `X-HyperTodo-Client-Contract: realtime-v1` and the
previously confirmed `X-HyperTodo-Expected-Session`. The binding is not a bearer
credential. Native requests may omit Origin; a supplied Origin must match the
request's scheme/host/effective port, with no path, credentials, query or fragment.
There are no redirects, CORS reflection or client-selected topics.

| Condition before headers | Status |
|---|---:|
| Disabled | 404 |
| Enabled but method is not GET | 405, `Allow: GET` |
| Invalid contract/Expected/Origin/query or mismatched binding | 403 |
| Anonymous, expired, inactive, revoked or invalid auth hash | 401 |
| Worker capacity exhausted or broker/auth service unavailable | 503 |

Errors are bounded JSON `{"error":"realtime-unavailable"}`, no-store, without
binding, theme metadata or private response content. The exact-path method
middleware rejects unsupported methods before CSRF; it never authenticates,
reads cookies, executes business work or marks a view CSRF-exempt. All ordinary
routes and GET session/auth/CSRF processing retain Django's existing behavior.
Presentation middleware skips only this exact non-HXML path.

Successful responses use `text/event-stream`, no-store/no-transform and the exact
captured `X-HyperTodo-Session-Binding`. Before subscribing, and again after all
subscription ACKs, the app verifies fresh Django database-session authority.
Only then are headers constructed; the subscription's **single** initial resync
is not duplicated by the controller.

## Authority, bounds and cleanup

- A new SessionStore and Django `get_user` evaluation precede every frame and
  15-second heartbeat. Cached request user/session objects are never revalidation.
  Built-in active-user and authentication-hash checks remain authoritative;
  Django may flush/rotate an invalid/fallback session for security.
- The captured binding, user primary key and database alias must all still match.
  Midstream loss emits only `auth-required` and closes; it never adopts a new user.
  Database/broker failure closes without private diagnostics.
- Limits are 256 total and four per `(database alias, principal)` per worker,
  a 60-second connection lifetime, and two seconds for broker operations/close.
  Lifetime and closed state are checked again after awaited auth before output.
- The broker's 32-item queue overflows conservatively to resync. Redis PubSub has
  no replay guarantee and is not isolated by Redis DB number: namespace is required.
- Before response construction succeeds, the app retains subscription/capacity
  ownership. Afterwards the public response receives the idempotent close callback;
  even never-iterated, cancelled or failed responses release the slot. The package
  ASGI scope is a backstop, not a timer heuristic or private Django hook.

Private topics combine the actual user database and primary key as separate
encoded components. Shared UI topics use configured DatabaseSource aliases;
when `using` is omitted/None, Django's model read router selects the alias exactly
as that source does. No owner, database alias, template name or topic enters SSE
payloads. Resources are canonical nonempty subsets of `tasks`, `categories`, `ui`.
Task screens already declare their category dependency, so category renames do
not require changing the template corpus.

Legacy wire: `invalidate` carries only `{"version":1,"resources":[...]}`; `resync` and
`auth-required` only `{"version":1}`; heartbeat is a comment. No IDs, retry fields,
URLs, XML or extra keys. The consumer rejects noncanonical broker envelopes.
The a22-backed application additionally negotiates `changes-v2`, fresh response seeds
and opaque entity/origin metadata, projecting back to this exact v1 wire for old
clients; see [contextual changes](realtime-changes.md). All authority and lifecycle
checks above remain prerequisites, not replaced by the feature header.

## Verification boundary

Permanent tests use real Django session/auth/SQLite, actual ASGI middleware and
public package framing/cleanup, with a controlled acknowledged subscription where
Redis is not under test. They cover expiry/revocation, old bindings, capacity,
cancellation, lifetime-after-auth, exact Origin ports and preheader ownership.
The earlier failed native recovery trace remains historical; it was followed by
separately reviewed recovery and limited [normal-App SSE demo](sse-demo-fixture.md)
evidence. This configuration migration does not rerun or extend native acceptance.
