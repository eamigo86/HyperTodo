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

## Consumer trial in progress

Physical-iPhone testing through Expo Go is actively refining navigation, forms,
dashboard layout, gestures, and feedback. These findings are tracked in
[Lessons learned](lessons-learned.md). Android acceptance and final end-to-end
regression remain pending. Native builds are still reserved for validating native
configuration or dependencies that Expo Go cannot exercise.
