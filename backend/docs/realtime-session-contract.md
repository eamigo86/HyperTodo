# Realtime session contract

A modern client can confirm the **effective Django cookie session** and reject
stale expectations before protected application work. This protocol does not
implement SSE, change permission checks or grant authentication through a header.
Legacy HXML, Admin, CSRF, status codes and existing biometric effects remain intact.

## Wire contract

Send `X-HyperTodo-Client-Contract: realtime-v1` on same-origin `/hv/` requests.
Absent negotiation preserves existing routes; unsupported/combined/malformed
values return 400 `{"error":"unsupported-client-contract"}`. Outside `/hv/`,
including Admin, these headers do not change behavior.

`GET /hv/session-state/` requires negotiation but no expected binding. It returns
only `{"version":1,"authenticated":true|false,"binding":"hvs1.…"}` and the same
`X-HyperTodo-Session-Binding` header. JSON is bounded below 1 KiB; responses use
`Cache-Control: no-store` and `Vary: Cookie`. Other methods return 405; legacy
requests to this new endpoint receive 404.

Confirmation performs no application-owned session allocation, writes, key
rotation, CSRF token creation or business effects. Django still validates its
actual lazy user and may **flush invalid authentication or rotate a fallback key**
for security. Healthy authenticated and anonymous confirmation do not write.

Normal negotiated HXML requests and auth POSTs require
`X-HyperTodo-Expected-Session`. Both binding headers have exactly 48 ASCII bytes:
`hvs1.` plus 43 unpadded base64url characters. Missing/malformed expectations return
400 `{"error":"invalid-session-binding"}`; constant-time mismatch returns
409 `{"error":"session-binding-mismatch"}` **before the business view/queries**.
Django session/authentication reads remain necessary and allowed. These errors
are bounded, no-store and disclose neither the actual unexpected binding nor
private HXML. Confirmation is explicit, never silent adoption of another owner.

Bindings use Django `salted_hmac`, salt `hypertodo.session-binding.v1`, SHA-256
and the server secret. The exact message is UTF-8 encoding of:

```python
json.dumps(
    [1, user._state.db, str(user.pk), request.session.session_key],
    separators=(",", ":"),
    ensure_ascii=True,
)
```

Anonymous state uses `[1, null, null, null]`. The HMAC digest is base64url-encoded
without padding. No input, secret, raw session key, owner identifier or biometric
credential is added to protocol headers. The binding is **not a bearer token**.

## Middleware order and resulting identity

Request order is intentional:

1. `SessionBindingResponseMiddleware` (app-local finalizer).
2. Django `SessionMiddleware`, normal locale/common/CSRF middleware, then
   `AuthenticationMiddleware`.
3. `SessionContractMiddleware` (app-local guard), before profile/theme queries
   and protected views.

Response order reverses. The guard marks the exact successful guarded response
and its status **privately on the request**. Django then saves/clears its session
and sets cookies. Only afterward does the outer finalizer calculate the resulting
binding. This matters for account switch A→B: Django flushes A and allocates B's
new key during response persistence. No early or duplicate save is added.

If persistence replaces the response, or its status changed after the guard,
no stale auth outcome or intermediate binding survives. Existing failure
body/status remain unchanged and no-store. Other guarded HXML/error responses
carry their effective resulting binding; negotiation failures never disclose it.

## Auth outcomes are explicit branch results

| Exact POST route | Outcome and unchanged status |
| --- | --- |
| `/hv/login/` | `password-ok` 200; `password-invalid` 422 |
| `/hv/biometric/login/` | `biometric-ok` 200; `biometric-invalid` 401; `biometric-throttled` 429 |
| `/hv/logout/` | `logout-ok` 200 |

Only these owning branches set `X-HyperTodo-Auth-Outcome`, and only after modern
negotiation. GET, generic errors, CSRF403 and settings/preferences events do not
claim authentication. Settings credential removal stays a same-session effect.
Logout retains biometric enrollment while deleting existing preference cookies;
password opt-in and biometric rotation keep their existing HXML token handoff.
No credential is copied into a new header.

## Verification and scope

Permanent Django-client regressions cover exact HMAC/grammar, no-write healthy
confirmation, session/user separation, rotation/revocation, incoming versus
post-persistence identity, no pre-guard business queries/writes, permissions,
CSRF, real auth branches, session-save failure, legacy/Admin and same-session
credential removal. Tests use isolated SQLite and LocMem; the separately enabled
existing Redis regression profile uses UUID namespaces in its test database.

This is backend contract C3a only. Mobile supervision, native lifecycle/layout,
SSE transport and the demo remain separate work; backend tests are not native
or end-to-end SSE proof.
