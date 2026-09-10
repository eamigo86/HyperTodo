# Resource invalidation and coherent screen refresh

**Resource hints refresh only screens that declare matching dependencies.** This
policy uses the real public Hyperview document loader and layout barrier. The
[generation-owned SSE connection](realtime-event-stream.md) now supplies hints in
normal App; the original resource-unit tests alone do not establish native delivery.

## Wire the captured epoch, not a late lookup

```ts
const epoch = gate.snapshot().epoch; // capture when creating this owner/connection
const accepted = gate.invalidateResources(epoch, ["tasks", "categories"]);
```

The boolean means the hint was admitted, not that HTTP or layout completed.
Resources are exactly `tasks`, `categories`, `ui`, in that order, without duplicates.
The seven nonempty subsets are valid. Unknown values, combined strings pretending
to be one token, old epochs and unavailable label configuration have no effect.
A late callback must not obtain a new epoch to revive itself. The historical
`invalidate()` remains for previous proof fixtures; App must not use it as fallback.

A boundary's unqualified `resources` attribute declares dependencies, not ownership
or routing. Categories depends on tasks because it renders task counts. Matching
is set intersection, never a hardcoded list of route names. Hints contain no URL,
markup, owner, username or database identity.

## Choose refresh policy from the actual boundary

| Current boundary | Resource policy |
| --- | --- |
| Focused, ready `mode="readonly"` or clean list | Automatic whole-document reload. Negotiated lists retain prefixes up to 20 pages; larger prefixes fall back to fresh page 1. |
| Legacy v1 list with multiple pages, or a page other than 1 | Preserve its existing manual Update policy. |
| `mode="form"`, or legacy `mode="notice"` | Preserve the form; edited contextual forms require discard confirmation before Update. |
| Hidden readonly route | Defer; keep stale content concealed on focus until fresh layout. |
| Same-user retained pause | Keep mounted state and admitted operations; wait for confirmed resume. |

Whole-document refresh deliberately costs a larger normal HTTP response than list
replacement: chips, counts, styles and content outside the list must agree. It
uses existing canonical `refresh-href`, removes the fragment selector, retains
filters and uses the negotiated loaded prefix or documented page-1 fallback. Notice/form targets preserve their
canonical URL. No correlation nonce enters reload/navigation URLs, no root
navigator is nested, and no additional list item is fabricated.

Ordinary POST/append/replace retains the existing serialized lifecycle. Resource
refresh waits for real layout, never retries a POST, and does not call cancellation
a rollback. Repeated hints before dispatch coalesce into one refresh. Hints arriving
after an in-flight request started can require one follow-up after its real ACK;
that request cannot claim to include later changes. Per-resource clocks are private
in-memory observations, not durable SSE cursors or server revisions.

## Supply translated notice text explicitly

App provides a dynamic `noticeLabels()` port with `changed`, `resync`, `update`,
`dismiss`, `csrf` and `error`. Each must be nonblank plain text of at most 512 UTF-16 code units.
The gate never infers locale, supplies implicit English, or interprets labels as
HTML. `changed` should express possible new information, not guaranteed divergence;
`resync` expresses reconciliation, not proof of changed content. Current SSE resync
and own-operation echoes are silent, while retaining the same resource policy. Separate captured change
and reconciliation versions prevent a later resync from hiding an unacknowledged
invalidation; only matching real layout covers the versions admitted with its HTTP.

The themed notice card is accessible, with an alert/live region, dismiss action and
Update button, outside FlatList's item collection. Dismiss hides one warning revision,
not staleness. Pressing Update while work is
active is disabled; duplicate admission is also guarded. App rerender can change
labels without remounting the HXML tree, losing draft input, or fetching again.
No notice store rerenders are emitted when this optional UI port is not configured.

CSRF refusal has its own safe translated notice and **no Update action that could
discard the form**. Refresh failures remain visible without an automatic retry
loop. A deliberate retry uses ordinary HTTP and only real matching layout clears
the failed state. No native appearance/theme/keyboard acceptance is claimed by
these JavaScript tests. See [contextual updates](realtime-contextual-updates.md)
for exact entity matching, draft revisions, confirmed discard, loaded-prefix limits
and success feedback that waits for actual layout.

## Verification boundaries

The permanent resource tests use real Hyperview 0.110.0, Parser, React Navigation,
public callbacks and DOM. Native Jest shims and synthetic HTTP fixture responses
are explicit. They cover dependency matching, malformed/old hints, both operation
orders, filters, real document/layout changes, manual forms/pagination, hidden
focus, two instances, retained background work, errors, and dynamic ES/EN labels.

Earlier auth panel keys remain mandatory even when configured notices happen to
cause another render: correctness must not depend on an incidental rerender.
The navigator scaffold is not an XML ACK and its historical unowned pending
record does not become an operation barrier or disappear merely to satisfy a test.

[App wiring and authoritative session binding](realtime-app.md), the authenticated
backend/broker, and [reconnect semantics](realtime-event-stream.md) are implemented
as separate contracts. Their software checks do not turn these historical resource
tests into end-to-end/native SSE acceptance; that verdict remains separately owned.
