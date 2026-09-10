# Portable test support

Normal Expo Go startup uses the normal App and the root Makefile/README. Set
`EXPO_PUBLIC_ALLOW_LOCAL_API=1` explicitly for an approved local HTTP API; the
guard, session ownership and cookie/CSRF contract are unchanged. The helpers
below are for **isolated tests**, not a replacement startup path for personal data.

## Choose independent roots

- `sourceRoot`: the canonical `mobile` directory. Default: the helper's own repo.
- `dependencies`: existing readonly `node_modules`. Default: under `sourceRoot`.
- `projectRoot`: a **new** canonical directory outside both roots, ending in
  `sse-demo-<run>/metro` or `native-app-<run>/metro`. Symlink ancestors are rejected.
- SSE demo `sourceManifest` and `sourceManifestSha256`: an external reviewed
  portable inventory and its independently pinned digest. No historical evidence
  file is an executable default, and verification never silently refreshes hashes.

The backend handoff is still `run` + `apiOrigin`; credentials stay in its private
workspace. No passwords, cookies or binding values enter expectations or the
bundle. The demo uses DefaultApp's ordinary storage keys, so it requires a **fresh
disposable Simulator**. Do not run it in a personal Expo Go container.

Use [the demo procedure](../test-support/sse-demo/README.md) for manifest review,
preparation and exact-file cleanup, or [the native fixture procedure](../test-support/native-app/README.md)
for isolated credential/theme keys and diagnostic controls. Neither helper starts
Expo, DNS, a device, Redis or a backend, installs dependencies, or builds anything.

## Repeat checks without a native launch

From the checkout root, use an existing Node 24 binary and dependency directory:

```sh
REPO_ROOT=$(pwd -P)
NODE=${NODE:-node}
MODULES=${MODULES:-"$REPO_ROOT/mobile/node_modules"}
NATIVE_TEST_NODE_MODULES="$MODULES" "$NODE" --test \
  mobile/test-support/source-portability.test.cjs \
  mobile/test-support/sse-demo/*.test.cjs \
  mobile/test-support/native-app/launcher.test.cjs \
  mobile/test-support/native-app/preflight.test.cjs \
  mobile/test-support/native-gate0/preflight.test.cjs \
  mobile/test-support/native-gate0/metro.test.cjs
```

These tests copy source/templates into owned temporary directories, exercise
relocation and rejection cases, and remove only their own test files. Four App
suites read backend XML relative to their test files rather than the process's
working directory or a maintainer's checkout. Existing full Jest/typecheck commands
remain unchanged; an external readonly dependency root needs an explicit resolver
adapter, not a symlink or a guessed `NODE_PATH` TypeScript override.

`native-gate0/metro-dev.test.cjs` is a separate **served HTTP** acceptance check;
it requires explicit project root, slug and private origin. Do not run it in an
offline unit-test command. Its companion pure preflight tests remain offline.

## Evidence boundaries

Old Gate0/SSE native records retain their original run IDs, hashes and paths.
Relocation tests and adoption of published a21 do not make those historical runs
new a21 native evidence. Current manifest counts are reported, not forced to the
old 109-source checkpoint. The source inventory covers JS/TS, JSON and `yarn.lock`;
dependencies and assets are not claimed as hash-verified by that inventory.
