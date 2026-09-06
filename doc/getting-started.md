# Getting started

This guide starts from clean Django and Expo projects. You do not need to clone
the Hyperview repository or copy its demo application.

Choose the path that matches your goal:

- **Run HyperTodo:** follow the recommended Make workflow.
- **Create a separate Hyperview client:** start at section 2.
- **Use a native dependency not bundled in Expo Go:** continue through section 5
  and create a development build.

## Prerequisites

- Python 3.14 and uv
- Node 22.19.0 through nvm
- Corepack, which installs the project-pinned Yarn 1.22.22
- Expo Go on a physical device for the shortest local feedback loop
- Xcode and CocoaPods, or Android Studio and ADB, only for development builds
- A running Redis service only when testing cache behavior

Expo Go supports the native libraries required by the tested Expo 57 and
Hyperview 0.110.0 matrix. It is the quickest option for local QR-based testing.
A development build remains available for validating project-specific native
configuration and production-like behavior.

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

Use that value in both terminals. The normal Expo Go workflow is:

```console
# Terminal 1
LAN_IP=192.168.1.20 make backend-run-device

# Terminal 2
LAN_IP=192.168.1.20 make mobile-start-go
```

Metro prints a QR code. Scan it with the phone camera and open the link in Expo
Go. Both devices must be on the same reachable local network. This command does
not expose Metro or Django on the public internet.

No custom mobile installation is required for this flow. If a development build
is needed later, install it once with `LAN_IP=... make mobile-ios-device` or
`LAN_IP=... make mobile-android-device`. Start its later Metro sessions with
`LAN_IP=... make mobile-start-device`.

Expo Go requires Expo CLI and the mobile app to be signed in with the same Expo
account. Confirm the CLI account with `make mobile-whoami`. If it reports
`Not logged in`, run `make mobile-login`. The browser opens Expo.dev, where
Google-based accounts can select **Continue with Google** without entering a
Google password in the terminal. Use the same account in Expo Go.

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
| `make mobile-login` | Open browser authentication for Expo CLI manifest signing. |
| `make mobile-whoami` | Display the Expo account currently used by the CLI. |
| `make mobile-start-go` | Start Metro on the LAN and generate a QR code for Expo Go. |
| `make mobile-start-device` | Start Metro for an already installed custom development build. |
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

## 2. Create a standalone mobile client

Create a blank TypeScript Expo project. The `--no-install` option lets the project
use the chosen package manager from the first lockfile:

```console
nvm install 22.19.0
nvm use 22.19.0
corepack enable
npx create-expo-app@latest hyperview-mobile --template blank-typescript --no-install
cd hyperview-mobile
corepack yarn set version classic
```

The `blank-typescript` and `--no-install` options are documented by
[create-expo-app](https://docs.expo.dev/more/create-expo/). This creates an
ordinary Expo application rather than copying Hyperview's example project.

Install the released Hyperview package and the tested Expo 57 dependency matrix:

```console
corepack yarn add expo@~57.0.20 hyperview@0.110.0
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

Create `index.ts` and point the `main` field in `package.json` to it:

```typescript
import "react-native-gesture-handler";
import { registerRootComponent } from "expo";

import App from "./App";

registerRootComponent(App);
```

The application shell must import gesture-handler before other UI modules, wrap
Hyperview in `SafeAreaProvider` and `NavigationContainer`, and provide:

- an absolute `entrypointUrl`
- a fetch implementation that retains cookies and existing headers
- a date formatter
- optional owned loading and error screens

Start with no custom components or behaviors. Add them only after a verified native
interaction cannot be expressed in HXML. The complete working implementation is in
`mobile/App.tsx`, `mobile/index.ts`, `mobile/src/config.ts`, and
`mobile/src/network.ts`.

### Expo Go or development build?

| Situation | Use |
| --- | --- |
| All required native modules are already bundled by Expo Go | `expo start --go` |
| JavaScript, TypeScript, or server-rendered HXML changed | Reuse the current client; do not rebuild |
| A native dependency or native configuration changed | Development build |
| Launcher icon, bundle metadata, or production-like native behavior must be verified | Development or release build |

Expo describes a development build as a custom version of Expo Go that includes
project-selected native code. See the official
[development-build introduction](https://docs.expo.dev/develop/development-builds/introduction/).

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

## 5. Optionally create a development client

Skip this section while Expo Go satisfies the dependency matrix. Install
`expo-dev-client` only when the application needs native code or configuration
that Expo Go cannot provide:

```console
corepack yarn add expo-dev-client@~57.0.16
```

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

## Troubleshooting: a replace action rejects the `doc` element

The message `XMLRestrictedElementFound: Restricted <doc> tag found in the
response` means the request reached Django, but the response shape does not match
the action. A `new` navigation action can load a complete HXML document. A
`replace` action must receive a fragment or transition compatible with its target.

Check these items in order:

1. Confirm whether the originating action is `new`, `replace`, or `append`.
2. Inspect the Django response body and media type.
3. Return only the expected target fragment for an in-place mutation.
4. Give the target a stable ID and assert it in the endpoint test.
5. If a custom component calls Hyperview's `onUpdate`, pass `targetId` explicitly
   for a replacement without a behavior element.

Do not hide this error in the mobile shell. Correct the server response contract.

## Troubleshooting: Expo Go asks you to sign in

If Expo Go displays “You need to be signed in to Expo Go and Expo CLI,” Metro
cannot verify the development manifest. Check the CLI session:

```console
make mobile-whoami
```

If it reports `Not logged in`, sign in:

```console
make mobile-login
```

Complete authentication in the browser. A Google-based Expo account should use
**Continue with Google**; never enter the Google password directly in the
terminal. Sign in to Expo Go on the phone with the same Expo account. Stop the
existing Metro process with Control-C and start a fresh Expo Go session:

```console
make lan-ip
LAN_IP=192.168.1.20 make mobile-start-go
```

Scan the new QR code with the phone camera and open it in Expo Go. Authentication
signs and authorizes the local manifest; it does not publish the application or
expose Metro or Django on the public internet.

Use the remaining sections only when testing a custom development build.

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

After HyperTodo is installed, later custom development-build sessions use:

```console
LAN_IP=192.168.1.20 make mobile-start-device
```

Scan Metro's QR code with the iPhone camera so that it opens the installed
**HyperTodo** development build, or open HyperTodo and select the server from
its launcher. This particular QR is for the custom client, not Expo Go. The Mac
and iPhone must share a reachable network, and macOS must allow incoming
connections to the Django and Metro processes. Test
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
