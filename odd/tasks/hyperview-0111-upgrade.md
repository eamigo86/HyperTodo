# Hyperview 0.111.0 local adoption

Upgrade the original Django package's active validation contract and HyperTodo's mobile client without altering historical 0.110.0 artifacts. This is local-only work; no push, release, remote mutation, real database, or seeding is authorized.

## Scope and constraints

- Package: `/Users/eamigo/Documents/Work/django-hv`; preserve its 12 pre-existing Admin editor/validation changes and the public 0.110.0 upstream-inspection helper.
- Consumer: `/Users/eamigo/Documents/Mis Tests/dj-hyperview-test`; pin only the mobile Hyperview dependency to 0.111.0 and update any version report/tests that are genuinely hard-coded.
- Strict TDD from current AGENTS instructions: observe RED on 0.110.0, then GREEN with the change, then refactor and run applicable checks. Do not remove the existing offline refresh/logging fallback without client-level proof.
- Keep React Navigation 6, Expo 57, and RN 0.86.3; the new `content-insets` attribute is opt-in, so existing templates must remain unchanged.
- Public upstream evidence: [Hyperview v0.111.0](https://github.com/Instawork/hyperview/releases/tag/v0.111.0), [v0.110.0...v0.111.0](https://github.com/Instawork/hyperview/compare/v0.110.0...v0.111.0), issue #1348 / PR #1350.
- Delivery strategy: ask-on-risk. Current authored estimate is about 225 lines in the package repository and 181 in HyperTodo, counted separately for their independent branches. Copied upstream XSDs, generated catalogs/revision manifest, the lockfile, and the package's pre-existing Admin changes are excluded. These are review estimates, not code-size targets; reassess before either commit if that repository crosses 400.
- Parent owns commits, native review, and delivery. This worker must not commit.

## Tasks

- [x] **T1 — Package compatibility.** Route: delegated writer (multiple non-trivial files). Preserve historical 0.110.0 resources and helper semantics; add verified versioned 0.111.0 upstream resources and a separately identified corrected active overlay. Keep validation, registry cache, catalog, and extension collision checks on that same new contract. Acceptance: tests first RED, then valid `content-insets` only where upstream allows it, invalid boolean/other attributes rejected, extension cannot redefine it, prior registry/reuse tests and historical integrity remain green. Checks: focused package pytest; package full pytest when feasible; Ruff check-only; diff check. Local commit: `4de79a4`; functional checks passed; automated review awaits consent.
- [x] **T2 — Mobile issue #1348 upgrade.** Route: delegated writer (multiple non-trivial files). Add mounted Hyperview regression coverage reproducing failure on 0.110.0 for HTTP 500, network rejection, clean-up/onEnd and successful retry, while intentional NO_OP drop stays distinct. Pin Hyperview 0.111.0 with a focused lockfile change. Acceptance: observed RED before bump and GREEN after, no unrelated dependency migration; existing offline-refresh fallback retained unless proven unnecessary. Checks: focused Jest, full Jest, typecheck. Local commit: `9570d52`; functional checks passed; review assessed medium/under_budget.
- [x] **T3 — Integration and documentation.** Route: delegated writer (cross-repository compatibility and documentation). Verify backend's About/client version reporting and update only if hard-coded; test backend against the local package candidate with proven import provenance while keeping its released b1 pin. Add concise Unreleased/readme impact notes distinguishing new XSD attribute from the client lifecycle fix. Acceptance: backend compatibility/config/About checks, accurate docs, no fake published package version, no SSE server protocol change. Checks: isolated backend test DB only; diff check. Local commits: `4de79a4` and `9570d52`; native-device acceptance remains pending.

## Progress and verification

- Local feature branches created in both original repositories from package `45d537e` and HyperTodo `b2f016a`.
- Package's 12 pre-existing dirty-file changes are preserved. Only the changelog gained a new upgrade entry alongside its existing Admin entry; stage that new content separately, never the whole dirty file set.
- Strict TDD runner candidates (verify exact installed commands before running): package `uv run pytest`; mobile `corepack yarn test`, `corepack yarn typecheck`; backend `uv run --no-sync python manage.py test`.
- T1 observed RED: 14 active-schema failures on 0.110.0. GREEN: new 0.111.0 contract 21 passed; focused package suite 241 passed; full package suite 1,979 passed, 159 skipped (five expected schema-safety warnings). Targeted Ruff check/format and `git diff --check` passed. Rollback: remove only the new 0.111.0 directory and schema/runtime/docs/tests upgrade hunks, not the old resources or Admin work.
- T2 observed RED: four mounted 0.110.0 failures (HTTP 500 and network rejection, indicators and pull refresh). GREEN: 5 new tests, focused new+offline 25 tests/2 suites, full mobile Jest 826 tests/51 suites, and TypeScript typecheck passed. Exact lockfile delta is only `hyperview` 0.110.0→0.111.0; existing fallback and Navigation 6 remain. Rollback: revert the dependency, lock hunk, new test, and related mobile notes only.
- T3 local candidate provenance: `PYTHONPATH=/Users/eamigo/Documents/Work/django-hv/src` imported that schema module (0.111.0), while installed distribution metadata remained b1. `manage.py test` discovered 0 pytest-function tests; actual isolated `uv run --no-sync pytest -o addopts=""` for schema compatibility, config and About passed 35 tests. No About Hyperview version hard-code was found; no backend dependency edit. Rollback: documentation only.
- Manual native-device acceptance remains pending. No build, real database modification, seed, push or release was performed. Local commits: package `4de79a4`, HyperTodo `9570d52`. The parent repeated all five mounted fragment lifecycle regressions successfully.
- Native review assessment: package medium/slice_budget_reached (24 paths and 14,134 total lines including copied/generated schema assets), awaiting per-candidate consent; HyperTodo medium/under_budget (8 paths, 189 total lines), no review due. Existing Admin edits remain uncommitted and outside the reviewed package commit.

## Next step

Await user consent for the package review, then complete the exact bound native review or record its candidate-scoped decline. User reviews local commits and performs native-device acceptance before any separately authorized push or release.
