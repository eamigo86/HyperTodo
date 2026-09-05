# HyperTodo

HyperTodo is a real consumer application for [dj-hyperview](https://github.com/eamigo86/dj-hyperview). Django owns the data and serves HXML screens; an Expo development client renders those screens with Hyperview.

The project intentionally keeps both sides visible:

- `backend/`: Django 6.1.1, dj-hyperview 0.1.0a7, SQLite, and optional Redis caching.
- `mobile/`: Expo 57, React Native 0.86, and Hyperview 0.110.0.
- `doc/`: architecture, setup, testing, and acceptance records.

## Quick start

```console
cd backend
uv sync
uv run python manage.py migrate
HYPERTODO_DEMO_PASSWORD=local-password uv run python manage.py seed_demo
uv run python manage.py runserver
```

In another terminal:

```console
cd mobile
nvm use
cp .env.example .env
YARN_NODE_LINKER=node-modules yarn install
yarn start
```

Hyperview uses native modules, so this app requires a development build rather than Expo Go. Native build commands are documented but were deliberately not run as part of this implementation.

Read the complete [Getting Started guide](doc/getting-started.md).
