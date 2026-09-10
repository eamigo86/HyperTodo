# Neutral Sign in recovery

A modern client can explicitly open the existing public navigator and Sign in
screen **without rendering the cookie owner's account context**. This is a
presentation scope, not authentication or permission. Django still owns the
actual cookie, Session/Auth/CSRF, credential checks and session persistence.

This backend unit is tested with isolated Django clients, real templates and
mandatory final XSD. It is not App integration, native acceptance or SSE transport.

## Exact request contract

Send both headers, with exact case-sensitive values:

```http
X-HyperTodo-Client-Contract: realtime-v1
X-HyperTodo-Recovery: login-v1
```

| Method and path | Query | Purpose |
| --- | --- | --- |
| `GET /hv/session-state/` | None | Observe actual binding/authenticated metadata, not adopt Identity |
| `GET /hv/recovery/` | None | Existing public root navigator, 200 |
| `GET /hv/recovery/` | Literal `screen=login` | Existing login screen, 200 |
| `POST /hv/login/` | None | Explicit password authentication |
| `POST /hv/biometric/login/` | None | Existing explicit biometric authentication |

Except for session-state observation, the existing strictly formatted
`X-HyperTodo-Expected-Session` is required and compared against the **original**
request in constant time. Missing/malformed Expected remains 400; mismatch
remains 409 and returns no actual binding. Binding is not a bearer credential.

The raw query must be exactly empty or, only on the recovery GET, `screen=login`.
Duplicate parameters, alternate encoding, extra parameters and any other
path/method are 400 `invalid-recovery-scope`, before business work. Invalid
recovery value or a missing/invalid paired client-contract value is 400
`invalid-recovery-contract`. `/hv/recovery/` without the recovery header is 404
`recovery-required`, including when it has no query. **No query with valid headers
and Expected is the successful root case**, not a 404. Ordinary routes without
the recovery header retain their existing legacy/modern behavior; legacy
session-state remains unchanged.

## Anonymous presentation, original security

The guard sets a private request-only marker after validation. Only that marker
activates neutral rendering and profile/theme suppression; an arbitrary header
alone cannot select this branch. Scope errors never reach application views.

Rendering uses a fresh anonymous `HttpRequest` with empty session, META, cookies,
GET/POST and no message storage or original-request reference. Locale and theme
use public defaults, not account/profile/cookie preferences. No
`X-HyperTodo-Theme` is published. Existing DB templates receive that same neutral
request through the real engine/context processors. Public context is allowlisted:
submitted username, validation/biometric notices, opt-in state, bounded realtime
metadata and the existing successful authentication effect value. A password- or
token-bearing bound Form is never passed to the template; error/username values
are projected instead. Django autoescaping remains enabled.

The masked hidden CSRF fields come from `get_token(original_request)`, passed
explicitly as escaped values. We do not copy the original META/CSRF secret into
the render request, create an unrelated CSRF cookie, or exempt either POST.
Original session-backed CSRF also works. Recovery uses the existing navigator,
login screen, replaceable keyed login panel, transitions and validation messages.
Password invalid 422, biometric invalid 401, throttle 429 and CSRF refusal 403
retain their original semantics and explicit auth outcomes where applicable.
Messages belonging to the unexpected session are neither rendered nor consumed.

## Failure and settlement boundaries

Neutral rendering is completed inside the public locale scope. If preparation,
template rendering or final XSD fails, return only JSON 500
`{"error":"recovery-render-failed"}`, never invalid XML or a DEBUG report of the
original request. Recovery 5xx responses have no binding or auth outcome. This
policy does not change normal non-recovery rendering/error behavior.

Django skips session persistence on 5xx. Authentication may already have performed
security cleanup or rotation before rendering fails: **neither rollback nor
successful persistence is promised**. No manual session save, compensating login
or POST replay occurs. Subsequent explicit confirmation observes the actual
cookie/session result.

The client recovery capability is a separate unit, not confirmed Identity. Before
issuing it, submitted auth/ordinary HTTP capable of late cookies and native storage
writes must settle. Read-only hardware probes/prompts may be revoked via captured
leases and late results discarded after every await; they need not be awaited
forever when no mutation remains. Recovery cannot authorize private resources,
SSE or theme publication, and successful auth still requires explicit confirmation.

## Review and tests

`tests/test_realtime_recovery.py` covers the real root/login navigator, original
cookie and session-backed CSRF, unexpected-account DB-template probes, message
retention, profile-query suppression, exact scope/Expected grammar, password and
biometric transitions, normal-route controls and bounded rendering failures.
Historical RED/GREEN commands, source provenance and freeze hashes are in
`evidence/gate0-mobile/c3-recovery-backend-*` of the isolated worktree run.
