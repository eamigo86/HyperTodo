# Contextual changes with the published package

**Negotiate change metadata to distinguish this operation from a remote edit.**
The backend still sends hints, not documents. The mobile host decides whether to
refresh silently, confirm a visible remote refresh, or protect a dirty form.
Neither a matching token nor an HTTP success acknowledges a native layout.

HyperTodo pins published beta `dj-hyperview[editor,realtime]==0.1.0b1`, whose public
`INVALIDATION_VERSIONS` capability is `(1, 2)`. The backend checks that capability,
not a guessed version. An older a21 installation advertises no v2 feature/seed,
publishes v1 and retains legacy presentation metadata. That compatibility fallback
does **not** provide own-echo correlation or entity precision.

Deploy package and backend workers together, and roll them back together. Do not
mix old a21 Redis readers with v2-producing workers in the same namespace. Client
compatibility is not mixed-backend compatibility. Published-package adoption does
not prove new native acceptance of the contextual UX.

## 1. Negotiate on existing requests

Keep all existing cookie, CSRF, Origin and expected-session checks. Add
`X-HyperTodo-Realtime-Features: changes-v2` to the already-owned HXML and SSE
requests. The successful negotiated response echoes that header and sends
`X-HyperTodo-Mutation-Seed`, a fresh 32-lowercase-hex random 128-bit seed.

HXML seeds are attached only after final Django session persistence/binding
verification. SSE seeds follow authentication, all subscribe ACKs and the fresh
authority recheck. Bootstrap uses the existing `/hv/session-state/` GET, including
anonymous confirmation; no extra seed request or session allocation is necessary.
No seed is advertised on unverified/replaced responses or 5xx. Seeds are generated
again for each response, including a reused cached object or a 304. Existing
no-store policy remains; `Vary` includes the feature header.

The client accepts a seed only from its verified same-origin, same-owner/current
generation response. It concatenates the seed with an eight-hex-digit uint32
operation counter and sends the exact 40-lowercase-hex result as
`X-HyperTodo-Mutation-ID` on that POST. Re-observing a seed must not reset its
counter. No wrap, reuse or fallback to a user/session ID: missing seed, exhausted
counter or changed owner generation means unknown origin. Seeds are not persisted
on the server. This is 128 random bits plus a counter, not fresh independent
randomness per operation.

The guarded POST context is isolated and restored after exceptions. Invalid IDs
become unknown; they never grant authority or change existing auth/CSRF rejection.
Signals capture the context before `on_commit`, so SSE may arrive before the POST
response or after the request context ended. Rollback still emits nothing.

## 2. Interpret the closed envelope

An invalidate v2 contains exactly:

```json
{
  "event": "invalidate",
  "data": {
    "version": 2,
    "resources": ["tasks"],
    "mutation_id": null,
    "entities": null
  }
}
```

`mutation_id` is null or the exact 40-hex correlation value. `entities` is null or
`{"epoch":"<16 lowercase hex>","items":[{"resource":"tasks","key":"<64 lowercase hex>"}]}`.
The array contains 1–32 distinct resource/key pairs; resources must also occur in
the event's canonical subset of `tasks`, `categories`, `ui`. The package's 4 KiB
bound still applies. `resync` and `auth-required` remain version one; the endpoint
projects an exact v1 invalidate for a client that did not negotiate v2.

Entity keys are purpose-specific HMACs of the actual alias/resource/model key,
using Django's existing signing secret. They contain no raw model key, cookie,
session key, installation ID, text or email. The epoch changes with secret
rotation. Keys cannot be used to fetch an object or authorize a mutation.

Null, unknown precision, producer overflow and mismatched metadata epochs mean
**conservative resource invalidation**, never "no change". Incompatible entity
resources also collapse to null instead of dropping publication. A match to a
pending local mutation may silence presentation only; delayed or duplicate hints
still participate in freshness reconciliation. Another device of the same
account has different operation IDs and must not be treated as this device.

## 3. Publish at the existing mutation boundary

Task and Category ORM signals include that entity's opaque key. Category deletion
still covers `tasks` and `categories`, including Task owners affected by SET_NULL.
Profile presentation changes are private owner `ui` events, **not shared UI-topic
broadcasts**: User first/last name/email and Profile theme/language/avatar are
compared from persisted rows. `last_login`, password-only saves, unchanged fields,
unsaved in-memory values and creating a blank preferences row emit no profile hint.
Profile ownership transfer notifies both recipients separately with only their
own profile key. Ordinary Admin saves use the same observers and unknown origin.

Recipients remain server-selected old/new owners, never authors inferred from
scope. Template invalidation remains a broad shared UI hint for its configured
alias. Direct SQL and QuerySet update/bulk APIs still require explicit service
notification; this feature does not add hidden bulk observers or migration writes.

## 4. Render precise forms and complete list refreshes

Negotiated Task/Category/Settings boundaries use `mode="form"` and an escaped
`entities` JSON attribute. They carry their own entity (when editing) plus the
owner's profile key. A new form has no existing Task/Category key. Dashboard and
About use `mode="readonly"`; non-negotiated clients retain list/notice modes.

Each authorized category `picker-item` additionally has unqualified app extension
attributes `realtime-entity-key` and `realtime-entity-epoch`. The client reads the
**currently selected** option, not the original form choice, as its category
dependency. The ordinary option `value` is still needed for validated form
submission; it is not interchangeable with the opaque SSE key. Missing or
rotated option metadata falls back conservatively. Refused 422 form-panel responses
retain the same option metadata and submitted draft values; they do not silently
lose precision when replacing the panel. These two typed application
extensions do not alter Hyperview's vendor/core XSD.

For a ready list with pages 1 through N loaded, the canonical document GET may
add `through_page=N`, with N in 1–20 (at most 400 rows). This is a **full document**
with current chips, category task counts, styles and the same list ID, not a
rows-only substitute. The response includes each real page marker and only one
next-page append behavior. Existing task status/category authorization is
preserved. Deleting the tail clamps to the last actual page; an empty list retains
its existing page-one empty item. No false empty tail marker is fabricated.

`page` and `through_page` cannot be combined; duplicate/invalid bounds, legacy
requests and `fragment=items` with a prefix are rejected. `fragment=list` remains
supported, but the resource coordinator must request the complete document for
refreshes affecting headers/styles. Above 20 loaded pages, the mobile host uses
a fresh canonical first-page GET with the current filters and coherent markers
and counters. It does not send an oversized prefix, pretend to preserve later
rows, or require a manual SSE banner. Returning to a stale screen stays silent;
a remote-change toast belongs only after the visible replacement is acknowledged.
Up to 20 pages, the loaded prefix is retained. No backend response alone proves
scroll-position preservation: that depends on retaining the native list instance
and must be checked separately.

A dirty form is never merged or saved by a hint. The mobile host owns value
baselines, later edits during an in-flight POST, explicit discard/refresh, and
same-account other-device warnings. HTTP 200/422 alone must not erase later edits.

## Verification scope

- `tests/test_realtime_changes.py`: exact negotiation, fresh response seed,
  unknown input, context restoration, immutable commit capture, conservative
  precision, v1 projection and actual Django ASGI framing/cleanup.
- `tests/test_realtime_profile_changes.py`: owner-only profile effects, auth-only
  exclusions, persisted values, ownership transfer and rollback.
- `tests/test_realtime_change_templates.py`: real mandatory-XSD documents, option
  metadata, legacy modes, filters, bounds and loaded-prefix markers.

Run normal installed-package acceptance from the repository root:

```console
make backend-test
# Optional real Redis acceptance; only the isolated loopback test service:
make backend-test-redis
```

The complete default suite uses the locked a22 package, with no source hook or
temporary METADATA. Redis integration is explicitly opt-in and uses unique test
namespaces, never a shared-key flush. `test_support.runtime.verify_package()`
checks the actual import, metadata, pin and Python/Django versions before private
fixture allocation. Keep the full coverage policy enabled for the default suite.
Source-only experiments and historical installed-a21 compatibility remain separate
evidence; neither substitutes for current installed-package acceptance.
