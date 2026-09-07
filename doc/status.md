# Status

## Completed

- Repository layout and reproducible Python/Node versions.
- Django TODO domain, admin, migrations, selectors, services, and demo seed command.
- Session-authenticated, CSRF-protected HXML endpoint contract without redirects.
- Pastel dashboard, task, category, login, loading, and error interfaces.
- Filesystem defaults, database overrides, LocMem, and isolated shared-Redis tests.
- Expo 57 and Hyperview 0.110.0 shell for iOS and Android.
- Automated backend, mobile, type, lint, and Expo compatibility checks.
- Architecture, setup, testing, decision, acceptance, and findings documents.
- Animated splash handoff, native safe areas, themed error handling, and offline recovery feedback.
- Biometric login lifecycle, profile settings, language/theme preferences, and avatar uploads.
- Explicit dj-hyperview 0.1.0a8 document and validated-fragment response contracts.

## Consumer trial in progress

Physical-iPhone testing has refined navigation, forms, dashboard layout, gestures,
feedback, biometrics, themes, and avatar handling. These findings are tracked in
[Lessons learned](lessons-learned.md). Formal iOS and Android regression evidence,
including a live database-template override, remains pending. Native builds remain
required for store configuration and capabilities Expo Go cannot exercise fully.
