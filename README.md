# HyperTodo

[![CI](https://github.com/eamigo86/HyperTodo/actions/workflows/ci.yml/badge.svg)](https://github.com/eamigo86/HyperTodo/actions/workflows/ci.yml)
[![dj-hyperview](https://img.shields.io/badge/dj--hyperview-0.1.0b1-278CFF)](https://pypi.org/project/dj-hyperview/0.1.0b1/)
[![Hyperview](https://img.shields.io/badge/Hyperview-0.110.0-171A2F)](https://www.npmjs.com/package/hyperview/v/0.110.0)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

HyperTodo is a test application for the
[dj-hyperview](https://github.com/eamigo86/dj-hyperview) package. It combines a
Django backend with an Expo mobile host that uses Hyperview to render native
screens from server-provided HXML.

The project exists to exercise dj-hyperview in a realistic application. It is
not intended to be a reusable task-management product.

## Quick start: SSE with Expo Go

Use two terminals: **ASGI backend + Expo Go**. No native build is needed.
The backend pins the published beta `dj-hyperview[editor,realtime]==0.1.0b1`, which
supports the contextual change metadata used by this app. Install the reviewed
package/app pair together. These instructions are not new native acceptance.

### Requirements

- Python 3.14 and [uv](https://docs.astral.sh/uv/).
- Node 22.19.0 through [nvm](https://github.com/nvm-sh/nvm), with Corepack.
- Expo Go compatible with this app's Expo SDK 57, on a phone or simulator.
- An existing Redis server at `redis://127.0.0.1:6379/15`, or a reviewed replacement
  in `backend/config/settings_sse.py`. Installing Python's Redis extra does not
  start a Redis server.
- For a phone: the computer and phone on the same reachable private network.
  Development HTTP and the Expo bundle are visible to that network; do not expose
  them publicly or use demo credentials with real data.

### 1. Install the project dependencies

From the repository root:

```console
make help
make setup
```

This installs the backend dependencies from `backend/uv.lock` and the mobile
packages from `mobile/yarn.lock`. No database migration or seed runs during setup.

### 2. Prepare a new demo database (fresh checkout only)

**Only use this section for a new, disposable local database.** If you already
have data or edited HXML templates, use the next section instead.

```console
make backend-migrate
make backend-seed
```

The local seed creates demonstration accounts and data. It can reset demo fields;
it is not an upgrade command. The development accounts are:

| User | Password | Purpose |
| --- | --- | --- |
| `admin` | `admin123` | Local Django Admin superuser. |
| `demo` | `demo123` | Regular owner with separate tasks and categories. |

### Existing database: update without seeding

After pulling the reviewed package/app pair, run `make setup` to synchronize its
dependencies. Take a verified backup and review the migration plan before applying
migrations deliberately. **Do not run `make backend-seed` to upgrade.** It changes
demo accounts/data and does not replace existing template edits.

The SSE development profile below uses filesystem HXML, leaving stored override
rows untouched. To use your DB-first profile instead, review its effective HXML
before enabling realtime; see [database override adoption](#adopt-database-overrides-explicitly).
Do not run old and new backend/package workers together on the same SSE namespace.

### 3. Start Redis and the SSE backend

Make sure your existing Redis service is running. `make lan-ip` prints a candidate
computer address; verify that it belongs to the network your phone can reach.
Replace `192.168.1.20` in **both** terminal commands below with that address.

```console
make lan-ip
# Backend terminal, repository root:
LAN_IP=192.168.1.20 make backend-run-sse
```

This runs Uvicorn with `config.settings_sse`, not Django's WSGI `runserver`.
It does not start Redis, migrate the database, seed data or rewrite DB templates.
The backend serves HXML at `/hv/`, the authenticated stream at `/realtime/events/`
and Django Admin at `/admin/`. Admin assets are served here only in development.
The connection subscribes after normal login; opening the stream URL in a browser
is not an SSE authentication test.

### 4. Open Expo Go

In the second terminal, from the same repository root:

```console
# Mobile terminal; use the SAME computer address:
LAN_IP=192.168.1.20 make mobile-start-go
```

Scan the QR code and open it in Expo Go. This target uses `expo start --go` and
explicitly permits the local HTTP API; the release HTTPS guard stays enabled.
Leave both terminals running. Allow the chosen development ports through your
local firewall only as needed. Stop each command with Ctrl+C when finished.

For a simulator on the same computer, the same two commands work with its
reachable host address. `make backend-run-sse` without `LAN_IP` binds loopback
only; a physical phone cannot reach that address. `make mobile-start` and
`make mobile-start-device` target a **development client**, not Expo Go, and the
older `backend-run*` targets use WSGI rather than SSE. They are not substitutes
for this pair.

### 5. Check Admin → Tasks updates

1. In Expo Go, sign in as `demo`, open **Tasks** and keep a visible task on screen.
2. In a browser, open `http://192.168.1.20:8000/admin/` and sign in as `admin`.
   Edit the **title** of that same task, preserving its owner, and save normally.
3. The owner's visible list should update **without** navigation, manual refresh
   or an injected hint. A small confirmation appears only after the refreshed
   document has actually rendered. Another account must not receive that task.
4. Edit a task or profile from the **same device**: its own operation should not
   produce a change-warning/refresh message. Existing explicit Save feedback stays.
5. Keep a form open, untouched or with an unsaved draft, then edit the same record
   from **another device** signed into the same account (or from Admin). Expect the
   same centered dialog: one short localized sentence naming the object and exactly
   **Update** and **Go back**. Both explicitly
   discard this draft: Update fetches the current form; Go back refreshes the exact
   previous page before showing it. Go back is disabled if that page is unavailable
   or has unsaved edits. An unrelated task must not trigger that form conflict.

These are manual acceptance steps, **not a claim of new native verification**.
The [contextual-update guide](mobile/docs/realtime-contextual-updates.md) covers
silent login/resync, stale-route entry, draft races and list limits: preserve the
loaded prefix and filters up to 20 pages/400 rows; above that, refresh page 1 with
the same filters. Exact pixel anchoring after removed/resized rows is not promised.

## Realtime configuration

The normal `config.settings` remains DB-template-first with realtime disabled.
Its complete HYPERVIEW configuration is:

```python
HYPERVIEW = {
    "TEMPLATE_DIRS": [BASE_DIR / "hyperview"],
    "SOURCES": [
        {
            "BACKEND": "dj_hyperview.contrib.database.sources.DatabaseSource",
            "OPTIONS": {"using": "default"},
        },
        {"BACKEND": "dj_hyperview.sources.FileSystemSource"},
    ],
    "ADMIN": {"EDITOR": True},
    "EXTRA_SCHEMAS": [BASE_DIR / "schema" / "hypertodo.xsd"],
    "SCHEMA_EXTENSIONS": schema_extensions(),
    "REALTIME": None,
}
```

`BASE_DIR` and `schema_extensions` are already defined/imported in
`backend/config/settings.py`. The explicit `config.settings_sse` profile preserves
this configuration except for filesystem-only `SOURCES` and this transport block:

```python
HYPERVIEW["REALTIME"] = {
    "REDIS_URL": "redis://127.0.0.1:6379/15",
    "NAMESPACE": "hypertodo-development",
}
```

Edit that development block if your Redis endpoint differs. The namespace
identifies this app/environment: Redis PubSub is not isolated by database number.
This block does not configure CACHE, and the Make variable `REDIS_URL` used by the
older cache targets does not override it. Authentication, tasks, sessions, CSRF,
schema extensions and the existing database/cache configuration are preserved.

The development SSE profile **does not read DB override rows as templates,
rewrite or delete them**. For reviewed DB overrides, preserve the full normal
mapping, set its `REALTIME` section explicitly, and serve `config.asgi:application`
with ASGI. Omitted/None disables transport; schema validation remains mandatory.
Remove the retired top-level `HYPERTODO_REALTIME` even if None; there is no CACHE
alias adapter. Production static serving belongs to your web server/CDN, not
Django's DEBUG-only development handler.

The [backend change contract](backend/docs/realtime-changes.md) describes v2
negotiation and coordinated package/backend adoption. Older a21 deployments use
v1 fallback without own-operation correlation or entity precision. See also
[stream configuration](backend/docs/realtime-stream.md),
[installed-package adoption](backend/docs/installed-adoption.md) and the
[disposable normal-App fixture](backend/docs/sse-demo-fixture.md).

## What HyperTodo tests

- Login and session authentication, with each user restricted to their own data.
- Task and category creation, editing, filtering, completion, and deletion.
- Complete HXML documents and partial screen updates with fragments.
- Filesystem templates and database-backed overrides edited through Django Admin.
- Template validation, source precedence, revision-based invalidation, and caching.
- Optional Redis caching with an isolated logical database and namespace.
- Light and dark themes, English and Spanish, avatars, and accessible contrast.
- Native integrations such as the animated splash screen, biometric unlock, image
  selection, swipe actions, and the side menu.
- Automated backend and mobile quality gates.

## Custom elements, actions and host components

Use this inventory when editing HXML or looking for the code behind a native
interaction. These extensions belong to **HyperTodo**, not to dj-hyperview or
Hyperview core. Existing elements can be reused in templates; declaring a new
name in a schema does **not** install its mobile implementation.

### HXML elements: what renders and why

The `app:` prefix denotes `https://hypertodo.app/components`; ordinary HXML uses
`https://hyperview.org/hyperview`. The namespace URI, not the chosen prefix,
identifies a component. [App registration](mobile/App.tsx) supplies the first
three components below. [AppSessionSurface](mobile/src/realtime/app-session.tsx)
adds the two [gate components](mobile/src/realtime/gate.tsx) to the same renderer.

| Registered element | Why HyperTodo implements it | Real usage |
| --- | --- | --- |
| [`app:side-menu`](mobile/src/components/AnimatedSideMenu.tsx) | Animates a drawer and its backdrop, then replaces the menu host on close. `panel-width` is a percentage of the window; HXML supplies the menu contents. | [Side-menu fragment](backend/hyperview/fragments/side_menu.xml). |
| [`app:edge-menu-opener`](mobile/src/components/EdgeMenuOpener.tsx) | Adds a rightward edge gesture that fetches/replaces the menu host without replacing the screen. It uses GET + `replace`, not a new navigation action. | [Dashboard](backend/hyperview/screens/dashboard.xml). |
| [`app:swipe-row`](mobile/src/components/SwipeRow.tsx) | Adds an animated action tray and equivalent screen-reader actions to a row. Labels, destinations and optional destructive confirmation come from its children; only one tray stays open. | [Task rows](backend/hyperview/partials/task_items.xml), [category rows](backend/hyperview/partials/category_items.xml). |
| [`app:realtime`](mobile/src/realtime/gate.tsx) | Wraps a screen's content to coordinate resource dependencies, refresh, drafts and route/session ownership. A successful request is acknowledged only after matching layout, not when an SSE event arrives. | [Task form](backend/hyperview/screens/task_form.xml); [contextual-update policy](mobile/docs/realtime-contextual-updates.md). |
| [`app:realtime-page`](mobile/src/realtime/gate.tsx) | Renders nothing. Its request/page metadata lets the boundary correlate actual layout and loaded pages without adding a list row. A marker alone is not proof of success. | [Task page markers](backend/hyperview/partials/task_items.xml). |

`app:swipe-action` is **data consumed by `SwipeRow`**, not a sixth registered
component. It declares `href`, `action` (`navigate`/`replace`), `verb` (`get`/`post`),
labels, tone and optional confirmation copy. The current host reads these children;
the row's legacy `edit-href`/`toggle-href`/`delete-href` attributes remain for older
clients. Keep the surrounding form and CSRF token for mutations.

For example, this existing Dashboard element targets the screen's
`side-menu-host` and uses its existing `edge-menu-opener` style:

```xml
<app:edge-menu-opener xmlns:app="https://hypertodo.app/components"
  id="dashboard-edge-menu" style="edge-menu-opener"
  href="/hv/menu/?active=dashboard" action="replace" target="side-menu-host" />
```

### Custom behavior actions: native effects, not new HTTP verbs

The current six actions are registered by
[`createOwnedBehaviors`](mobile/src/behaviors/owned.ts), with native APIs supplied
by [owned-native](mobile/src/behaviors/owned-native.ts). The callbacks retain their
live source and session generation across asynchronous work; an old screen cannot
apply its result to a new account. Recovery exposes only the three biometric
actions, not all six.

| `behavior action` | Why it exists | Real usage |
| --- | --- | --- |
| `probe-biometrics` | Checks hardware/enrollment and the saved credential, reveals available controls and selects the face/fingerprint icon. It does not sign in. | [Login panel](backend/hyperview/fragments/login_panel.xml). |
| `biometric-unlock` | Opens the OS biometric prompt, then submits the saved credential through the captured login form. Django still authenticates the request. | [Login panel](backend/hyperview/fragments/login_panel.xml). |
| `store-biometric-token` | Consumes an authorized session credential effect for device sign-in; an explicitly bound empty-token response clears it. Arbitrary HXML cannot grant credential-write authority. | [Login transition](backend/hyperview/fragments/login_transition.xml), [Settings transition](backend/hyperview/fragments/settings_transition.xml). |
| `pick-avatar` | Opens the photo picker, resizes/encodes a JPEG and updates the form field/preview. The photo remains a draft until Settings is saved. | [Avatar panel](backend/hyperview/partials/avatar_panel.xml). |
| `show-snackbar` | Displays brief success/error copy supplied by a response, without embedding a native toast implementation in HXML. | [Task transition](backend/hyperview/fragments/task_transition.xml). |
| `notify-resources` | Marks the current session's declared resources stale after its own operation, so dependent screens can refresh silently. It neither publishes to Redis nor substitutes for authenticated SSE delivery. | [Task transition](backend/hyperview/fragments/task_transition.xml); [resource coordinator](mobile/docs/realtime-resources.md). |

These are excerpts from the task-success fragment, inside its existing Hyperview
`view`. The backend supplies `notice_message`; the resource notification is emitted
only in the negotiated realtime branch:

```xml
<behavior trigger="load" action="show-snackbar" message="{{ notice_message }}" tone="success" once="true" />
```

```xml
<behavior trigger="load" action="notify-resources" resources="tasks" once="true" />
```

By contrast, `navigate`, `back`, `reload`, `replace`, `append` and `dispatch-event`
used in the templates are **built-in Hyperview actions**, not six more custom
behaviors. `get`/`post` select the HTTP method. The app's gate coordinates owned
operations; it does not turn those actions into permission checks or replay POSTs.

### React-only UI and validation boundaries

These helpers are mounted by the host, **not addressable as XML tags**:

| Host helper | Why it exists |
| --- | --- |
| [`AnimatedSplash`](mobile/src/components/AnimatedSplash.tsx) | Provides the startup animation, reduced-motion handling and a bounded fallback if animation completion never arrives. |
| [`LoadingScreen` / `ErrorScreen`](mobile/App.tsx), [`ElementErrorBanner`](mobile/src/components/ElementErrorBanner.tsx) | Supply branded loading, safe full-screen errors and dismissible fragment errors rather than exposing raw exception text. |
| [`OfflineRefreshControl`](mobile/src/components/OfflineRefreshControl.tsx) | Stops the pinned client's stuck pull-to-refresh indicator after a failed request and applies the current theme. It does not retry or declare the request successful. |
| [`SnackbarHost`](mobile/src/components/SnackbarHost.tsx), [`RealtimeNotice`](mobile/src/components/RealtimeNotice.md) | Separate transient feedback from persistent non-conflict warnings and errors. Closing a card does not acknowledge fresh data. |
| [`RealtimeConflictDialog`](mobile/src/components/RealtimeConflictDialog.tsx) | Shows one localized sentence and exactly Update / Go back for an open form's relevant remote change, untouched or edited. Both discard any current draft and fetch the chosen route; Go back requires the exact clean predecessor. The gate owns consent, pending operations and staleness; see the [update policy](mobile/docs/realtime-contextual-updates.md#choose-how-to-resolve-a-form-conflict). |
| [`AppSessionSurface`](mobile/src/realtime/app-session.tsx), [`gate.Root`](mobile/src/realtime/gate.tsx), [`SessionNavigation`](mobile/App.tsx) | Own the authentication shield, request generations and navigation lifetime, preventing retired account content/callbacks from becoming current. |

There are also **attributes on core elements**, not replacement components:
`image.variant` (`face` or `fingerprint`) identifies icons for `probe-biometrics`;
`picker-item.realtime-entity-key` and `picker-item.realtime-entity-epoch` identify
the currently selected category dependency for contextual form conflicts.
They do not change the normal picker value or grant access to an entity.

The backend validates custom elements through
[`hypertodo.xsd`](backend/schema/hypertodo.xsd) (`HYPERVIEW.EXTRA_SCHEMAS`) and the
six actions/extra attributes through
[`schema_extensions()`](backend/config/schema.py) (`HYPERVIEW.SCHEMA_EXTENSIONS`).
For a new extension, implement/register it in the mobile host **and** declare its
validation contract; neither side replaces Django authentication, ownership or
CSRF checks. Realtime additionally needs the coordinated
[backend change contract](backend/docs/realtime-changes.md) and
[mobile update policy](mobile/docs/realtime-contextual-updates.md). Schema acceptance
alone does not start SSE, prove native support or verify a layout acknowledgement.

## Screenshots

<table>
  <tr>
    <td align="center"><img src=".github/assets/screenshots/login.png" width="280" alt="HyperTodo login screen"><br><strong>Login</strong></td>
    <td align="center"><img src=".github/assets/screenshots/dashboard-light.png" width="280" alt="HyperTodo dashboard in light mode"><br><strong>Light dashboard</strong></td>
    <td align="center"><img src=".github/assets/screenshots/dashboard-dark.png" width="280" alt="HyperTodo dashboard in dark mode"><br><strong>Dark dashboard</strong></td>
  </tr>
  <tr>
    <td align="center"><img src=".github/assets/screenshots/task-swipe-actions.png" width="280" alt="HyperTodo task list with swipe actions"><br><strong>Task actions</strong></td>
    <td align="center"><img src=".github/assets/screenshots/task-edit.png" width="280" alt="HyperTodo task editing form"><br><strong>Edit task</strong></td>
    <td align="center"><img src=".github/assets/screenshots/categories.png" width="280" alt="HyperTodo category list"><br><strong>Categories</strong></td>
  </tr>
  <tr>
    <td align="center"><img src=".github/assets/screenshots/settings.png" width="280" alt="HyperTodo profile and security settings"><br><strong>Settings</strong></td>
    <td align="center"><img src=".github/assets/screenshots/side-menu.png" width="280" alt="HyperTodo side menu"><br><strong>Side menu</strong></td>
    <td align="center"><img src=".github/assets/screenshots/about.png" width="280" alt="HyperTodo About screen"><br><strong>About</strong></td>
  </tr>
</table>

## Repository layout

| Path | Purpose |
| --- | --- |
| `backend/` | Django 6.1.1 application using Python 3.14 and dj-hyperview 0.1.0b1. |
| `mobile/` | Expo 57 host using React Native 0.86 and Hyperview 0.110.0. |
| `Makefile` | Commands for installing, validating, and running both applications. |

## Testing database-backed templates

The backend checks the database template source before the filesystem source.
`make backend-seed` publishes database overrides for the About screen and the
Categories document and fragment, while retaining their filesystem versions as
fallbacks.

1. Sign in to Django Admin with `admin` / `admin123`.
2. Open **Hyperview database templates → Hyperview templates**.
3. Edit and save the About template or a Categories template.
4. Return to the corresponding mobile screen and refresh it.

The About screen uses a database-backed template that can be edited and validated
in Django Admin, then refreshed immediately in the mobile application:

![Django Admin HXML editor](.github/assets/screenshots/django-admin-hxml-editor.png)

Editing stored HXML changes the mobile interface without rebuilding the app. Treat
that access like a production code-deployment permission: dj-hyperview restricts
template mutations to superusers by default.

## Quality checks

Run the complete automated gate from the repository root:

```console
EXPO_PUBLIC_API_URL=https://hypertodo-ci.invalid/hv/ make check
```

It runs Ruff, pytest with statement and branch coverage, Django system checks,
migration drift detection, TypeScript, Jest, and Expo Doctor. No native build is
required. Run `make acceptance` to print the manual device checklist.

The HTTPS `.invalid` URL is an explicit **validation-only** setting, not a running
backend or a deployment default. For Doctor alone, run
`EXPO_PUBLIC_API_URL=https://hypertodo-ci.invalid/hv/ corepack yarn --cwd mobile doctor`.
The command first requires successful full Expo config resolution, then the
complete successful `expo-doctor` report. A zero exit without checks is rejected
(the locked Doctor 1.20.4 can log config errors and still exit zero). Tool launch,
config, check, report, signal and timeout failures stay failures with diagnostics.
Doctor's online checks need network access; an unavailable service is not a PASS.
The API guard and normal local-development opt-in remain unchanged.

Package documentation is available at
[eamigo86.github.io/dj-hyperview](https://eamigo86.github.io/dj-hyperview/).

## Automatic HXML validation

The installed dj-hyperview 0.1.0b1 beta enforces one corrected Hyperview schema automatically.
HyperTodo configures only the extensions owned by its existing mobile host in
`backend/config/schema.py`: six custom behaviors, `image.variant` with
`face`/`fingerprint` values, and the picker-item entity metadata used by contextual
form updates. `backend/schema/hypertodo.xsd` continues to describe
app-owned components through `EXTRA_SCHEMAS`. Empty biometric tokens remain valid
revocations, and fragment targets may reference their host document.

There is no schema profile, validation callback, or enable/disable flag to select.
The package owns standard validation and includes its schema dependency normally;
`[editor]` still enables the optional Admin editor. HyperTodo refuses startup when
the package lacks the `automatic-xsd-v1` capability. This is a compatibility check,
not a release number or a user setting: unsupported installations cannot silently
skip validation.

The package pin and lock are part of the same reviewed adoption. After pulling a
new version, run `make backend-install` before starting Django so the environment,
metadata, and automatic-validation contract cannot drift apart.

### What the corpus proves

The manifest covers all 40 filesystem XML sources: 12 documents, 21 fragments,
and 7 partials. Real route contexts exercise both themes and languages, empty and
populated data, absent/legacy/current mobile-version headers, successful and
invalid forms, authentication transitions, and escaped user text. Existing flow
tests use the same automatic rendered XSD contract as normal application requests. Active/inactive database overrides are
created only in isolated test databases.

Ten stylesheets moved intact inside their owning screen. Their byte hashes and
existing light palette goldens are unchanged; the pinned Hyperview stylesheet
parser is checked before/after relocation. Fragments remain bare and inherit
host styles. Language decorations now use one labeled button text with
role-neutral inline content, not unconverted boolean strings. The idle avatar
preview stays hidden with a transparent 1×1 PNG data URI: no missing/empty source
and no external request. The unchanged picker replaces its source before showing
it.

Admin **Format & Validate is context-free** and may report dynamic-template
warnings. It neither renders a scenario nor proves every rendered branch. The
before-save validator remains authoritative for its source-level contract;
rendered XSD validation is the separate runtime check. No preview is restored.
The About source keeps the optional realtime wrapper in balanced XML branches
around one shared content partial. This preserves both legacy and negotiated
rendered output while allowing the conservative formatter to prove idempotence;
it does not relax handling of branch-dependent XML.
The corrected schema covers documented differences, not the whole native client:
date-field button labels are iOS-only, and the pinned host's decimal width
conversion (for example, `12.5` points becoming `12`) is not rewritten.

### Adopt database overrides explicitly

1. Obtain authorization for the exact database alias and take a verified backup.
   Run `check_hyperview_templates --database ALIAS` read-only. This checks identity
   integrity, **not XSD compatibility**. Stop on anomalies; do not choose a winner,
   delete duplicates, or repair automatically.
2. Review active rows before filesystem fallbacks, especially `screens/about.xml`,
   `screens/categories.xml`, and `fragments/category_list.xml`. `seed_demo` only
   creates absent rows and also changes demo accounts/data: **do not use it as an
   upgrade or repair command**.
3. Compare reviewed row contents with the normalized sources and validate them in
   an isolated copy using approved synthetic contexts. Preserve deliberate Admin
   edits; a filesystem-only green result does not authorize a package upgrade.
4. After human approval, publish each reviewed change through `publish_template`
   with the explicit alias and `expected_revision` from that review. A concurrent
   edit requires another review. Never perform automatic data migrations.
5. Adopt a reviewed package release and the matching consumer
   configuration **as one unit**, after the effective-source review passes. The
   package upgrade now activates enforcement; there is no later toggle. Update the
   pin/lock only as part of that authorized adoption and repeat installed-package
   acceptance before restarting the application. If any effective source still
   fails, keep the existing reviewed application/package pair in place.
6. Roll back the reviewed package and consumer configuration together, never by
   disabling validation. Database rollback requires its separate approved backup
   procedure; do not overwrite concurrent edits. Publication invalidates affected
   names. If a controlled repair requires namespace rotation, rotate only
   Hyperview's namespace—never flush a shared cache.

Visual comparison, native flows, and VoiceOver/TalkBack on **existing** iOS and
Android apps remain explicit manual acceptance gates. Check inline flag spacing,
spoken language/state, date controls, avatar picking, and fragment refreshes.
Automated source/prop tests are not device E2E evidence, and no new native build
or deployment is authorized by this guide.

## Realtime Gate 0: historical experiment scope

The original isolated `mobile/src/realtime/gate.tsx` spike did not register itself
in App or open SSE/WebSocket connections. The evidence below describes that
preparatory scope, not the later App integration or a current SSE deployment claim.
Use the stream/fixture instructions above for the opt-in realtime candidate.
The finite Gate 0 prerequisites were subsequently accepted, followed by the
limited normal-App/Admin SSE demo documented in
[the demo fixture guide](backend/docs/sse-demo-fixture.md). This section preserves
the earlier checkpoints; their pending items are not the candidate's current status.

Its integration tests run the real pinned Hyperview parser, component registry,
DOM updates and React Navigation with Jest's native shims. The transparent
`app:realtime` boundary sits outside `FlatList`; it scans page metadata inside
existing items and acknowledges request IDs only after a React layout commit.
It serializes `append`/`replace` dispatches, including tested POST mutations,
before Hyperview captures a DOM root—not merely before network I/O. Tests preserve
filters and drafts, ignore hidden routes, retain in-flight hints, and reject
old-epoch responses both before headers and during deferred body consumption.

Authentication-generation tests use `gate.Root`, not a raw Hyperview root.
`resetEpoch()` suspends and removes the **whole** HXML tree, including content
outside the realtime boundary, and returns a generation token. It does not start
a new request while login/logout may still be changing session cookies. Only
`resumeEpoch(token)` with the current token remounts Hyperview, keyed by that
generation; stale or repeated tokens do nothing. A failed reset revokes any
previous resume capability. Exhausting the bounded epoch counter permanently
suspends that gate instance; no old token can resume it or send another request.
Each mounted root binds its
public fetch to that generation: a retained callback from the previous tree
cannot send a request under the new session. The authentication owner must call
resume only after confirming the current session. At this checkpoint, App/auth
wiring and the origin-generation policy for old global events were still pending.

The C1 proof replaces first-fetch guessing with an explicit app-owned contract:
remote same-origin `append`/`replace` operations reserve route/epoch identity before
SDK dispatch. A bounded `__djhv_op` query token is stripped before HTTP; the real
wire URL preserves filters, duplicate form values and their encoding. Only the
matching route's committed attempt marker acknowledges that operation. Unrelated
initial loads cannot acquire or block it. An already admitted ordinary POST is
not canceled or replayed just because its route loses focus; only automatic
refresh follows the hidden-route deferral policy. Its own transport and committed
attempt, not another route's focus or ACK, release the reservation.

App-owned custom handlers opt in explicitly with `gate.ownBehavior(handler)`;
SDK defaults are not wrapped. This binds the source route and generation, remains
valid after normal XML clones, and rejects a removed or stale origin. Null/empty
and missing local sources reject truthfully before SDK dispatch, without calling
successful `onEnd` or fabricating an ACK. At most 64 live operations are retained;
invalid, reused or colliding tokens never evict another owner. Dispatch options
and HTTP method authority are copied at admission. The private Root provenance
used for initial-load ownership is immutable, instance/epoch-bound and removed
before HTTP; normal fetch without that provenance retains its fail-closed policy.
Multiple boundaries in a document are rejected as ambiguous before an owned
callback is invoked.

The C1 slice alone is **not transparent for every SDK action**. Remote hashes
remain rejected. C2 below adds owned local/fragment terminal proof;
reload/navigation, generic custom callbacks and broader lifecycles remain
separate work. The SDK's parse/error callbacks may retain the transient token
even though HTTP and app refresh identity stay canonical. See the [corrective C1 evidence](../evidence/gate0-mobile/explicit-fix-report.md)
and the [historical four-red action report](../evidence/gate0-mobile/action-report.md).

### C2: owned fragment lifecycle (historical review checkpoint)

The `gate.Root` dispatcher now owns local and remote `append`/`replace`
lifecycles. It uses the **public Hyperview Parser**, the Registry exposed in
component options for form values, and a public `swap` to deliver the result.
It rechecks operation, route and authentication generation after parsing, and
rejects stale response correlation before delivery. Only the resulting boundary
layout acknowledges success; parsing, callback return and timers never do.
A valid successor dispatched by `onEnd` keeps its captured route and live origin
across the public swap's cloned ancestors. Once a result is submitted, sync
replace/drop no longer cancels that result: a successor waits in the queue for
its matching layout ACK. Removed origins and ambiguous boundaries stay denied.

Terminal outcomes are `ack`, `no-document`, `error`, `cancelled` or `dropped`,
with a finite reason and route key—no URL, request token, HXML or user data.
Empty/no-body responses, parse/network errors, already-consumed `once`, removed
delayed sources and owned sync drop/replacement cannot strand the next ordinary
request. Errors preserve an uncertainty notice rather than claim a POST failed
to save. The original `onError`, declared retry headers and loading indicators
are retained; throwing caller callbacks cannot bypass cleanup or invent an ACK.
The private SDK error overlay/state is **not** impersonated: the later app-owned
notice UI consumes these explicit outcomes.

Retry is an explicit new invocation with a fresh identity, never an automatic
POST replay. Canceling/replacing an operation suppresses its late delivery;
**it does not undo a POST already received by the server**. Delayed operations
still preserve C1's admitted-POST-across-blur policy; reset cancels owned scheduler
resources and denies previous-generation delivery.

See the [C2 seam matrix and historical evidence](../evidence/gate0-mobile/c2-report.md)
and the [pending-commit ownership correction](../evidence/gate0-mobile/c2-fix-report.md).
This checkpoint was a worktree proof, not production registration. Navigation/reload,
broader default actions, authentication/background integration and native layout
verification were covered in later C3/Gate 0 work. Bare Hyperview
without `gate.Root` retains only the earlier C1 harness contract.

At that checkpoint, the XSD declarations typed test-only metadata and only the
test transport echoed correlation IDs in synthetic HXML. Actual backend routes
now emit the negotiated metadata described in [the template contract](backend/docs/realtime-templates.md).
An absent ACK stays pending; errors fail closed rather than
using a timeout to pretend a document was committed.

Run the focused suites from their respective projects with existing dependencies:

```sh
# mobile/
yarn test --watchman=false --no-cache realtime-gate realtime-operation navigation-contract network schema-normalization

# backend/ — isolated SQLite, local memory cache and temporary media
DJANGO_SETTINGS_MODULE=tests.settings_schema python -B -m pytest \
  -o addopts= -p no:cacheprovider tests/test_realtime_gate_schema.py \
  tests/test_schema_compatibility.py
```

**Early native checkpoint: physical iOS I/O passed; Gate 0 was still pending.** On 2026-09-09
at 02:05 UTC, the existing Expo Go 57.0.9 client (build 1017880), source SDK 57.0.21
and native RN 0.86.2 proved synthetic cookie sharing, two ACK-gated streamed
frames and abort-driven server closure with zero active streams. The phone
result matches the [durable native result](../evidence/gate0-native/native-ios-result.md).
This used only the standalone test fixture, not real app authentication or data.

Android I/O and the representative native App/auth campaign had not yet run at
this early checkpoint. Later acceptance is separate from this synthetic result;
Jest is not native evidence, and no single run proves every action permutation.
The current application uses the real SSE transport described above, without a
silent manual-only fallback or an SDK fork. Configuration/source regressions do
not rerun or upgrade the historical native evidence.

## License

HyperTodo is distributed under the [MIT License](LICENSE).
