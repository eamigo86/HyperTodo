# Testing

## Backend quality gate

The backend follows strict TDD. Pytest enforces statement and branch coverage together with a minimum of 95 percent.

```console
cd backend
uv sync
uv run pytest
uv run ruff check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
```

The suite covers model constraints, user ownership, deadline parsing, composable filters, mutation services, profile and biometric lifecycles, avatar safety and rollback compensation, session behavior, CSRF enforcement, explicit document and fragment responses, XML escaping, database/filesystem precedence, admin registration, LocMem invalidation, and isolated real-Redis invalidation.

Redis tests use logical database 14 and a random namespace. They never call FLUSHDB or FLUSHALL. If the shared service is unavailable, only the explicitly marked Redis acceptance test is skipped.

## Mobile quality gate

```console
cd mobile
nvm use
corepack yarn install
corepack yarn typecheck
corepack yarn test
corepack yarn doctor
```

The focused suite checks URL normalization, relative request resolution, cookie credentials, HXML headers, splash handoff, theme propagation, biometric behaviors, avatar selection, gesture responders, navigation contracts, offline recovery, and branded loading/error states. There is no arbitrary numeric mobile coverage target because this project does not extend Hyperview internals.

## Native smoke tests

Native smoke is required on both iOS and Android but remains manual. It needs development builds, a running Django server, and platform simulators or devices. Record each result in `acceptance.md`.
