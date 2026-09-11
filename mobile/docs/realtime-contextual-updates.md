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
| Return to a stale retained readonly route | Keep its tree mounted but hidden until fresh HTTP and actual layout complete. Show the existing centered HyperTodo mark, name and spinner in the available content area; no refresh toast for this focus return. |
| An open Task X form receives a precise change for Task Y | No irrelevant form warning. Unknown metadata remains conservative. |
| Another device edits the same task or a current form dependency | Show the same centered dialog whether the form is untouched or edited: one short localized sentence and exactly **Update** and **Go back**. Any local draft stays until either choice discards it. |
| Close a non-conflict warning card | Hide this warning revision only. The route remains stale. The form-conflict dialog has no close, backdrop or hardware-back dismissal action. |
| Type a filter/search value without applying it | Defer automatic list replacement; preserve the exact input until the user resolves it. |

The card and dialog use existing theme tokens, accessible actions and translated
English / Spanish labels. These are app-owned copy and policy, not a global user setting.
The SDK's list remains the same mounted instance across canonical reloads.
Successful refresh feedback is “Updated with recent changes” / “Actualizado con
los cambios recientes”. It does not claim that a network response alone was applied.

Stale-route loading reuses the App's `LoadingScreen` inside the existing safe-area
host, with the current light/dark theme. The overlay fills the retained content
area without remounting its Root or list. It disappears only when the existing
gate reveals the committed document. On failure, the error notice remains usable
while stale content stays hidden; an explicit Update GET shows the same loader
again. This does not change request, pagination, session or POST-replay policy.
Real App/SDK renderer tests cover the loader, theme, retained identities and retry;
native layout and visual inspection remain manual checks.

## Choose how to resolve a form conflict

- **Update / Actualizar** discards this form's draft and fetches the current saved
  form with a new GET. It does not merely display a retained POST response.
- **Go back / Volver** discards this form's draft, returns to the exact preceding
  route and fetches that route before revealing it. It does not refresh unrelated
  screens. If that route is unavailable or its clean state cannot be proved,
  Go back is visibly disabled with an accessibility hint; Update remains available. Another
  page's unsaved edits are never covered by this choice.

The dialog shows only a short sentence such as “This task was updated remotely.” /
“Los datos de esta tarea se modificaron de forma remota.” and the two buttons,
without a separate title or explanatory paragraph. It uses the same light/dark
surfaces and blue action as the App, dismisses the keyboard and exposes modal
accessibility semantics. There is no second confirmation for
the same edit revision. Pausing, leaving the screen, signing out or unmounting
revokes old button callbacks, even if the same form later regains focus.

During either refresh, the existing branded loader covers the retained document
until its own GET and layout acknowledgment complete. The accepted resolution
does not briefly redisplay the old change-warning card while waiting; actual
failure, CSRF and recovery notices remain distinct and usable. A failed Update preserves
the draft behind the error/retry notice; retry uses the same explicit consent.
A later functional edit requires new consent. Changes arriving after a GET was
admitted remain pending rather than being falsely acknowledged by that response.

Object wording comes only from the boundary's declared target matching its actual
containing screen: `task-form-screen`, `category-form-screen` or `settings-screen`
(including profile/security settings). Unknown or inconsistent declarations use
generic form wording. URLs, resource lists and entity IDs do not determine this
display label or grant any action authority.

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
response and its effects. The remote-conflict dialog disables both choices while
an operation is still in flight. Once its response is retained, either choice
terminally abandons that response and its local effects before issuing the fresh
GET or going back. Neither choice rolls back a save already committed on the
server, replays the POST, clears device credentials or delivers delayed navigation.

Held-response notices without a remote form conflict keep their existing explicit
discard confirmation. Every delivery still checks generation, live owner and
edit revision; Settings clear requires its response-owned status-200 capability.
CSRF refusal and generic error/recovery notices remain distinct. CSRF refusal
does not offer a destructive Update action.

The normal `createSessionApp` supplies the dialog's English/Spanish copy. An
isolated gate integration with only the older notice-label port retains its
legacy card contract; that compatibility is not an App preference or setting.

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

1. Open the same task on devices A and B. First leave A's form untouched, then
   repeat after editing its title without saving. Both must show the same dialog.
   Save a different task on B: A's draft should remain without an irrelevant card.
   Save the same task on B: A should keep its draft behind the two-choice dialog.
2. On A, choose Update: expect the branded loader, then current saved values.
   Repeat the conflict and choose Go back: expect the preceding page to refresh
   before it is shown. With no clean preceding route, Go back must be disabled.
   Pause with a dialog visible and resume: old callbacks must not discard edits.
3. On a visible clean list, load two pages and change a task remotely. Verify the
   automatic refresh includes both pages, current counts and filters, then one
   success snackbar. Repeat while typing an unapplied filter: the input must stay.
4. Change a hidden readonly route, then navigate back. Expect minimal loading,
   fresh content and no focus toast. Login/resync must not show a change banner.
5. Save a form with a delayed response, then type again and cause a remote conflict.
   Both dialog choices must wait until the response is retained. Update must fetch
   the form, not deliver the old response; Go back must refresh the prior page.
   Signing out instead must abandon old effects, without another POST.

These steps are a future native checklist, not a claim they were executed here.
Permanent Jest controls use real Hyperview Parser, DOM, public callbacks and React
Navigation with explicit native shims and synthetic HTTP/stream responses.
Historical native SSE acceptance is separate; it does not prove this contextual UX.
