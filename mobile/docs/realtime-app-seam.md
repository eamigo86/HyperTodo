# Owned authentication and retained-tree gate seam

**This reference documents the internal authentication and retained-tree bridge.**
Its original bounded JavaScript unit used the real Hyperview 0.110.0 Parser,
renderer and public callbacks; those tests alone do not establish native acceptance.
App composition and backend negotiation have since been integrated. See the current
[App composition](realtime-app.md), [resource policy](realtime-resources.md) and
[generation-owned SSE connection](realtime-event-stream.md) for their separate
contracts and the still-separate end-to-end/native SSE verification boundary.

## Integrate the exact owned ports

`createRealtimeGate({authenticate, onReady})` returns the existing `Root`, fetch
wrapper and operation dispatcher, plus:

- `setRetainedPaused(epoch, paused)`: retain the mounted tree and admitted work;
  only the current epoch can change the pause. OS foreground alone must not call
  resume: App first confirms the cookie-backed session through its supervisor.
- `bindSource(element, {getRoot, updateRoot})`: capture the actual route, epoch and
  live source. It returns `isAlive`, `sourceIsCurrent`, `onUpdate`, `effectReceipt`
  and `bindBiometricSubmit`. Ambiguous boundaries or a removed source reject.
- `isSettingsClear(element, source)`: the positive response-owned predicate for
  the owned credential behavior. Do not replace it with an empty-token check.

The auth port receives the genuine Parser-prepared request. The App adapter uses
`modern-form-body` to snapshot its FormData **before** invoking the supervisor;
that bridge is separately owned. It returns the supervisor's discriminated
`AuthResult`, not a fabricated Response. A private operation-bound signal crosses
the real Parser's fetch rejection and is consumed only by that operation.

A supplied `resume(result)` belongs to one attempt. If foreground completes before
Parser registers `held`, the gate buffers one result until that held handoff.
Duplicates, a stale epoch, or an already retired operation cannot deliver. A true
return is continuation admission, **not** authentication success or an XML ACK.

## Deliver outcomes without retiring-tree effects

| Result | Gate behavior |
| --- | --- |
| `transition` | Retire as `no-document/auth-transition`; never parse or execute transition HXML on the old tree. |
| `held` | Keep the exact operation reserved; await its owned continuation. |
| `panel`, status 422/401/429 | Parse the bounded app panel and perform the real public swap; only its matching node at layout ACKs. |
| `refused`, status 403 | Preserve the form, stack and draft; expose `auth-refused` notice and a no-document terminal. No error HTML reflection or XML ACK. |
| `busy`/`uncertain`/`stale` | Explicit typed terminal, not successful XML delivery. |

Accepted panels are UTF-8 bounded to 262144 bytes, reject declarations and nested
screen/document/navigation roots, and retain the canonical `login-panel` target.
They must contain this modern response-specific root key:

```xml
<view xmlns="https://hyperview.org/hyperview"
      id="login-panel" key="auth-panel-REQUEST_ID">
  <!-- original app-owned panel -->
</view>
```

`REQUEST_ID` is the exact `X-HyperTodo-Request-ID` of that operation. The existing
a16 schema accepts `view.key`; no schema relaxation is needed. Missing or wrong
keys reject before replacing the draft. Real SDK tests show why: repeated
unkeyed panels can retain press callbacks referring to removed behavior nodes.
This key remounts only the rejected panel, **not** Root or its navigation stack.
No private SDK normalization or additional behavior IDs are used.

Native field callbacks also require exact live-node ownership before any local
`swap`. A callback retained from a replaced panel cannot mutate its same-ID
replacement. After a valid public SDK swap, the gate carries the new document's
boundary forward synchronously so consecutive current edits retain their full
value; only real layout can ACK. The callback's captured epoch remains binding.

Permanent actual-App tests reproduce a detached-panel blur/focus/change causing
`No root element found`, and a second current edit being dropped before layout;
both are guarded without editing the SDK. They also retain repeated rejected
panels followed by successful login. This controlled reproduction matches the
Simulator error stack, not proof of the exact native event ordering or a native
post-fix PASS. See isolated evidence `ios-root-failure-*`.

A biometric401 clear node receives the exact accepted receipt before its real
load callback. The factory consumes that receipt; it does not run another native
credential effect. Settings clear is distinct: only a correlated same-origin
POST `/hv/settings/`, status200, replacing `settings-form-panel` can register a
direct empty-token `store-biometric-token` load/once/immediate node. The private
binder must belong to that same live node and gate. GET, other URLs/statuses,
forged source objects, paused/retired identities and unrelated empty tokens fail.
The factory retains its per-node exactly-once ledger.

Contextual draft protection holds a destructive ordinary POST response before its
public swap when later input exists. Its Settings-clear capability is not delivered
until owned discard consent and the existing retention checks permit that same
source. Logout/replacement abandons it without another POST. A 422 cannot acquire
the status-200 credential-clear capability. A complete-form saved baseline resets
only after matching layout with an unchanged revision/snapshot; other drafts stay
protected. See [contextual updates](realtime-contextual-updates.md).

## Pause and ownership are not logout

A retained pause denies new actions/refreshes and native continuations, without
resetting the epoch or unmounting the tree. Already admitted ordinary writes
retain their reservation and are never resent or treated as rolled back. The
gate holds prepared delivery until confirmation. If pause occurs inside `onEnd`
after a swap, confirmed resume requests a real public rerender so the actual
layout can acknowledge it; no timer, callback or parse event substitutes for ACK.

`isAlive` can remain true during a same-owner pause, while `sourceIsCurrent` is
false. Native factories capture the source and its one-use biometric submit
**before** opening a prompt, recheck after await, then invoke that same closure.
The closure updates the original form field through public `shallowCloneToRoot`
and dispatches its existing biometric POST. It never uses a global event bus or
rebinds to whichever screen happens to be focused later.

`onReady({epoch, routeKey})` is emitted from a real focused boundary layout, not a
navigator scaffold fetch or Parser completion. Identity changes still revoke the
whole previous Root through the separate epoch-reset contract.

## Keep navigation within the confirmed session

The real App keys its public `NavigationContainer` by presentation
(`primary` or `recovery`) and session generation. Resetting only Hyperview's Root
can leave React Navigation holding the retired route: a new authenticated root
document may otherwise request the old login URL instead of its dashboard.

The session owner and App lifecycle remain outside this navigation reset.
`session.start()` is cached, so remounting its surface does not repeat bootstrap.
Resource hints, theme updates and a confirmed same-identity foreground keep the
same key, mounted field and draft; they do not fabricate an ACK or replay a POST.

Permanent actual-App/public-SDK controls cover URL-accurate login and recovery
after a mutated task route, plus retained field identity and unchanged HXML
request/observation counts across hints, theme and foreground. Evidence lives in
`native-navigation-*`. This JavaScript reproduction and correction do not prove
the exact cause or resolution of the separately recorded native recovery failure.

## Verify and review

Permanent tests: `mobile/__tests__/realtime-app-seam.test.tsx`. Reproduction and
chronological RED/GREEN logs live in the isolated evidence directory, under
`c3-app-seam-*`. Native Jest shims are explicit; ordinary HTTP responses and auth
outcomes in these tests are synthetic fixtures. No phone or production broker
participates in this unit.

Current integration must preserve persistent accessible translated error notices,
real keyboard/OS pause behavior, session binding, and exactly-once credential
handoff. [Resource dependency filtering](realtime-resources.md) and negotiated
template metadata have their own implemented contracts; this seam does not replace
them with global invalidation. Historical unit results remain distinct from a
current native SSE verdict.
