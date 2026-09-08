# HyperTodo

[![CI](https://github.com/eamigo86/HyperTodo/actions/workflows/ci.yml/badge.svg)](https://github.com/eamigo86/HyperTodo/actions/workflows/ci.yml)
[![dj-hyperview](https://img.shields.io/badge/dj--hyperview-0.1.0a10-278CFF)](https://pypi.org/project/dj-hyperview/0.1.0a10/)
[![Hyperview](https://img.shields.io/badge/Hyperview-0.110.0-171A2F)](https://www.npmjs.com/package/hyperview/v/0.110.0)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

HyperTodo is a test application for the
[dj-hyperview](https://github.com/eamigo86/dj-hyperview) package. It combines a
Django backend with an Expo mobile host that uses Hyperview to render native
screens from server-provided HXML.

The project exists to exercise dj-hyperview in a realistic application. It is
not intended to be a reusable task-management product.

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
| `backend/` | Django 6.1.1 application using Python 3.14 and dj-hyperview 0.1.0a10. |
| `mobile/` | Expo 57 host using React Native 0.86 and Hyperview 0.110.0. |
| `Makefile` | Commands for installing, validating, and running both applications. |

## Quick start

### Requirements

- Python 3.14 and [uv](https://docs.astral.sh/uv/)
- Node 22.19.0 through [nvm](https://github.com/nvm-sh/nvm)
- Corepack
- Expo Go on a physical device, or an iOS/Android simulator
- Redis only when testing the optional shared-cache configuration

### 1. Prepare the project

Run these commands in a terminal opened at the repository root:

```console
make help
make setup
make backend-migrate
make backend-seed
make check
```

`make setup` installs the locked Python and JavaScript dependencies. The migration
command prepares the local database, and the seed command creates repeatable demo
data and publishes the database-template examples. `make check` verifies the
complete backend and mobile test suites before the app is started.

The development seed provides two local accounts:

| User | Password | Purpose |
| --- | --- | --- |
| `admin` | `admin123` | Superuser with access to Django Admin and the HXML editor. |
| `demo` | `demo123` | Regular user with separate tasks and categories. |

### 2. Start the backend for a physical device

First, obtain the development machine's LAN address from any root terminal:

```console
make lan-ip
```

Then start Django in the **backend terminal**, replacing the example address:

```console
LAN_IP=192.168.1.20 make backend-run-device
```

### 3. Start Expo Go

In a separate **mobile terminal**, use the same address:

```console
LAN_IP=192.168.1.20 make mobile-start-go
```

Scan the QR code with the phone camera and open the project in Expo Go. The phone
and development machine must be connected to the same reachable local network.

### Simulator alternatives

For an iOS Simulator, run `make backend-run` in the backend terminal and
`make mobile-start` in the mobile terminal. Use `make mobile-start-android` for
the Android Emulator. To exercise the existing Redis service, replace the backend
command with `make backend-run-redis`.

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
make check
```

It runs Ruff, pytest with statement and branch coverage, Django system checks,
migration drift detection, TypeScript, Jest, and Expo Doctor. No native build is
required. Run `make acceptance` to print the manual device checklist.

Package documentation is available at
[eamigo86.github.io/dj-hyperview](https://eamigo86.github.io/dj-hyperview/).

## License

HyperTodo is distributed under the [MIT License](LICENSE).
