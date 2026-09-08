# HyperTodo

[![CI](https://github.com/eamigo86/HyperTodo/actions/workflows/ci.yml/badge.svg)](https://github.com/eamigo86/HyperTodo/actions/workflows/ci.yml)
[![dj-hyperview](https://img.shields.io/badge/dj--hyperview-0.1.0a10-278CFF)](https://pypi.org/project/dj-hyperview/0.1.0a10/)
[![Hyperview](https://img.shields.io/badge/Hyperview-0.110.0-171A2F)](https://www.npmjs.com/package/hyperview/v/0.110.0)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

HyperTodo is a real consumer application for
[dj-hyperview](https://github.com/eamigo86/dj-hyperview). Django owns the data,
business rules, and HXML screens; an Expo host renders those screens as a native
mobile interface with Hyperview.

Unlike a static demo, HyperTodo exercises complete document navigation,
fragment updates, database-backed templates, cache invalidation, authentication,
custom HXML components, and native device capabilities.

## What it demonstrates

- Session-authenticated task and category management with strict user isolation.
- Filesystem HXML templates with database overrides managed through Django Admin.
- Live screen changes after publishing a stored template, without rebuilding the
  mobile application.
- Full Hyperview documents and targeted fragment replacement.
- Optional Redis caching through an isolated logical database and namespace.
- Light and dark themes, English and Spanish, avatars, and accessible contrast.
- Animated splash handoff, biometric unlock, native image selection, swipe
  actions, and a server-driven side menu.
- Strict backend TDD, focused mobile tests, type checking, linting, Django checks,
  migration checks, and Expo Doctor.

## Repository layout

| Path | Purpose |
| --- | --- |
| `backend/` | Django 6.1.1 application using Python 3.14 and dj-hyperview 0.1.0a10. |
| `mobile/` | Expo 57 host using React Native 0.86 and Hyperview 0.110.0. |
| `doc/` | Architecture, setup, testing, acceptance, decisions, and integration findings. |
| `Makefile` | Root commands for installing, validating, and running both applications. |

## Quick start

### Prerequisites

- Python 3.14 and [uv](https://docs.astral.sh/uv/)
- Node 22.19.0 through [nvm](https://github.com/nvm-sh/nvm)
- Corepack
- Expo Go on a physical device, or an iOS/Android simulator
- Redis only when exercising the optional shared-cache path

Run all setup commands from the repository root:

```console
make help
make setup
make backend-migrate
make backend-seed
make check
```

The seed command creates two local accounts while Django debug mode is enabled:

| User | Password | Purpose |
| --- | --- | --- |
| `admin` | `admin123` | Superuser and Django Admin template editor. |
| `demo` | `demo123` | Regular account with separate tasks and categories. |

### Run with Expo Go on a physical device

Find the development machine's LAN address:

```console
make lan-ip
```

Start Django in the backend terminal:

```console
LAN_IP=192.168.1.20 make backend-run-device
```

Start Expo in the mobile terminal:

```console
LAN_IP=192.168.1.20 make mobile-start-go
```

Scan the QR code with the phone camera and open it in Expo Go. The phone and
development machine must use the same reachable local network.

### Run locally or in a simulator

```console
# Backend terminal
make backend-run
```

```console
# Mobile terminal: iOS Simulator or an installed development client
make mobile-start
```

Use `make mobile-start-android` for the Android Emulator address. Run
`make backend-run-redis` instead of `make backend-run` when testing the existing
Redis service configured by `REDIS_URL`.

## Live database templates

The configured source order checks the database before the filesystem. Running
`make backend-seed` publishes database overrides for the About screen and the
Categories document and fragment while preserving their filesystem fallbacks.

1. Sign in to Django Admin with the local admin account.
2. Open a stored Hyperview template.
3. Edit and publish its HXML with the optional schema-aware editor.
4. Refresh the corresponding screen in HyperTodo.

The committed database version appears immediately on the next request. Editing
a stored HXML template is equivalent to changing application code, so
dj-hyperview 0.1.0a10 restricts mutations to superusers by default.

## Quality gates

```console
make check
```

This runs:

- Ruff, pytest with statement and branch coverage, Django checks, and migration
  drift detection for the backend.
- TypeScript, Jest, and Expo Doctor for the mobile host.

No native build is required for the automated gate. See
[Testing](doc/testing.md) and the [Acceptance checklist](doc/acceptance.md) for
the manual device workflow.

## Documentation

Start with the [documentation index](doc/index.md) or go directly to:

- [Getting started](doc/getting-started.md)
- [Architecture](doc/architecture.md)
- [Testing](doc/testing.md)
- [Lessons learned](doc/lessons-learned.md)
- [Package improvement candidates](doc/package-improvements.md)

The reusable package documentation is published at
[eamigo86.github.io/dj-hyperview](https://eamigo86.github.io/dj-hyperview/).

## Scope

HyperTodo is a reference consumer, not a reusable task-management package. Its
purpose is to prove and document the integration boundary between Django,
dj-hyperview, Hyperview, Expo, and project-owned native extensions.

## License

HyperTodo is distributed under the [MIT License](LICENSE).
