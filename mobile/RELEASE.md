# Store release checklist

Everything in this file is an account or infrastructure action. None of it can live in the repo,
and the build is intentionally impossible to complete until items 1 and 2 are done.

## How the build guard works

`app.config.ts` resolves `EXPO_PUBLIC_API_URL` at config resolution time. Expo evaluates that file
during `expo config`, `expo prebuild`, and again inside the native build (expo-constants writes
`extra.apiUrl` into the app bundle), so a missing or wrong URL fails the build loudly instead of
producing a binary that talks to `127.0.0.1`.

It fails **closed**. Release detection is not something store safety can hang on: `expo prebuild`
followed by an Xcode Archive sets no EAS variable at all, and that native build phase re-resolves
this same file. So localhost and cleartext are an explicit developer opt-in instead:

- Without `EXPO_PUBLIC_API_URL`, resolution throws unless `EXPO_PUBLIC_ALLOW_LOCAL_API` is set
  (`1`/`true`). Development machines set it in `mobile/.env` — see `mobile/.env.example`; `.env` is
  gitignored, so it never reaches an EAS upload.
- A non-`https` URL is accepted only for loopback, `.local`, private IPv4, or local IPv6 hosts, only with that
  opt-in, and **never** on an EAS profile other than `development` — pasting the `.env.example` URL
  into the EAS `production` environment throws rather than shipping cleartext.
- `EAS_BUILD` is read boolish (`1` counts as `true`), the way Expo's own CLI reads it.
- Android cleartext (`usesCleartextTraffic`) and iOS `NSAppTransportSecurity.NSAllowsLocalNetworking`
  are both derived from that one URL's scheme. There is no second switch to forget.

## Owner tasks

1. **Deploy the Django backend behind https** and set `EXPO_PUBLIC_API_URL` (e.g.
   `https://api.example.com/hv/`) as an EAS environment variable in the `production` environment.
   Its type must be **plain text** or **sensitive**. A **secret**-type variable is NOT readable while
   the app config is resolved and the build will fail with the guard's error message.

2. **Demo credentials.** The app is 100% login-walled and has no sign-up, so a reviewer cannot get in
   without them. Seed an account on the production server (`backend/todo/management/commands/seed_demo.py`)
   and enter the credentials in:
   - App Store Connect → App Review Information → Sign-In Required (Apple guideline 2.1(a))
   - Play Console → App content → App access
   Missing this is a first-round rejection on both stores.

3. **Privacy policy URL.** Mandatory on both stores. Host it and paste it into both listings.

4. **`eas init`**, then add the returned `extra.eas.projectId` (and `owner`) to `app.config.ts` by hand.
   EAS CLI cannot write into a function-export dynamic config. Until this is done `eas build` cannot
   run at all, because `cli.appVersionSource: "remote"` and `build.production.autoIncrement` both need
   a linked project. `eas.json` also declares `cli.version: ">= 13.2.0"`, because
   `build.production.environment` (EAS environments) is not understood by older CLIs.

   `submit.production` is deliberately empty: fill in `ascAppId` (iOS) and `serviceAccountKeyPath`
   (Android) before any `eas submit --non-interactive`, or it fails on missing credentials instead of
   prompting.

5. **App Store Connect → App Privacy**
   - Data used to track you: **none** (no ATT prompt, no tracking SDK).
   - Data linked to you: **Identifiers → User ID** (username + session cookie), purpose App Functionality;
     **User Content → Other User Content** (task titles, notes, due dates, category names), purpose App Functionality;
     **Contact Info → Name** and **Contact Info → Email Address**, purpose App Functionality — the Settings
     screen posts `first_name`, `last_name` and `email` to `/hv/settings/` and the server persists them
     (`ProfileForm` in `backend/todo/forms.py`, `update_profile` in `backend/todo/services.py`);
     **User Content → Photos or Videos**, purpose App Functionality — the Settings screen posts a
     chosen photo through `/hv/settings/`, and the server stores it under `MEDIA_ROOT` and serves it back
     (`AvatarForm` in `backend/todo/forms.py`, `store_avatar` in `backend/todo/services.py`).
     The photo is re-encoded server-side and its EXIF, including GPS, is discarded — but it is still
     collected and persisted, so it is declared.
   - Everything else: No — Location, Contacts, Health, Financial, Browsing/Search History,
     Usage Data, Diagnostics, Purchases, Sensitive Info.
   - There is no separate "password" data type; the login credential is covered by Identifiers → User ID.

6. **Play Console → Data safety**
   - Collected and sent off device: Personal info → User IDs, Name, Email address; App activity / other
     user-generated content (task titles, notes, category names); **Photos and videos → Photos**
     (optional, purpose App functionality — the profile picture).
   - Shared with third parties: No.
   - Encrypted in transit: Yes — true only once the production URL is https, which item 1 enforces.
   - Data deletion: there is no in-app deletion path; provide a contact route or answer No.
   - Biometrics/Health: No. `expo-local-authentication` returns a boolean; the rotating device token
     lives in Keychain/Keystore (`WHEN_UNLOCKED_THIS_DEVICE_ONLY`) and never leaves the device.
   - Permissions after `blockedPermissions`: INTERNET, USE_BIOMETRIC, USE_FINGERPRINT, VIBRATE.
     None requires a sensitive-permission declaration. **Re-derive this list from a prebuilt
     manifest** (`npx expo prebuild -p android --clean`, then read
     `android/app/src/main/AndroidManifest.xml`) rather than editing it by hand.
   - **No Photo and Video Permissions declaration is needed** for the avatar picker. Verified in the
     installed module source, not assumed: `expo-image-picker`'s library path builds an
     `ActivityResultContracts.PickVisualMedia` intent — the system Photo Picker, which needs no
     permission on any API level (`node_modules/expo-image-picker/android/src/main/java/expo/modules/imagepicker/contracts/ImageLibraryContract.kt`),
     and `launchImageLibraryAsync` never calls the permission helper at all. That helper
     (`ImagePickerModule.kt:258`) returns an **empty array** on API 33+ anyway.
   - Related, and the reason `blockedPermissions` was left alone: the module's own manifest declares
     `READ_EXTERNAL_STORAGE` / `WRITE_EXTERNAL_STORAGE` at `maxSdkVersion="32"`, and `app.config.ts`
     strips both at merge time. Picking still works, because the code paths above never request them.
     If a picker bug ever appears on an old Android device, verify against the prebuilt manifest
     before touching that block list — `__tests__/app-config.test.ts` fails if it is edited.

7. **iPad is off.** `ios.supportsTablet` is `false`: the design is portrait-only and phone-shaped, so
   claiming iPad support would add an iPad review surface and mandatory 13" iPad screenshots. Turning
   it on later is a normal app update, not a breaking change.

8. **Serve `MEDIA_URL` in production.** `config/urls.py` serves `/media/` only when `DEBUG` is on;
   that branch is a development convenience and returns nothing in a release. Production must serve
   `MEDIA_ROOT` from the web server or object storage, with **directory listing off**, on storage
   that survives a deploy. An ephemeral container filesystem loses every avatar on the next release
   while every gate in this repo stays green. Avatar filenames are unguessable (`uuid4().hex`), which
   is what makes an unauthenticated URL acceptable — do not add an index that enumerates them.

9. **This release needs a NEW NATIVE BUILD.** `expo-image-picker` and `expo-image-manipulator` are
   native modules, and there is no `expo-updates` dependency and no OTA channel anywhere in the tree,
   so an over-the-air push cannot deliver them. `app.config.ts` `version` is `1.2.0`, and the server
   reads that off `X-App-Version` (`MIN_AVATAR_UPLOAD_VERSION` in `backend/todo/views.py`) to decide
   whether to render the "Change photo" row at all — `pick-avatar` is a custom action, and Hyperview
   ignores an unregistered action silently, so a 1.1.0 binary would otherwise show a dead control.
   **Keep the server gate until 1.2.0 is the installed floor.**

10. **Before the first build**, confirm what EAS uploads: this is a single git repo with `backend/` and
   `mobile/` as siblings, and there is a large uncommitted working tree. Check the reported archive
   size on the first `eas build`, and see `cli.requireCommit` if committed-only state is wanted.

11. **Known and accepted: OS chrome stays light while the app is dark.** The theme this app draws
    follows the SERVER preference (`todo/theme.py` → the stylesheet, `X-HyperTodo-Theme` → the native
    shell), not the OS appearance. Two surfaces cannot be reached from there, and both are deliberate,
    not oversights:

    - **The native splash.** `app.config.ts` pins `expo-splash-screen` `backgroundColor` to the light
      canvas `#F7F8FC`, so a dark-preference user gets a full-brightness frame for the native launch
      window (roughly 0.5–1.5s on a cold bundle) before `AnimatedSplash` mounts, reads the stored
      preference synchronously and repaints `#0F1118`. The plugin's `dark` variant keys off the OS
      appearance, which is the *wrong* signal here: it would flash a dark splash at a light-preference
      user on a dark phone. Do not ship the OS-coupled variant to make the flash go away. The honest
      alternatives are to accept it, or to pick one splash `backgroundColor` that is tolerable in both
      palettes and change `assets/splash-icon.png` to suit — a design decision, not a bug fix.
    - **`userInterfaceStyle: "light"`.** Every native surface the app raises therefore renders light
      chrome over a dark canvas: the delete confirmation (`SwipeRow.tsx` → `Alert.alert`), the keyboard
      on the login, task-form, category-form and settings fields, the `expo-image-picker` library
      sheet, and the scroll indicators. Flipping it to `"automatic"` couples all of them to the OS
      instead of the account, which is a different wrong answer. The one that is genuinely fixable
      in-app is the delete confirmation: an HXML dialog instead of `Alert.alert` would follow the
      palette AND remove the only untranslated "Cancel" string in the app. Worth doing; out of scope
      for this release.

    Both are cosmetic, both need a **new native build** to change (`app.config.ts` feeds `prebuild`),
    and neither is covered by a test because neither is expressible in JS.

## Not applicable

- Account deletion UI (Apple 5.1.1(v)): the app has no in-app account creation.
- iOS privacy manifest: `PrivacyInfo.xcprivacy` is generated by the Expo template and already correct.
  Do not hand-edit it — `ios/` is gitignored and regenerated by prebuild.
- Android `targetSdk`: already 36.
