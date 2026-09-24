# Hyperview 0.111.0 local adoption

Upgrade the original Django package's active validation contract and HyperTodo's mobile client without altering historical 0.110.0 artifacts. This is local-only work; no push, release, remote mutation, real database, or seeding is authorized.

## Scope and constraints

- Package: `/Users/eamigo/Documents/Work/django-hv`; preserve its 12 pre-existing Admin editor/validation changes and the public 0.110.0 upstream-inspection helper.
- Consumer: `/Users/eamigo/Documents/Mis Tests/dj-hyperview-test`; pin only the mobile Hyperview dependency to 0.111.0 and update any version report/tests that are genuinely hard-coded.
- Strict TDD from current AGENTS instructions: observe RED on 0.110.0, then GREEN with the change, then refactor and run applicable checks. Do not remove the existing offline refresh/logging fallback without client-level proof.
- Keep React Navigation 6, Expo 57, and RN 0.86.3; the new `content-insets` attribute is opt-in, so existing templates must remain unchanged.
- Public upstream evidence: [Hyperview v0.111.0](https://github.com/Instawork/hyperview/releases/tag/v0.111.0), [v0.110.0...v0.111.0](https://github.com/Instawork/hyperview/compare/v0.110.0...v0.111.0), issue #1348 / PR #1350.
- Delivery strategy: ask-on-risk. Current authored estimate is about 225 lines in the package repository and 181 in HyperTodo, counted separately for their independent branches. Copied upstream XSDs, generated catalogs/revision manifest, the lockfile, and the package's pre-existing Admin changes are excluded. These are review estimates, not code-size targets; reassess before either commit if that repository crosses 400.
- Parent owns native review and delivery. The user separately authorized one local, no-source-change history-slicing pass for the package commit; no PR or remote action was authorized.

## Tasks

- [x] **T1 — Package compatibility.** Route: delegated writer (multiple non-trivial files). Preserve historical 0.110.0 resources and helper semantics; add verified versioned 0.111.0 upstream resources and a separately identified corrected active overlay. Keep validation, registry cache, catalog, and extension collision checks on that same new contract. Acceptance: tests first RED, then valid `content-insets` only where upstream allows it, invalid boolean/other attributes rejected, extension cannot redefine it, prior registry/reuse tests and historical integrity remain green. Checks: focused package pytest; package full pytest when feasible; Ruff check-only; diff check. Original local commit: `4de79a4` (preserved at the T4 backup ref, superseded on the feature branch by five slices); functional checks passed; four prerequisite slices are approved, while the activation slice remains in `correction_required`.
- [x] **T2 — Mobile issue #1348 upgrade.** Route: delegated writer (multiple non-trivial files). Add mounted Hyperview regression coverage reproducing failure on 0.110.0 for HTTP 500, network rejection, clean-up/onEnd and successful retry, while intentional NO_OP drop stays distinct. Pin Hyperview 0.111.0 with a focused lockfile change. Acceptance: observed RED before bump and GREEN after, no unrelated dependency migration; existing offline-refresh fallback retained unless proven unnecessary. Checks: focused Jest, full Jest, typecheck. Local commit: `9570d52`; functional checks passed; review assessed medium/under_budget.
- [x] **T3 — Integration and documentation.** Route: delegated writer (cross-repository compatibility and documentation). Verify backend's About/client version reporting and update only if hard-coded; test backend against the local package candidate with proven import provenance while keeping its released b1 pin. Add concise Unreleased/readme impact notes distinguishing new XSD attribute from the client lifecycle fix. Acceptance: backend compatibility/config/About checks, accurate docs, no fake published package version, no SSE server protocol change. Checks: isolated backend test DB only; diff check. Original package commit `4de79a4` (now backup) and HyperTodo commit `9570d52`; native-device acceptance remains pending.
- [x] **T4 — Local package review slices.** Route: delegated writer (Git history only). Preserve the original package commit, split its exact tree into coherent local prerequisites and final activation, and prove the original tree and 12 pending Admin files/index are unchanged. Acceptance: ordered conventional commits, immutable backup ref, exact final-tree equality, focused integrity checks, no native review claim. Local package commits: `ab346136` → `9905d199` → `e1ed5181` → `ee9957ff` → `cc6abae2`. No PR was created.

## Progress and verification

- Local feature branches created in both original repositories from package `45d537e` and HyperTodo `b2f016a`.
- Package's 12 pre-existing dirty-file changes are preserved. Only the changelog gained a new upgrade entry alongside its existing Admin entry; stage that new content separately, never the whole dirty file set.
- Strict TDD runner candidates (verify exact installed commands before running): package `uv run pytest`; mobile `corepack yarn test`, `corepack yarn typecheck`; backend `uv run --no-sync python manage.py test`.
- T1 observed RED: 14 active-schema failures on 0.110.0. GREEN: new 0.111.0 contract 21 passed; focused package suite 241 passed; full package suite 1,979 passed, 159 skipped (five expected schema-safety warnings). Targeted Ruff check/format and `git diff --check` passed. Rollback: remove only the new 0.111.0 directory and schema/runtime/docs/tests upgrade hunks, not the old resources or Admin work.
- T2 observed RED: four mounted 0.110.0 failures (HTTP 500 and network rejection, indicators and pull refresh). GREEN: 5 new tests, focused new+offline 25 tests/2 suites, full mobile Jest 826 tests/51 suites, and TypeScript typecheck passed. Exact lockfile delta is only `hyperview` 0.110.0→0.111.0; existing fallback and Navigation 6 remain. Rollback: revert the dependency, lock hunk, new test, and related mobile notes only.
- T3 local candidate provenance: `PYTHONPATH=/Users/eamigo/Documents/Work/django-hv/src` imported that schema module (0.111.0), while installed distribution metadata remained b1. `manage.py test` discovered 0 pytest-function tests; actual isolated `uv run --no-sync pytest -o addopts=""` for schema compatibility, config and About passed 35 tests. No About Hyperview version hard-code was found; no backend dependency edit. Rollback: documentation only.
- Manual native-device acceptance remains pending. No build, real database modification, seed, push or release was performed. Original local commits: package `4de79a4` (now backup), HyperTodo `9570d52`; the package feature branch now ends at `cc6abae2`. The parent repeated all five mounted fragment lifecycle regressions successfully.
- Original monolithic package candidate assessed medium/slice_budget_reached (24 paths and 14,134 total lines including copied/generated schema assets); its START refused with `lens_context_budget_exceeded`. Four replacement prerequisite slices have approved native verdicts and burned acknowledgement authority; the fifth activation slice remains `correction_required` without approval. HyperTodo assessed medium/under_budget (8 paths, 189 total lines), no review due. Existing Admin edits remain uncommitted and outside the package upgrade commits.

## Local package review boundaries (T4)

The user authorized one honest local history-slicing pass after native START refused the monolithic `4de79a4` candidate with `lens_context_budget_exceeded`. The original commit remains at `refs/backup/hyperview-0111-original-4de79a4`. Every row depends on its predecessor; there is no PR chain or independent publication claim. `Lines` means additions plus deletions against the listed parent. `Bytes` is the sum of complete new blobs in that row, not a review-budget verdict.

| Slice | Commit (parent) | Cohesive boundary | Paths | Lines | Blob bytes |
| --- | --- | --- | ---: | ---: | ---: |
| 1 | `ab346136` (`45d537e`) | Exact upstream XSD set, MIT license, hash provenance JSON | 6 | 1,609 | 60,940 |
| 2 | `9905d199` (`ab346136`) | Indivisible generated upstream catalog | 1 | 5,640 | 120,682 |
| 3 | `e1ed5181` (`9905d199`) | Audited compatibility and corrected r3 XSD overlays | 2 | 888 | 39,098 |
| 4 | `ee9957ff` (`e1ed5181`) | Indivisible corrected catalog and manifest | 2 | 5,780 | 129,396 |
| 5 | `cc6abae2` (`ee9957ff`) | Runtime activation, regression tests, and documentation together | 13 | 217 | 144,990 |

Inactive asset prerequisites did not change runtime behavior. Their rollback boundary is each listed commit; final activation is reversible independently, while the backup retains the original unsliced tree. The final tree is exactly `762b586a89a291a44ffc83b9e32554e1d9c0d011`, matching original `4de79a4^{tree}`. The 12 pending Admin-file SHA-256 manifest (`sorted path\0digest\n`) matched before and after: `48db5bf47428ad39e5ca54686203724afa4f3f68c42e247f33efbe4a72788466`; normal index SHA-256 likewise remained `738dd8efdb2de2daaad0b3b80977078e4f4058cbf8d21c695bb0b6e115c60585`, with no staged paths. Focused checks after slicing: published XSD hashes, both deterministic catalogs, immutable slice blobs, and `git diff --check` passed; schema pytest focused suite passed 70 tests. Runtime harness for inactive assets: N/A; final tree is byte-identical to the earlier 1,979-pass full-suite candidate, so the full suite was not rerun.

### Native review outcomes

The first four local prerequisites were independently approved, with exact acknowledgement authority burned. The first approval carried an informational warning that tests are absent from its inactive-asset commit; regression tests remain with runtime activation.

| Slice | Native lineage | Outcome |
| --- | --- | --- |
| `ab346136` | `review-d621d455b47db86e` | Approved; inactive-asset test warning only |
| `9905d199` | `review-1b01e7e3028975c6` | Approved; no findings |
| `e1ed5181` | `review-4c458be10f63128e` | Approved; no findings |
| `ee9957ff` | `review-d55bcf21d53b8720` | Approved; no findings |
| `cc6abae2` | `review-69ca6b812577693f` | `correction_required`; no approval or correction submitted |

The fifth review targets `sha256:86f78d1766bee9a7c42024e3eb5337db3c938488037dd09618cb61f03486c0f8`. Its `R3-missing-active-schema-assets` claim says the active XSD, catalogs, manifest, and `PROVENANCE.json` are absent. Read-only `git ls-tree` inspection shows those assets in both the provider-bound candidate tree `762b586a89a291a44ffc83b9e32554e1d9c0d011` and base tree `98a04d8ebf5a9c46e0a557666873de630f07919b`. This contradicts the missing-assets premise, but does not resolve the native transaction or imply approval. No source correction, review decline, or provider-defect report has been submitted.

## Next step

Parent: obtain the user's choice for the provider-defect handoff while preserving the fifth review transaction; record its actual terminal outcome rather than assuming a pass. Manual native-device acceptance remains pending before any separately authorized push or release.
