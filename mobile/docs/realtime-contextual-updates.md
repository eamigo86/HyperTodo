# Contextual realtime updates

**Keep reading while readonly screens refresh; protect edits before replacing a form.**
Use the normal App with the matching contextual backend. Do not inject hints or
reload manually when checking automatic SSE delivery.

## What to expect

| Situation | Result |
| --- | --- |
| A visible Dashboard or clean list receives a remote change | Reload its canonical document automatically; show a small success snackbar only after matching layout. |
| This device's admitted operation produces an echo | Invalidate normally, but do not show an SSE warning or refresh snackbar. Existing Save feedback is unchanged. |
| Login, initial resync, or confirmed foreground reconciliation | Reconcile silently; session confirmation is still required. |
| Return to a stale retained readonly route | Keep its tree mounted but hidden until fresh HTTP and actual layout complete. No refresh toast for this focus return. |
| An edited Task X receives a precise change for Task Y | No irrelevant form warning. Unknown metadata remains conservative. |
| Another device edits the same task or a current form dependency | Keep the draft and show an actionable card. Update requires discard confirmation when edited. |
| Close the warning | Hide this warning revision only. The route remains stale; a later conflict can show a new card. |
| Type a filter/search value without applying it | Defer automatic list replacement; preserve the exact input until the user resolves it. |

The card uses existing theme tokens, accessible actions and translated English /
Spanish labels. These are app-owned copy and policy, not a global user setting.
The SDK's list remains the same mounted instance across canonical reloads.
Successful refresh feedback is “Updated with recent changes” / “Actualizado con
los cambios recientes”. It does not claim that a network response alone was applied.

## Lists and pagination

Negotiated list refreshes remove fragment selectors and use `through_page=N`
for a contiguous loaded prefix of 1–20 pages, retaining filters, row keys, counts,
chips and styles. The backend clamps the final page if deletions shorten the list.
Above 20 pages (400 rows), the fallback is a fresh canonical **page 1**, never a
truncated page 20 presented as the old prefix. This fallback is automatic too.

There is no forced scroll-to-top call. Preserving the mounted FlatList is not a
promise of an exact pixel anchor after deletion, height changes, or the page-1
fallback. Legacy v1 list documents keep their older page-1/manual pagination policy.

## Draft and response safety

Draft comparison uses the same public form serialization as submission, held only
in memory. It ignores `csrfmiddlewaretoken` and forms with no other values for
comparison only: real POSTs still include CSRF. Hidden functional fields, including
an avatar draft, remain part of the comparison. Unsupported or oversized snapshots
remain protected; they never mean “clean”.

A real functional field edit advances the draft revision even when two snapshots
are both unknown. Focus/blur, cosmetic rendering and request-only row forms are
not edits. The owned avatar behavior signals its live field change before mutation,
without retaining another image payload.

A hint never resets the baseline. A complete-form POST 200 can reset it only at its
matching layout, with the same draft revision and applied form snapshot. A 422,
an unrelated form, or merely sending the request cannot mark edits saved.

If a POST response would replace a form edited after submission, hold that exact
response and its effects until explicit discard consent. Recheck the generation,
live owner, document and edit revision after the dialog and any background pause.
Do not resend the POST. A logout or replacement owner abandons the old response;
it cannot clear device credentials or execute a retired transition. Settings clear
still requires its existing response-owned status-200 capability. CSRF refusal
remains distinct and does not offer a destructive Update action.

## Negotiated operation and entity metadata

The request and response must agree on
`X-HyperTodo-Realtime-Features: changes-v2`. Otherwise the connection accepts the
existing v1 protocol. A v2 invalidation has exactly `version`, `resources`,
`mutation_id` and `entities`; resources remain `tasks`, `categories`, `ui`.

- Mutation ID: null or 40 lowercase hexadecimal characters.
- Entities: null or an opaque 16-hex epoch with 1–32 distinct resource/key pairs;
  keys are 64 lowercase hexadecimal characters.
- Resync and auth-required remain v1. Event JSON stays within 4 KiB.

The form boundary declares escaped entity metadata. The current category comes
from the actual picker-field value and its selected item's
`realtime-entity-key` / `realtime-entity-epoch`, not its initial selection.
Missing metadata or a changed epoch falls back to resource matching.
An account ID is **never** evidence that a change came from this device.

Only a current, binding-checked, same-origin negotiated response can supply
`X-HyperTodo-Mutation-Seed`: a fresh 128-bit server seed. The client appends an
8-hex operation counter to that 32-hex seed. It does not use `Math.random`,
installation IDs or storage credentials. The in-memory ledger retains one current
seed, one monotonic uint32 counter and 256 recent operation IDs. The counter never
resets across seed rotation or generation changes, so normal navigation does not
exhaust a seed-history limit. Repeated or out-of-order seeds cannot reuse IDs;
actual counter exhaustion or missing metadata yields unknown origin, not a false own
echo. Admission is not an ACK and late response loss does not replay the mutation.

Deploy the matching backend and the pinned published a22 broker schema together;
old clients receive v1 projection. Older a21 alone does not provide v2 correlation.
Unknown origin
can therefore still produce conservative warnings. See the
[backend deployment contract](../../backend/docs/realtime-changes.md).

## Check the behavior with fictional data

1. Open the same task on devices A and B. Edit its title on A without saving.
   Save a different task on B: A's draft should remain without an irrelevant card.
   Save the same task on B: A should keep its draft and offer Update.
2. On A, close the card: the input stays and the stale state is not acknowledged.
   Cause another relevant change, choose Update, then cancel the discard dialog.
   Choose Update again and confirm: only then should saved values replace edits.
3. On a visible clean list, load two pages and change a task remotely. Verify the
   automatic refresh includes both pages, current counts and filters, then one
   success snackbar. Repeat while typing an unapplied filter: the input must stay.
4. Change a hidden readonly route, then navigate back. Expect minimal loading,
   fresh content and no focus toast. Login/resync must not show a change banner.
5. Save a form with a delayed response, then type again. The response must wait for
   consent; signing out instead must abandon its old effects, without another POST.

These steps are a future native checklist, not a claim they were executed here.
Permanent Jest controls use real Hyperview Parser, DOM, public callbacks and React
Navigation with explicit native shims and synthetic HTTP/stream responses.
Historical native SSE acceptance is separate; it does not prove this contextual UX.
