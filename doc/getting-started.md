# Getting started

This guide starts from clean Django and Expo projects. You do not need to clone the Hyperview repository or copy its demo application.

## Prerequisites

- Python 3.14 and uv
- Node 22.19.0 through nvm
- Corepack, which installs the project-pinned Yarn 1.22.22
- Xcode and CocoaPods for iOS, or Android Studio and ADB for Android
- A running Redis service only when testing cache behavior

Expo Go is not sufficient because Hyperview uses native dependencies. Use an Expo development build.

## 1. Start the Django backend

```console
cd backend
uv sync
uv run python manage.py migrate
```

The package is already registered with the short app labels:

```python
INSTALLED_APPS = [
    "dj_hyperview",
    "dj_hyperview.contrib.database",
]
```

The resolver checks editable database templates before physical project templates:

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
    "VALIDATION": {"MODE": "publish_and_render"},
}
```

Create a local demo account without committing a password:

```console
HYPERTODO_DEMO_PASSWORD=local-password uv run python manage.py seed_demo
uv run python manage.py runserver
```

The seed command is idempotent. Sign in as `demo` using the password you supplied.

### Optional Redis cache

The default development configuration uses LocMem. To reuse the existing Redis service:

```console
ENABLE_REDIS_CACHE=1 REDIS_URL=redis://127.0.0.1:6379/15 uv run python manage.py runserver
```

Do not flush the shared Redis instance. HyperTodo isolates its keys by namespace and logical database.

## 2. Understand a minimal standalone mobile setup

A fresh client needs an Expo app, the released Hyperview package, its native peers, and a development client. The versions below are the tested Expo 57 matrix derived from the upstream Expo integration work while keeping Hyperview itself on npm release 0.110.0.

```console
nvm install 22.19.0
nvm use 22.19.0
corepack yarn add expo@~57.0.20 expo-dev-client@~57.0.16 hyperview@0.110.0
```

Install the native peers:

```console
corepack yarn add @react-native-community/datetimepicker@9.1.0 \
  @react-native-picker/picker@2.11.4 \
  @react-navigation/bottom-tabs@6.5.7 \
  @react-navigation/native@6.1.6 \
  @react-navigation/stack@6.3.16 \
  moment@2.30.1 react@19.2.3 react-native@0.86.3 \
  react-native-gesture-handler@~2.32.0 \
  react-native-safe-area-context@~5.7.0 \
  react-native-screens@~4.26.0 react-native-webview@13.16.1
```

Hyperview 0.110.0 advertises peer ranges from its older demo stack, so Yarn prints expected peer warnings for React, React Native, the date picker, and safe-area context. Expo Doctor is the compatibility gate for the selected Expo matrix.

The app entry point must import gesture-handler before other UI modules, register the root component, wrap Hyperview in `SafeAreaProvider` and `NavigationContainer`, and provide:

- an absolute `entrypointUrl`
- a fetch implementation that retains cookies and existing headers
- a date formatter
- optional owned loading and error screens

The complete working implementation is in `mobile/App.tsx`, `mobile/index.ts`, `mobile/src/config.ts`, and `mobile/src/network.ts`.

## 3. Configure the backend URL

```console
cd mobile
cp .env.example .env
```

For iOS Simulator, use:

```dotenv
EXPO_PUBLIC_API_URL=http://127.0.0.1:8000/hv/
```

For Android Emulator, use:

```dotenv
EXPO_PUBLIC_API_URL=http://10.0.2.2:8000/hv/
```

A physical device must use the development machine's reachable LAN address. Add that origin to `CSRF_TRUSTED_ORIGINS` and the host to `ALLOWED_HOSTS` before connecting.

## 4. Validate before running native code

```console
nvm use
corepack yarn install
corepack yarn typecheck
corepack yarn test
corepack yarn doctor
```

## 5. Create the development client

These commands generate native projects and are intentionally manual:

```console
corepack yarn ios
# or
corepack yarn android
```

After the development client exists, start Metro with:

```console
corepack yarn start
```

Open the development build, sign in, and follow the acceptance checklist. Rebuild only after changing native dependencies or native configuration.
