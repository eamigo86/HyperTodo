# Native I/O prerequisite probe

**Test-only standalone Expo 57 entry. It does not enable HyperTodo realtime.**
No application login, database, real session, biometric token or production App
module is imported. Use a verified Expo Go 57 client without building a client.
The separately authorized Android run may install official Expo Go only in its
owned disposable emulator; this entry never installs or modifies dependencies. Expo's own developer-account login is a
separate prerequisite; it is not HyperTodo authentication.

## Current native evidence

**Physical iOS native I/O: PASS on 2026-09-09 at 02:05 UTC. Full Gate 0 remains pending.**
The existing Expo Go 57.0.9 installation (native build identifier 1017880),
Expo source 57.0.21 and native React Native 0.86.2 completed the isolated probe.
The phone result matches the durable server record: its synthetic cookie was
accepted by explicit Expo fetch, two reads were independently ACK-gated, and
abort produced a client-side stream close with zero active server streams.
See the [reviewed native result](../../../../evidence/gate0-native/native-ios-result.md).

This does not prove Android, real application session/auth transitions, native
Hyperview layout/ACK races, broad action coverage, notices/accessibility or
background/reconnect safety. Production App/auth/transport remain unimplemented.
Keep these gates blocked; do not turn a narrow I/O pass into full Gate 0 approval.

## Interpret runtime metadata correctly

The panel displays the raw `Constants.expoVersion` value as **Expo client
build/version**, not as the source SDK. The observed iOS client reports
`1017880` here; the independently inspected installation is Expo Go 57.0.9,
build 1017880. The report preserves `1017880` unchanged in its existing
`clientVersion` field. It must never substitute a guessed semantic version.

The source package version (`expoVersion`, currently57.0.21) establishes the
supported source SDK57 separately. Metadata must identify iOS/Android and
`storeClient`, a bounded numeric build/version identifier, a valid SDK57
package version and a present numeric React Native version. Unknown/missing or
unsupported metadata is rejected before network access. Native React Native
0.86.2 is retained as observed; it is not forced to equal the JS dependency's
0.86.3 patch. These values describe the experiment, not its success.

## What a passing run proves

1. Normal global `fetch` bootstraps this fixture's unique HttpOnly cookie;
   explicit `expo/fetch` sends it to the synthetic stream.
2. A complete first frame is read before its ACK unlocks the second frame.
   A fully buffered response cannot pass this handshake.
3. After the second ACK, `AbortController.abort()` alone ends the native reader
   and the server records a client-initiated close with zero active streams.

The server observations and sanitized client report are separate. Neither is a
full Gate 0 approval. An iOS result does not establish Android compatibility,
Hyperview DOM/ACK races, production auth integration or app lifecycle safety.
Jest controlled streams and mocked native metadata are **not native evidence**.

## Authenticate before starting the short-lived fixture

Physical iOS Expo Go 57 requires the **same Expo account in the CLI and phone**.
A correct SDK/entry alone is insufficient: an anonymous served manifest will be
rejected before this probe runs. Use the [official Expo login flow](https://expo.dev/changelog/expo-go-57-login),
not account spoofing, edited manifests or logging out as a workaround.

The coordinator first prepares owner-only (`0700`) runtime directories outside
the checkout and evidence: `$PRIVATE_WORKSPACE/{home,expo-home,tmp}`. Choose a new
canonical private workspace; these are explicit paths, not historical defaults.
Use that same isolated HOME, Expo settings location and TMPDIR for official
`login --browser`, `whoami` and Metro. Never read/copy Expo credential files,
record raw auth sessions, or place private homes under evidence. Keep telemetry
disabled with `EXPO_NO_TELEMETRY=1`.

**Unset `EXPO_OFFLINE` for both login and Metro.** In the installed Expo 57 CLI,
offline mode prevents resolving the logged-in account for `expoGo.username` in
the served manifest. This supersedes the earlier offline-Metro preflight advice.
It does not authorize a tunnel, dependency installation or build.

In the coordinator's already-isolated private shell, using the existing Node
and Expo CLI paths (no `npx` download):

```sh
unset EXPO_OFFLINE
export EXPO_NO_TELEMETRY=1
"$NODE" "$EXPO_CLI" login --browser
export NATIVE_EXPECTED_EXPO_USERNAME="$("$NODE" "$EXPO_CLI" whoami)"
```

Do not print/persist that username as test evidence. Confirm the same account in
Expo Go through the official UI. Finish this authentication **before** starting
the finite-lifetime HTTP fixture and preparing its QR, rather than spending its
timer on browser login.

## Validate the served manifest and development JavaScript

The coordinator prepares a private Expo development project whose entry imports
`index.ts`, with this directory and the existing dependency directory in Metro's
public `watchFolders`/`resolver.nodeModulesPaths`. Apply `withSharedExpo` from
`metro.cjs` to the resulting config, passing that same dependency directory.
It adds only the public `resolver.extraNodeModules.expo` package mapping. Expo57
resolves its HMR replacement from the fixture project root after clearing
`nodeModulesPaths`; the explicit package mapping keeps the real installed Expo
HMR module reachable. Do not disable HMR or patch Expo/React Native internals.
Dependencies are read-only;
there is no symlink, install, export or native build. Use isolated HOME, Expo
state, TMPDIR and Metro caches. Do not reuse the user's Metro server or App entry.
Metro stays on the separately coordinated private port 8082, with offline mode
unset and telemetry disabled.

Supply `NATIVE_PROBE_BASE_URL` with the **fresh** server URL from
[the synthetic HTTP fixture](../realtime-native-server.md). Never reuse a previous
run prefix. LAN host/ports require explicit coordination. Before handing off the
QR, save the **actual served manifest for the target platform**, not `expo config` output, and run the
pure guard below. Keep raw account-bearing manifest data private; retain only
the sanitized guard result in evidence.

```sh
# Independent expected values from the launch configuration, never from the
# observed manifest itself. Username above comes only from official whoami.
export NATIVE_EXPECTED_PLATFORM=ios # Use android for the independently verified Android run.
export NATIVE_EXPECTED_PROJECT_ROOT="$OWNED_PROBE_PROJECT" # explicit absolute new directory
export NATIVE_EXPECTED_SLUG="$OWNED_PROBE_SLUG"
export NATIVE_EXPECTED_METRO_ORIGIN="http://${PRIVATE_IPV4}:${METRO_PORT}"
"$NODE" ${REPO_ROOT}/mobile/test-support/native-gate0/preflight.cjs "$SERVED_MANIFEST_FILE"
```

The guard checks SDK 57, isolated project/`index` entry, the single expected
`ios`/`android` launch-asset platform, private Metro origin,
exact nonempty expected `expoGo.username`, and the current
`NATIVE_PROBE_BASE_URL`. It never changes or signs manifest metadata, reads
credentials, or makes network requests. Missing/mismatched accounts and stale
URLs fail with fixed diagnostic codes. Its successful `nativeIo: NOT_RUN`
means **manifest readiness only**, never an SSE/native PASS. The exported
`validateServedManifest(manifest, expected)` helper supports the same pure check.

Project root, slug and private origin are required independent inputs; there is
no historical temporary-root or interface-IP fallback.

A manifest PASS alone cannot prove its JavaScript resolves. Before handing off
the QR, also run the real development-payload regression against the running
fixture (it follows the manifest launch asset, not an export/build command):

```sh
NATIVE_EXPECTED_PLATFORM=ios NATIVE_METRO_ORIGIN="$NATIVE_EXPECTED_METRO_ORIGIN" "$NODE" --test \
  "$REPO_ROOT/mobile/test-support/native-gate0/metro-dev.test.cjs"
```

Set `NATIVE_EXPECTED_PLATFORM=android` for Android; both the served manifest
request and its development asset must match. Omitting the variable preserves
the earlier iOS command. Wrong/missing/ambiguous asset platforms fail rather
than treating iOS readiness as Android proof.

It requires HTTP200 JavaScript containing the standalone panel and real Expo HMR
module. An HTTP500 Metro error is a failure even when the manifest was valid.
The test neither runs the JS in a native client nor calls bootstrap/stream.
`metro.test.cjs` separately verifies lookup/alias preservation; neither check
constitutes native I/O evidence.

Only after both checks pass open the test client by scanning its separate QR, not by
launching the phone programmatically. Press **Run isolated native I/O probe** once.
If the fixture expired while preparing the handoff, obtain a fresh URL and repeat
the actual-served-manifest guard before rescanning.

A run displays `PASS`, `FAIL` or `INCONCLUSIVE`, runtime versions, bounded stage
codes and cleanup state. Report upload failures are inconclusive, not passes.
The screen logs only sanitized metadata/codes/booleans. Never copy cookies, ACK
tokens, device identifiers or raw exception traces into acceptance reports.

## Failure and cleanup

Requests and reads are bounded; the synthetic server additionally has a 30-second
stream deadline. The probe never uses a timer to pretend incremental delivery or
abort success. A malformed server report, including truthy strings instead of
booleans, cannot pass.

`reader.cancel()` is fallback cleanup **only after a failed result is recorded**;
it cannot establish abort success. The final reset expires only this run's
cookie, after result delivery and abort observation. If reset fails, the UI marks
cleanup pending; that cookie expires after at most 120 seconds from bootstrap.
Never clear the shared cookie jar. Each fixture permits one stream: restart the
fixture and supply its new URL before repeating.

## Tests and evidence

Permanent tests are in `__tests__`: controlled stream sequencing, denial and
malformed data, strict reports, abort attribution, cookie cleanup, sanitized
failures, deliberate button activation and explicit fetch API wiring. The Expo
UI test uses mocked metadata; its PASS log must not be copied as phone evidence.
The separate pure preflight regression suite runs with existing Node only:

```sh
"$NODE" --test mobile/test-support/native-gate0/preflight.test.cjs
```

The coordinator keeps exact commands, RED/GREEN logs, typecheck diagnostics,
private project configuration, QR and actual native results under the isolated
run's `evidence/gate0-native` directory. Each fresh run starts **NOT_RUN**; only
an actual supported client result reviewed alongside server observations may
change that run's status. The completed physical iOS result above is limited to
native I/O. Production App/auth/transport integration remains unimplemented.

## Owned Android execution

The panel and probe use `Platform.OS` and explicit Expo fetch unchanged. An
owned emulator may use private ADB reverse for the fixture and Metro ports with
matching `127.0.0.1` origins; port forwarding is setup, not native proof.
A fresh copied launcher supplies `NATIVE_EXPECTED_PROJECT_ROOT` and
`NATIVE_EXPECTED_SLUG` independently to both checks; `NATIVE_METRO_ORIGIN`
identifies its explicitly allocated port, never original8081. Only one
coordinator controls ADB input at a time. Keep the synthetic cookie's unique name
and path, the stream/fixture deadlines and closed report contract unchanged.

After Android manifest plus development-JavaScript checks pass, open only the
owned guest's isolated entry and press the probe button once. Preserve its actual
Android metadata, screenshot and matching server observations before cleanup.
iOS native evidence is never substituted for Android. Real-App fixtures have
separate fresh-hostname/storage guards and a separate representative campaign.
