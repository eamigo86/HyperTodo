# Real-App native Gate0 fixture

**Prepare, review, then coordinate a native run. No service or device is launched
by the unit tests.** This entry imports the same `createSessionApp` as normal
HyperTodo, with only fixture origin, storage, diagnostics and passive observation
injected. It is not an SSE endpoint or a native acceptance result.

## Evidence and boundaries

- `GatePorts.onObservation` emits frozen ready/terminal facts after the existing
  public layout/lifecycle decision. It exposes no XML, callbacks, reset or ACK.
  A fetch, parse, unrelated layout or navigator scaffold is not a successful ACK.
- `report.cjs` sends exact closed records to `POST /__native__/report/`:32-hex run,
  sequence1–500, <=2048 UTF8 bytes, no free text, identity, cookie, header, URL,
  body or credentials. `report-vectors.json` is test-only equivalence data for the
  independently implemented backend validator. `complete` means collection ended,
  **not PASS**. Exhausted delivery, bounds or cleanup are sticky INCONCLUSIVE.
- The fixture's controls sit outside the actual App/FlatList. “Receive tasks hint”
  invokes only the current captured ready receiver; this is hint→HTTP→layout
  proof, not Redis/SSE delivery. A retired receiver cannot act on another session.
- “Hold next GET/POST” delays delivery of one correlated **genuine Response**;
  “Release response” returns that same object. No URL/status/body/header changes.
  Native errors retain identity/name. The30s deadline fails; it never acknowledges
  XML, retries a POST or claims network rollback/abort. Use the separate I/O probe
  for native streaming/AbortController evidence.
- Diagnostics ignore raw SDK arguments and record only `sdk-error`. The App's
  narrow diagnostics DI preserves its real failure UI and normal non-fixture
  defaults; no global console patch.

## Run preparation — only after source review

1. Verify the final candidate/source manifests and compatible installed Expo
   client/account through the official flow. Do not read private Expo auth files.
2. Allocate the existing synthetic Django fixture with append data (22 tasks for
   fictional A,2 for B), exact private-interface binding and `--events-report`.
   The backend owner documents its finite controls and cleanup. Never seed/read a
   real DB or use an original host/Metro.
3. Prepare an independent JSON expectations file under evidence:

```json
{
  "run": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "apiOrigin": "http://hvt-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.local:8787",
  "metroOrigin": "http://hvtm-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.local:8082",
  "credentialKey": "hvt-native-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.credential",
  "themeKey": "hvt-native-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.theme",
  "platform": "ios",
  "username": "replace-with-verified-expo-username",
  "projectRoot": "/absolute/private-workspace/native-app-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/metro",
  "slug": "hypertodo-native-app",
  "mainModuleName": "index"
}
```

The example is not a usable session. Replace its run/origins with independently
allocated fresh values, choose an unused launcher directory, and use `android`
for that platform's guard. Do not derive expected account/source from the
manifest being checked. No credentials or tokens belong here.

4. With the existing Node24 binary and readonly dependency directory, run:

```sh
# Run from the checkout root with an existing Node 24 binary.
REPO_ROOT=$(pwd -P)
NODE=${NODE:-node}
MODULES=${MODULES:-"$REPO_ROOT/mobile/node_modules"}
"$NODE" mobile/test-support/native-app/launcher.cjs "$EXPECTATIONS" "$MODULES"
```

`sourceRoot` may be supplied in expectations; its default is the helper's
containing mobile directory. `dependencies` may also be explicit and must agree
with the CLI argument. Paths must be canonical and have no symlink ancestors;
output ends in `native-app-<run>/metro` outside sources/dependencies. The source
root, dependency directory and independent expectations are never cleanup targets.

This creates only five fresh launcher/config files; it refuses an existing
launcher. No install or build occurs. Existing Expo57.0.21/React19.2.3/RN0.86.3/
Hyperview0.110.0 metadata must match. Metro uses the reviewed shared Expo/HMR
resolver and readonly modules, with an isolated cache. Keep original8081 untouched.

5. Coordinator starts the finite fixture, fresh aliases and separate Metro using
   an explicitly reviewed command, isolated HOME/cache and telemetry disabled.
   Do not set EXPO_OFFLINE or use a public tunnel. Expo's `--host lan` advertising
   alone does **not** prove an exact-interface socket bind. Verify the listener and
   private exposure policy before native handoff; this preparation tool does not
   configure or start DNS/Metro/LAN.
6. Then perform the explicit, bounded development-HTTP check:

```sh
"$NODE" mobile/test-support/native-app/check-development.cjs "$EXPECTATIONS"
```

It validates expectations before HTTP, exact generated entry provenance, the
**served** manifest's source/account/SDK/fresh DI and actual HTTP200 development
JavaScript/HMR. It never calls Django auth/data/probe endpoints or launches a
client. Static marker checks supplement frozen source hashes, not replace them.
The older synthetic I/O entry and guard remain unchanged.

## Small native campaign

Use the [run design](../../../../evidence/gate0-mobile/native-app-run-design.md):
real login/refusal/logout/mismatch; page1 document refresh preserving filters;
form notice/draft; representative append-first and reload-before-POST races;
real focus/background/confirmation. Navigate and edit through the actual App,
not a duplicate screen. Select the relevant case label, arm/release the one
response if needed, and use the explicit tasks hint after a synthetic host edit.
The two opposite orders of each negative/permutation remain permanent SDK tests;
there is no additional manual204/error matrix or second-instance test App.

iOS/Android each still require native I/O plus actual layout integration. Previous
iOS I/O evidence may be reused if relevant transport code is unchanged. Jest uses
real SDK with disclosed native shims; its logs are **not device evidence**.

## Safe-area controls

The fixture controls use the installed public `react-native-safe-area-context`
provider and current top/left/right insets, plus the existing 8px spacing. There
is no fixed notch height. This provider wraps only the diagnostic controls;
the real App remains its sibling and keeps its own provider/navigation lifecycle.
Inset updates do not remount App, clear drafts or create gate observations.

A physical iPhone screenshot exposed the former fixed 36px overlap. Permanent
JS tests cover nonzero/zero/changing insets, accessible control behavior, retained
drafts and ordered cleanup; **a fresh native screenshot must verify the fix**.
No native acceptance is inferred from these tests.

## Finish safely

Press “Finish and clean fixture”. React first removes the real App; its cleanup
revokes the session/source authority. Only the subsequent fixture passive effect
closes new storage admission, drains previously admitted writes through the same
credential queue and tracked theme adapter, then deletes the two fixture keys.
The10s drain limit returns INCONCLUSIVE if settlement cannot be proved, rather
than deleting early while a late write can recreate a key. Repeated Finish is
idempotent. No shared-cookie cleanup or default storage access is performed.

Finish displays two independent local diagnostics once cleanup settles:
- **Local cleanup: confirmed** means the lifetime helper confirmed draining and
  both fixture-key removals. **Not confirmed** covers failure or timeout; it does
  not mean that no key was removed.
- **Report: state (reason)** uses closed diagnostic codes only. For example,
  `inconclusive (report-failed)` can accompany confirmed local cleanup: uploading
  evidence failed, not necessarily cleanup. A successful upload cannot establish
  cleanup either. No headers, exception text, keys or payloads are displayed.

Any recording/cleanup gap still leaves the global verdict **INCONCLUSIVE**;
`Report: complete (none)` still requires host review, not native acceptance.
These diagnostics do not identify the physical cause of an earlier missing upload.

### Local SDK diagnostic codes

The shell retains the first code for each existing sink (`on-error`,
`logger-error`, `logger-warn`), at most three rows, including after Finish.
For example: `SDK on-error: http; status 503`. Codes classify an allowlisted
family/name on a public `HvBaseError`, not exact constructor identity, authority
or a demonstrated cause. Only own data descriptors are inspected; an HTTP status
is shown only for a recognized HTTP/parser error and an integer from 100 to 599.
Other values, generic/abort errors, string warnings and name/status spoofs remain
`unknown`. No getters, messages, URLs, headers, bodies or context are read.

These rows are local screenshot evidence only. Every sink still emits the same
closed wire `diagnostic` / `sdk-error`; no protocol, retry, ACK or App flow changes.
The real-SDK tests establish classification and leakage controls, not the cause
of the unresolved native recovery failure or a native PASS.

### Bounded report recovery

Only confirmed `AppState.active` admits new uploads. Initial unknown/inactive
state queues records. Activation reads current state only after subscribing at
mount; an earlier factory-time value cannot authorize a child layout upload.
Inactive/background notifications are recorded in order,
then drained on foreground. An already admitted attempt is not aborted merely
because the App pauses. Its 2s deadline still fails even if the network ignores
AbortSignal; a timer is never evidence acknowledgment.

Each frozen head has at most **two total attempts**, and only transport failure
or timeout permits the second. HTTP non-204 is definitive and never retried.
Nothing advances until that head receives HTTP204. The companion collector ACKs
only its exact, validated, immediately last accepted record again, without adding
an event or changing its count/verdict; older/conflicting records still fail.
This explicitly replaces the earlier once-only test-fixture policy. It does not
retry business/auth POSTs, change the ten-field wire contract, or forgive gaps.

Finish seals producer admission before awaiting its final marker. Pauses cannot
reset the attempt budget or enqueue records after `complete`. Unexpected unmount
cancels pending upload/wait work; exhausted delivery, invalid/overflow records or
an unconfirmed teardown remain sticky INCONCLUSIVE. Queue limits remain 500
logical records and 2048 UTF8 bytes per record, within the finite fixture run.
Successful collection still requires host review; these controlled regressions
are not proof of the cause of any earlier phone failure.

Persist server JSONL and the separate native screenshot/observations before
coordinator stops the owned finite services and private DB. Unexpected termination,
expiry, upload gap or failed cleanup cannot be called complete/native PASS.

## Permanent commands (no running server needed)

```sh
"$NODE" --test mobile/test-support/native-app/*.test.cjs
cd "$REPO_ROOT/mobile"
"$NODE" node_modules/jest/bin/jest.js \
  --config jest.config.js \
  --runInBand --no-cache --watchman=false --runTestsByPath \
  __tests__/realtime-native-observer.test.tsx \
  __tests__/realtime-native-harness.test.tsx \
  __tests__/realtime-native-safe-area.test.tsx
"$NODE" node_modules/typescript/bin/tsc --noEmit
# For external readonly modules, use the coordinator's explicit resolver adapter;
# NODE_PATH alone does not redirect TypeScript config resolution.
```
