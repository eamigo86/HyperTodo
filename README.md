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

## What HyperTodo tests

- Django login, sessions, CSRF and per-user task/category ownership.
- Task/category forms, filters, completion and partial HXML updates.
- Filesystem and database templates, Admin editing, automatic validation and caching.
- Contextual SSE refresh, draft protection and account/session isolation.
- Light/dark themes, English/Spanish, avatars, biometrics and accessible native UI.

Automated checks and manual device acceptance are separate; a passing XML or
Jest test does not prove every native flow.

## Repository layout

| Path | Purpose |
| --- | --- |
| [`backend/`](backend/) | Python 3.14 / Django 6.1.1, pinned to `dj-hyperview[editor,realtime]==0.1.0b1`. |
| [`mobile/`](mobile/) | Expo SDK 57, React Native 0.86 and Hyperview 0.110.0 host. |
| [`Makefile`](Makefile) | Install, run and quality commands for both applications. |

## Makefile commands

Prerequisites: Python 3.14 with **uv**, Node **22.19.0** through **nvm/Corepack**,
and Expo Go for SDK 57. SSE also needs an **existing Redis server**; installing
its Python client does not start one. Run commands from the repository root.

**Database safety:** migration/seed commands below are for deliberate setup of a
**new disposable database**. For existing data, back up and review migrations;
**do not seed to upgrade**. The seed can reset demo accounts/data. Follow the
[installed-package and safe startup guide](backend/docs/installed-adoption.md)
for credentials, existing DB overrides and deployment details.

| Command | Use |
| --- | --- |
| `make help` | List every available target. |
| `make setup` | Install backend/mobile dependencies; does not migrate or seed. |
| `make backend-migrate`, `make backend-seed` | Initialize a new disposable demo DB, not an upgrade shortcut. |
| `LAN_IP=192.168.1.20 make backend-run-sse` | Start the same DB-first ASGI/SSE app, bound to the supplied LAN address. |
| `LAN_IP=192.168.1.20 make mobile-start-go` | Start the matching Expo Go QR workflow with explicit local-HTTP permission. |
| `make backend-run`, `make backend-run-redis` | Start ASGI/SSE with local-memory or Redis cache, respectively. |
| `LAN_IP=192.168.1.20 make backend-run-device` | Start the same ASGI/SSE app with Redis cache and device host/CSRF settings. |
| `make mobile-start`, `make mobile-start-device` | Development-client workflows, **not Expo Go**; device target requires `LAN_IP`. |
| `make lan-ip` | Print a candidate computer address; verify reachability from the phone. |

For SSE, run `make setup`, prepare the database as appropriate, then keep the
**ASGI and Expo Go commands in separate terminals**. Replace the example IP in
both with the same reachable private computer address, scan the QR and sign in.
No native build is needed. Use only trusted development networks, not real data
or publicly exposed demo credentials; stop both terminals with Ctrl+C.

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

## Custom components and behaviors

These extensions belong to **HyperTodo**, not dj-hyperview or Hyperview core.
HXML declarations describe the interface; the registered mobile implementation
provides the native behavior. Adding a schema declaration alone installs nothing.

### HXML components

Five registered elements use `https://hypertodo.app/components` (`app:` below).
[App](mobile/App.tsx) registers the visual components;
[AppSessionSurface](mobile/src/realtime/app-session.tsx) adds the realtime pair.

| Element | Why it exists |
| --- | --- |
| [`app:side-menu`](mobile/src/components/AnimatedSideMenu.tsx) | Animated drawer/backdrop with HXML-provided contents. |
| [`app:edge-menu-opener`](mobile/src/components/EdgeMenuOpener.tsx) | Edge gesture that fetches the menu without replacing the screen. |
| [`app:swipe-row`](mobile/src/components/SwipeRow.tsx) | Task/category action tray with equivalent screen-reader actions and optional destructive confirmation. |
| [`app:realtime`](mobile/src/realtime/gate.tsx) | Coordinates resource dependencies, safe refresh, forms and route/session ownership. |
| [`app:realtime-page`](mobile/src/realtime/gate.tsx) | Invisible request/page marker for correlating actual layout; adds no row. |

`app:swipe-action` is child data read by `SwipeRow`, **not a sixth component**.
Keep its normal form/CSRF context for mutations. See real
[task rows](backend/hyperview/partials/task_items.xml) and
[side-menu markup](backend/hyperview/fragments/side_menu.xml).

### Behavior actions

The six actions in [owned behaviors](mobile/src/behaviors/owned.ts) use
[native ports](mobile/src/behaviors/owned-native.ts) while retaining their source
and session generation. They are actions, not HTTP verbs or permission checks.

| Action | Why it exists |
| --- | --- |
| `probe-biometrics` | Discover hardware/enrollment and reveal available sign-in controls; does not authenticate. |
| `biometric-unlock` | Prompt through the OS, then submit the captured login form; Django still authenticates. |
| `store-biometric-token` | Store or explicitly clear an authorized device credential; arbitrary HXML cannot grant write authority. |
| `pick-avatar` | Select/resize an image and update its draft preview; saving remains an ordinary form action. |
| `show-snackbar` | Show brief response feedback using the native host. |
| `notify-resources` | Mark local dependent screens stale after an operation; does not publish to Redis or replace authenticated SSE. |

`navigate`, `back`, `reload`, `replace`, `append` and `dispatch-event` remain
built-in Hyperview actions; `get`/`post` choose the HTTP method. See the
[login panel](backend/hyperview/fragments/login_panel.xml) and
[task transition](backend/hyperview/fragments/task_transition.xml) for usage.

### React-only host UI

These helpers are mounted by React, **not addressable as XML tags**.

| Helper | Purpose |
| --- | --- |
| [`AnimatedSplash`](mobile/src/components/AnimatedSplash.tsx) | Branded startup, reduced motion and bounded animation fallback. |
| [Loading/Error screens](mobile/App.tsx), [`ElementErrorBanner`](mobile/src/components/ElementErrorBanner.tsx) | Branded loading and safe page/fragment errors. |
| [`OfflineRefreshControl`](mobile/src/components/OfflineRefreshControl.tsx) | Finish a failed pull-to-refresh indicator without retrying or declaring success. |
| [`SnackbarHost`](mobile/src/components/SnackbarHost.tsx), [`RealtimeNotice`](mobile/src/components/RealtimeNotice.md) | Transient feedback versus persistent non-conflict warnings/errors. |
| [`RealtimeConflictDialog`](mobile/src/components/RealtimeConflictDialog.tsx) | Explicit Update / Go back choices for an open form's relevant remote change. |
| [`AppSessionSurface`](mobile/src/realtime/app-session.tsx), [gate/navigation](mobile/src/realtime/gate.tsx) | Authentication shielding and request/navigation lifetime across account changes. |

Extra attributes on core elements are not new components: `image.variant`
selects biometric icons, and picker-item entity metadata tracks the selected
category dependency. None grants entity access. Implement/register new extensions
in the host **and** declare their backend schema; preserve authentication,
ownership and CSRF. See the [contextual-update policy](mobile/docs/realtime-contextual-updates.md).

## Database-backed templates

Every backend command uses `config.settings`: active database templates take precedence, with filesystem fallback when no active override exists. Startup never rewrites stored templates. A fresh demo seed creates About and Categories overrides.

Sign into `/admin/` as an authorized superuser, open **Hyperview database templates → Hyperview templates**, edit a template and save. With Redis available, committed changes send a `ui` hint to connected clients; the next authenticated HTTP refresh resolves the updated DB template without rebuilding the app. The stored screen must retain its realtime boundary for automatic refresh; older overrides need review. For existing data, follow [override adoption](backend/docs/installed-adoption.md#adopt-database-overrides-explicitly) instead of seeding or overwriting deliberate Admin edits.

![Django Admin HXML editor with Format and Validate](.github/assets/screenshots/django-admin-hxml-editor.png)

Template editing is code-deployment authority: dj-hyperview permits mutations
only to superusers by default. **Format and Validate is context-free**; it does
not preview a rendered screen or prove every dynamic branch.

## Automatic HXML validation

The installed beta applies the corrected standard XSD automatically; there is
no validation-off switch. HyperTodo adds only its own components in
[`hypertodo.xsd`](backend/schema/hypertodo.xsd) and behavior/attribute declarations
in [`schema_extensions()`](backend/config/schema.py). Startup requires the
`automatic-xsd-v1` capability.

Tests render real route contexts, themes, languages and valid/invalid forms;
XML acceptance does not prove native component registration or device behavior.
Review effective DB overrides before upgrading the package/app pair. See the
[package validation guide](https://eamigo86.github.io/dj-hyperview/custom-schemas/).

## Realtime SSE

The single `config.settings` enables `HYPERVIEW["REALTIME"]` independently of cache. All backend launchers use Uvicorn/ASGI and the same DB-first source order, Redis endpoint and namespace. Redis must already be running for notifications; `REDIS_URL` defaults to `redis://127.0.0.1:6379/15`. Use the same configuration for Admin, other writers and stream workers. Authentication, sessions, CSRF and validation remain unchanged. Redis PubSub channels are not isolated by database number. See [startup/configuration](backend/docs/installed-adoption.md) and the [backend contract](backend/docs/realtime-changes.md).

Committed hints cause authenticated HTTP refreshes; they carry no full document and do not guarantee replay. The current app wires these areas:

| Area | Relevant changes | Visible behavior |
| --- | --- | --- |
| Tasks / Categories | Task/category saves and deletes; `ui` presentation/template changes. | Automatic refresh, retaining filters and the bounded loaded prefix. |
| Dashboard | `tasks`, `categories` and `ui`. | Automatic refresh; a stale return loads fresh content before showing it. |
| Task / category forms | Current record, selected category for a task, and the owner's `ui` changes. | Update / Go back dialog, whether untouched or edited; precise metadata excludes unrelated records. |
| Settings | Owner's User `first_name`, `last_name`, `email`; Profile `theme`, `language`, `avatar`. | Same remote-change dialog; this app's own operations stay quiet. |
| About | `ui` presentation/template changes. | Automatic refresh of the readonly screen. |

**Settings is already wired:** normal Django Admin saves of the signed-in user's name should notify it. The Admin writer must also have realtime enabled and use the same Redis namespace and service as the stream server. `QuerySet.update()` and `bulk_update()` bypass save signals and need explicit publication; they are not equivalent to an ordinary Admin save.

The side menu is a fetched fragment, not an independent SSE boundary. Login/recovery use session reconciliation, not change dialogs. Own-operation feedback and login/resync stay quiet. See the [mobile policy](mobile/docs/realtime-contextual-updates.md) for draft safety, pagination and actual layout acknowledgement; this inventory is not a new native acceptance result.

## Quality checks

```console
EXPO_PUBLIC_API_URL=https://hypertodo-ci.invalid/hv/ make check
```

Runs backend Ruff/tests/coverage, installed Admin-editor JavaScript, Django checks
and migration-drift checks, plus mobile TypeScript/Jest/Expo Doctor. The HTTPS
`.invalid` address is **validation-only**, not a backend. Doctor must resolve
Expo config and report all checks successfully; unavailable online checks are
not a PASS. No native build is required.

Use `make backend-test` / `make mobile-test` for separate suites and
`make acceptance` for the manual iOS/Android checklist. Optional
`make backend-test-redis` requires an authorized isolated Redis test service;
never flush shared data. See the [package documentation](https://eamigo86.github.io/dj-hyperview/).

## License

HyperTodo is distributed under the [MIT License](LICENSE).
