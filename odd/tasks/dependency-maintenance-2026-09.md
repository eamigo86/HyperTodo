# HyperTodo dependency maintenance — September 2026

Align the existing Expo SDK 57 installation with its own Doctor recommendations and refresh compatible Python patch releases. The original local-only preparation honored the user's request for notice before commit or push; the user later authorized delivery. The reviewed implementation is committed locally, while hosted CI remains pending.

## Scope and guardrails

- Repository: the original HyperTodo checkout on `chore/dependency-maintenance-2026-09`, branched from clean main `3fd7d3f`.
- Keep the Expo SDK 57 line, React Native 0.86.3, React 19.2.3, React Navigation 6, Hyperview 0.111.0, and `dj-hyperview[editor,realtime]==0.1.0b2` unchanged. Do not suppress Doctor or weaken coverage/tests.
- Use public unauthenticated npm and PyPI artifacts only. No native build, real database, migration application, seeding, Redis service mutation, PR, or release. The initial no-commit/no-push hold was honored; the user subsequently authorized parent-owned commit and push.
- Strict TDD is enabled by AGENTS. The permanent `mobile/scripts/doctor.cjs` quality gate and its `mobile/__tests__/doctor-command.test.ts` coverage already exist; record a real Doctor RED before patching, then GREEN. Mechanical Python lock updates need regression checks, not invented behavior failures.
- Delivery strategy: the original local hold overrode automatic work-unit commits until the user was notified and explicitly authorized commit/push. Forecast under 200 authored lines excluding generated lockfiles; no size-driven compression. The combined implementation work unit is committed as `ae3e62455fb232faceeccb14e5a36eedf1eb82c6`; parent owns remote delivery and hosted CI.

## Tasks

- [x] **M1 — Expo SDK 57 patch alignment.** Route: delegated writer; multiple package/lock edits and verification. Confirm the eight Doctor-recommended patch versions exist in the public npm registry; update only those eight Expo packages and their lockfile resolutions, with no SDK/React/Navigation/Hyperview migration. Acceptance: baseline CI-style Doctor RED, then Doctor GREEN without exclusions; focused Doctor contract tests, typecheck, and full Jest remain green. Rollback: revert the eight manifest entries and their lockfile changes only.
- [x] **M2 — Compatible Python refresh.** Route: delegated writer; inspect current direct/transitive locks and public PyPI stable releases before selecting updates. Keep Django 6.1.1 if no newer 6.1 patch exists; retain exact dj-hyperview beta2. Selected stable candidates within existing bounds: coverage 7.16.0→7.16.1, tzdata 2026.3→2026.4, Ruff 0.16.6→0.16.8 after release-note review. Do not pull django-redis 7, redis 8, or uvicorn 0.53 without separate compatibility justification. Acceptance: only selected registry lock changes, complete backend quality/coverage, Ruff format check, Django check/migration dry run. Rollback: revert Python lock changes only.
- [x] **M3 — Verification and handoff.** Route: delegated writer; run the existing CI-style Doctor with `EXPO_PUBLIC_API_URL=https://hypertodo-ci.invalid/hv/` and `ALLOW_LOCAL_API=0`, typecheck, full Jest, `make backend-quality`, `uv lock --check`, Ruff format check, provenance, and `git diff --check`. Record exact RED/GREEN, changed/unchanged/deferred versions, failures/skips, and any device-only pending check. Read back this file and its full Engram mirror. At the initial handoff, leave source and task edits uncommitted and notify the user before commit or push; the later authorization and local commit are recorded below.

## Evidence and decisions

- Baseline consumer CI [run 36038814180](https://github.com/eamigo86/HyperTodo/actions/runs/36038814180): backend passed; mobile Jest passed 51 suites/826 tests, but Expo Doctor 1.20.4 passed 20/21 checks and rejected eight older SDK 57 patch versions. This was the baseline before maintenance edits.
- [Expo SDK 57 release notes](https://expo.dev/changelog/sdk-57) and [Expo CLI version-check guidance](https://docs.expo.dev/more/expo-cli/) confirm the SDK/RN line and immutable CI validation. Public npm metadata confirms all eight recommended 57.0.x packages exist.
- Public PyPI current stable releases as checked 2026-09-24: Django 6.1.1 is the latest 6.1 patch; coverage 7.16.1, tzdata 2026.4, and Ruff 0.16.8 are newer compatible candidates. [Coverage 7.16.1 notes](https://coverage.readthedocs.io/en/7.16.1/changes.html) list two fixes; [Ruff 0.16.7 and 0.16.8 notes](https://github.com/astral-sh/ruff/releases/tag/0.16.8) show preview additions and fixes, not a planned rule-set change. Validation passed as recorded below.

- M1 TDD: the unchanged CI-style Doctor exited 1 with 20/21 checks and the same eight patch mismatches. After updating only those eight manifest entries and their required SDK 57 transitive lock entries, Doctor passed 21/21 with no exclusion. Mobile typecheck passed. First full Jest run exposed one newly stale native Gate 0 test assertion (`expoVersion` literal `57.0.21` versus installed `57.0.25`): 825 passed, 1 failed. The test now reads the installed `expo/package.json` version; focused GREEN 1/1 and final full GREEN 826/826 across 51 suites. Watchman permission fallback to the Node crawler did not prevent tests. No native runtime/device acceptance was performed.
- M2 resolution: `uv lock --upgrade-package` changed only coverage 7.16.0→7.16.1, Ruff 0.16.6→0.16.8 and tzdata 2026.3→2026.4; `uv sync --no-build` updated the two locally applicable wheels. `tzdata` has a Windows-only lock marker and is not installed on macOS, so an initial read-only script that required local tzdata metadata exited 1; the corrected installed-package provenance check passed and dj-hyperview remains installed from `.venv` at exact 0.1.0b2 with schema 0.111.0. Full `make backend-quality` passed: 1,579 pytest passed, 6 skipped, 99.05% coverage, installed Admin JS 1 passed, Ruff passed, Django check clear and migration dry run found no changes. `uv lock --check` and Ruff format check (109 files) passed. All other 23 Python lock package versions remain unchanged.

- M3 final checks: offline frozen Yarn install with scripts disabled left `mobile/yarn.lock` SHA-256 `45dd97daee07b5efa9a6cd7ee162c73d21b9ec9a92e183ead2799f09e12231cd` unchanged; CI-style Doctor passed 21/21, final TypeScript check passed, and final full Jest passed 826/826. Backend full quality passed as above; `uv lock --check`, Ruff format check (109 files), installed dj-hyperview 0.1.0b2/schema 0.111.0 provenance, and `git diff --check` passed. Scope audit found exactly eight Expo manifest edits, 25 changed lock package names all in the Expo/Babel SDK family, and exactly three changed Python lock package versions. Expected baseline peer-dependency and Watchman fallback warnings remain; no test failures remain. Hosted CI (mobile Node 22.19.0; backend Python 3.14) and manual native-device checks were not run locally.

- Delivery authorization and review: after the local hold and notification, the user explicitly authorized commit/push and required all hosted GitHub CI to pass. Parent committed the exact reviewed implementation tree `b893c715` as `ae3e62455fb232faceeccb14e5a36eedf1eb82c6`. Native reliability review `59f0a887323fed67` for target `81013f8d` was approved with no findings; exact acknowledgement burned authority at revision `22d240b9`. This is not a hosted CI result or native-device proof. Parent will deliver and wait for all CI jobs.

## Version decisions

| Package group | Before → after | Reason |
| --- | --- | --- |
| Expo core | `expo` 57.0.21 → 57.0.25 | SDK 57 Doctor recommendation. |
| Expo build/dev | `expo-build-properties` 57.0.17 → 57.0.22; `expo-dev-client` resolved 57.0.18 → 57.0.19 | SDK 57 Doctor recommendation. |
| Expo media | `expo-image-manipulator` and `expo-image-picker` 57.0.16 → 57.0.20 | SDK 57 Doctor recommendation. |
| Expo security | `expo-local-authentication` 57.0.2 → 57.0.3; `expo-secure-store` 57.0.3 → 57.0.4 | SDK 57 Doctor recommendation. |
| Expo splash | `expo-splash-screen` 57.0.8 → 57.0.9 | SDK 57 Doctor recommendation. |
| Expo transitives | SDK 57 `@expo/*`, `babel-preset-expo`, `expo-asset`, `expo-constants`, `expo-modules-*` and related patches | Required by the selected core/peer manifests; no unrelated JS family was updated. |
| Python test/runtime support | `coverage` 7.16.0 → 7.16.1; `ruff` 0.16.6 → 0.16.8; Windows-only `tzdata` 2026.3 → 2026.4 | Stable in-bound patches; upstream fixes reviewed and backend quality remains green. |
| Unchanged | Django 6.1.1 (latest 6.1 patch), dj-hyperview 0.1.0b2, Redis 7.4.1, uvicorn 0.52.4; React 19.2.3, RN 0.86.3, Navigation 6, Hyperview 0.111.0 | Exact pins or latest selected compatible line retained. |
| Deferred | django-redis 7, Redis 8, uvicorn 0.53, Expo SDK 58 | Outside the existing version bounds or this patch-only scope; no major/0.x feature-line migration. |

## Next step

Parent fast-forwards and pushes the reviewed implementation plus this documentation to main, then waits for every GitHub CI job to pass. Hosted mobile Node 22.19.0, backend Python 3.14, and real-device acceptance remain pending; no push, PR, release, or native build is claimed here.
