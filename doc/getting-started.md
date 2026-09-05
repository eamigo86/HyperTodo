# Getting started

This guide starts from clean Django and Expo projects. You do not need to clone the Hyperview repository or copy its demo application.

## Prerequisites

- Python 3.14 and uv
- Node 22.19.0 through nvm
- Corepack, which installs the project-pinned Yarn 1.22.22
- Xcode and CocoaPods for iOS, or Android Studio and ADB for Android
- A running Redis service only when testing cache behavior

Expo Go is not sufficient because Hyperview uses native dependencies. Use an Expo development build.

## Recommended Make workflow

Run these commands from the repository root. The first five prepare and verify
the complete project:

1. List every available command:

   ```console
   make help
   ```

   This prints each Make target and its description without changing the
   project.

2. Install the locked backend and mobile dependencies:

   ```console
   make setup
   ```

   This runs uv for Python and the project-pinned Yarn version through
   Corepack. A global Yarn installation is not required.

3. Create or update the database schema:

   ```console
   make backend-migrate
   ```

4. Create the idempotent local demo accounts and their private sample data:

   ```console
   make backend-seed
   ```

   The default credentials are `admin`/`admin123` and `demo`/`demo123` while
   Django debug mode is enabled.

5. Run all automated quality gates:

   ```console
   make check
   ```

   This runs backend linting, tests with branch-aware coverage, Django system
   and migration checks, mobile type checking, Jest, and Expo Doctor.

Then use the workflow for the target device.

### iOS Simulator

Start the Redis-backed backend in one terminal:

```console
make backend-run-redis
```

Create and install the development build the first time, or after a native
dependency or configuration change:

```console
make mobile-ios
```

For normal JavaScript, TypeScript, or HXML development, reuse that installed
build and start Metro with:

```console
make mobile-start
```

### Physical iPhone or Android device

Display the Mac address reachable from the local network:

```console
make lan-ip
```

Use that value in both terminals. For example:

```console
# Terminal 1
LAN_IP=192.168.1.20 make backend-run-device

# Terminal 2, first installation on iPhone
LAN_IP=192.168.1.20 make mobile-ios-device

# Terminal 2, first installation on Android
LAN_IP=192.168.1.20 make mobile-android-device
```

Only one mobile installation command is needed for the selected platform. On
later development sessions, keep Terminal 1 running and replace the installation
command in Terminal 2 with:

```console
LAN_IP=192.168.1.20 make mobile-start-device
```

Metro prints a QR code. Scan it with the phone camera, or select the server from
the HyperTodo development client's launcher. The familiar QR workflow remains;
the only difference is that the link must open the installed **HyperTodo**
development build instead of Expo Go.

### Android Emulator

Start the backend in one terminal:

```console
make backend-run-redis
```

Install the development build the first time with `make mobile-android`. On
later sessions, run `make mobile-start-android`. Both commands use the Android
Emulator address `10.0.2.2` to reach Django on the Mac.

### Supporting commands

| Command | Purpose |
| --- | --- |
| `make test` | Run backend pytest and mobile Jest tests. |
| `make backend-quality` | Run every backend lint, test, Django, and migration check. |
| `make backend-test-redis` | Run the isolated Redis integration tests against logical database 14. |
| `make mobile-check` | Run TypeScript, Jest, and Expo Doctor. |
| `make acceptance` | Print the manual iOS and Android acceptance checklist. |

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

Create isolated local admin and demo accounts with representative data:

```console
make backend-seed
uv run python manage.py runserver
```

The seed command is idempotent. In debug mode it creates `admin`/`admin123` and
`demo`/`demo123`. Each account owns different categories and tasks. Set both
`HYPERTODO_ADMIN_PASSWORD` and `HYPERTODO_DEMO_PASSWORD` to override the local
defaults. Explicit passwords are mandatory when debug mode is disabled.

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

## Troubleshooting: Expo Go asks you to sign in

If Expo Go displays “You need to be signed in to Expo Go and Expo CLI,” it has
opened a development-client URL with the wrong application. Signing in may
remove that Expo Go message, but it does not turn Expo Go into this project's
native runtime.

HyperTodo includes `expo-dev-client` and starts Metro with `--dev-client`.
Therefore, open the installed **HyperTodo** development build, not Expo Go.
Expo describes a development build as a project-specific version of Expo Go
that can include arbitrary native libraries and configuration.

### iOS Simulator

Close Expo Go and create the development build once:

```console
make mobile-ios
```

Then launch the **HyperTodo** icon. For later JavaScript or HXML changes, the
existing build can reconnect to Metro without recompiling:

```console
make mobile-start
```

### Physical iPhone

Connect the iPhone to the Mac, trust the computer, enable Developer Mode, and
make sure Xcode has a signing team available. Find the Mac's Wi-Fi address:

```console
make lan-ip
```

Use the resulting address in both terminals. For example:

```console
# Terminal 1
LAN_IP=192.168.1.20 make backend-run-device

# Terminal 2: first installation
LAN_IP=192.168.1.20 make mobile-ios-device
```

After HyperTodo is installed, later Metro sessions use:

```console
LAN_IP=192.168.1.20 make mobile-start-device
```

Scan Metro's QR code with the iPhone camera so that it opens the installed
**HyperTodo** development build, or open HyperTodo and select the server from
its launcher. Do not open the QR link in Expo Go. The Mac and iPhone must share
a reachable network, and macOS must allow incoming connections to the Django
and Metro processes. Test
`http://LAN_IP:8000/hv/` from Safari on the iPhone if the app cannot reach the
backend.

Expo's official local-build flow uses `expo run:ios --device` for a connected
iPhone and does not require an Expo account. EAS cloud builds are a separate
option and do require Expo authentication. See the official
[development-build introduction](https://docs.expo.dev/develop/development-builds/introduction/)
and [local app development guide](https://docs.expo.dev/guides/local-app-development/).

### Physical Android device

Enable USB debugging, connect the device, and run:

```console
make lan-ip
LAN_IP=192.168.1.20 make mobile-android-device
```

Use the same address with `LAN_IP=... make backend-run-device` when the Android
device connects over Wi-Fi. The `10.0.2.2` address applies only to the Android
Emulator.
