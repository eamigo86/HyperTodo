# SSE demo — normal App, disposable iOS Simulator only

**Prepare and review; do not launch a guest or service with this helper.** The
generated entry registers the unchanged `DefaultApp`. Its actual `expo/fetch`
connection receives SSE; there is no Gate0 toolbar, injected hint, held Response,
observer or synthetic ACK. A real run was accepted with the limited scope below;
preparation checks alone never grant native acceptance.

## Historical native example — 2026-09-10 UTC

Run `8fedb272794b44ccaa57c8a3e25d0523` used normal DefaultApp, official Expo
Go57.0.9 and iOS26.5 in a fresh disposable Simulator. An actual Admin HTTP/CSRF
save changed A's visible task to “SSE renamed from Admin”; the unchanged Tasks
page1 updated automatically without client interaction or injected hints. One
actual OS background/foreground cycle retained the screen without reauthentication,
with the owned Redis subscriber count 1 → 0 → 1.

Evidence: `evidence/environment/sse-demo-8fedb272794b44ccaa57c8a3e25d0523/`
(screenshots, preflight and cleanup) and
`evidence/environment/sse-demo-backend-retry-20260910/` (Admin and subscriber
records). Guest, services and synthetic fixture were closed after the example.
This does not claim Android, physical-iPhone, concurrent-B-client or exhaustive
native fault coverage. Historical Gate0 checks remain separate evidence. This was a source-candidate run,
not native verification of the later published a21 package or relocated helpers.

## Prepare

1. Coordinator creates a **fresh disposable Simulator UUID**, with the verified
   official Expo Go SDK57. Never open this bundle in the user's phone, original
   Simulator or existing Expo Go data: DefaultApp uses its normal storage keys.
   The UUID below is an expected target, not proof the target is disposable.
2. Backend owner allocates the new SQLite fixture, run, private credentials and
   explicit realtime namespace. Take its sanitized ready record, not credential
   contents, to prepare config. Keep its finite lifetime at most600s. Use only the
   exact approved private interface and fresh API/Metro aliases, never8081.
3. Place expectations outside the bundle in a private0600 file. Its closed shape:

```json
{
  "run": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "apiOrigin": "http://hvt-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.local:8787",
  "metroOrigin": "http://hvtm-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.local:8082",
  "platform": "ios",
  "username": "independently-verified-account",
  "slug": "hypertodo-sse-demo",
  "mainModuleName": "index",
  "projectRoot": "/absolute/private-workspace/sse-demo-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/metro",
  "sourceRoot": "/absolute/checkout/HyperTodo/mobile",
  "dependencies": "/absolute/checkout/HyperTodo/mobile/node_modules",
  "sourceManifest": "/absolute/private-workspace/reviewed-mobile.json",
  "sourceManifestSha256": "replace-with-the-independently-reviewed-64-character-sha256",
  "simulatorUdid": "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE"
}
```

These are placeholders, not an active run. Credentials/passwords, cookies,
session bindings and tokens are never accepted or embedded. `extra` contains
**only** `apiUrl: <apiOrigin>/hv/`; the account and UUID are not in generated files.
Account expectations come from the official CLI flow, not its private auth files
or from the manifest being checked.

```sh
# From the HyperTodo checkout root, using an existing Node 24 interpreter.
REPO_ROOT=$(pwd -P)
NODE=${NODE:-node}
HELPER="$REPO_ROOT/mobile/test-support/sse-demo"
"$NODE" "$HELPER/launcher.cjs" "$PRIVATE_EXPECTATIONS"
```

`sourceRoot` defaults to the helper's containing `mobile` directory;
`dependencies` defaults to that source root's `node_modules`. When dependencies
are elsewhere, supply their absolute canonical path explicitly. No personal
checkout, temporary evidence directory or environment-specific default is used.
The output must end in `sse-demo-<run>/metro`, be outside source/dependency roots,
and be new. Existing paths, symlink ancestors and output/source overlap fail closed.

### Review the source manifest before preparation

The manifest is external, portable JSON: `{"version":1,"files":{"App.tsx":"<sha256>",...}}`.
It records **every** JS/TS source (including `.cts`, `.mts`, `.jsx`), JSON config
and `yarn.lock` under the source root. `node_modules`, `.git` and `assets` are
outside this source-only inventory; installed dependency versions are checked
separately. The source root itself is not embedded in the manifest.

Create a **draft**, inspect its complete inventory and diff against the intended
checkout, then pin its digest in the independent expectations file. This command
only gathers bytes; it does not approve the checkout or produce native evidence:

```sh
# MOBILE_ROOT and DRAFT_MANIFEST are absolute paths. Keep the draft outside mobile.
"$NODE" - "$MOBILE_ROOT" > "$DRAFT_MANIFEST" <<'JS'
const fs = require('node:fs'), path = require('node:path');
const {createHash} = require('node:crypto');
const root = process.argv[2];
const {sourceFiles} = require(path.join(root, 'test-support/sse-demo/preflight.cjs'));
const files = Object.fromEntries(sourceFiles(root).map(name => [name,
  createHash('sha256').update(fs.readFileSync(path.join(root, name))).digest('hex')]));
process.stdout.write(JSON.stringify({version: 1, files}, null, 2) + '\n');
JS
# After independent review, record the digest of these exact bytes:
"$NODE" -e 'process.stdout.write(require("node:crypto").createHash("sha256").update(require("node:fs").readFileSync(process.argv[1])).digest("hex")+"\n")' "$DRAFT_MANIFEST"
```

Never obtain expectations from the served manifest or silently refresh the digest
when a check fails. A missing, added or changed executable/config file fails the
inventory/byte check, even if all previously listed files still match. The helper
checks before and after Metro's response. Historical 109-root SSE2 evidence stays
historical; a current reviewed manifest reports its actual file count.

`prepareDemo(expected, dependencies?)` verifies that independent manifest plus
readonly Expo57.0.21/React19.2.3/RN0.86.3/Hyperview0.110.0 metadata, then creates
exactly five exclusive0600 files in a fresh0700 directory. Cleanup refuses unknown
files, file symlinks and changed content. The second dependency argument, if used,
must agree with expectations. The source manifest and dependencies are never deleted.

## Serve and preflight — explicit coordination

Reuse the reviewed [Metro proxy procedure](../native-app/metro-proxy.md): real
Expo CLI `--localhost` on an owned internal port; `EXPO_PACKAGER_PROXY_URL` set
before startup; set `EXPO_PUBLIC_ALLOW_LOCAL_API=1` for normal App HTTP; exact private-IP proxy and fresh Metro hostname. Check the actual
loopback address family. No build/export, dependency install, wildcard or tunnel.

After services are ready, run `preflight.cjs "$PRIVATE_EXPECTATIONS"`, or
`checkDevelopment(expected, {http?, readEntry?})` for the reviewed host adapter.
It checks independent source/account/SDK/API/entry and actual HTTP200 development
JavaScript/HMR, then rechecks the complete independently pinned source inventory.
The old Gate0 source guard/acceptance is not reused or weakened. The response is
consumed in memory with the existing bounded reader; no compiled bundle or raw
manifest is saved. It makes **no API requests**, credentials or auth mutations.

The normal App logger is unchanged and may produce raw SDK context. The
coordinator must discard raw Metro/App stdout/stderr and retain only closed
status/exit/counter summaries, never generic Error/context/body logs. A preflight
error is a fixed failure code, not proof about native behavior.

## Finish / evidence

Only root controls the exact Simulator UI. Sign in using the fixture credentials
through normal forms; perform the normal Admin edit on the synthetic database.
Before/after UI and independently captured server publication/owner routing prove
the demo—not a manually dispatched hint or successful collection alone.

Stop only owned guest/Metro/proxy/backend resources before cleanup. Destroy the
fresh Simulator and private fixture; never inspect or clear a shared cookie jar.
`cleanupDemo(expected, dependencies?)` deletes **only** the five unchanged generated
files and their empty directory. It refuses unknown files, symlinks or edits. The
coordinator first cleans its separately owned Metro cache; this helper does not
kill processes or recursively remove unknown artifacts. Preserve bounded evidence.

## Tests

```sh
cd "$REPO_ROOT"
NATIVE_TEST_NODE_MODULES="$MODULES" "$NODE" --test mobile/test-support/sse-demo/*.test.cjs \
  mobile/test-support/native-app/launcher.test.cjs \
  mobile/test-support/native-app/preflight.test.cjs \
  mobile/test-support/native-gate0/metro.test.cjs
```

`MODULES` is the existing readonly dependency root (normally `$REPO_ROOT/mobile/node_modules`).
These are host preparation controls with real files and controlled HTTP Responses;
they are **not** a native run, HMR proof, Redis proof or full SSE acceptance.
