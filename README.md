# HyperTodo

HyperTodo is a real consumer application for [dj-hyperview](https://github.com/eamigo86/dj-hyperview). Django owns the data and serves HXML screens; an Expo development client renders those screens with Hyperview.

The project intentionally keeps both sides visible:

- `backend/`: Django 6.1.1, dj-hyperview 0.1.0a8, SQLite, and optional Redis caching.
- `mobile/`: Expo 57, React Native 0.86, and Hyperview 0.110.0.
- `doc/`: architecture, setup, testing, and acceptance records.

Run `make help` from the repository root to list the setup, test, quality,
development-server, and native acceptance commands.

## Quick start

```console
cd backend
uv sync
uv run python manage.py migrate
uv run python manage.py seed_demo
uv run python manage.py runserver
```

In another terminal:

```console
cp mobile/.env.example mobile/.env
make mobile-start
```

The tested dependency matrix runs in Expo Go for the fastest local QR workflow. A development build is required only when introducing native code that Expo Go does not contain or when validating native configuration such as launcher icons.

Read the complete [Getting Started guide](doc/getting-started.md).

The local seed command creates `admin`/`admin123` and `demo`/`demo123` when
debug mode is enabled. Override both password environment variables before
using non-local settings.
