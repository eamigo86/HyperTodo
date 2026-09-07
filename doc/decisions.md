# Decisions

## Released packages over source checkouts

The backend installs dj-hyperview 0.1.0a8 from PyPI and the client installs Hyperview 0.110.0 from npm. This makes the project a truthful external consumer. The upstream Hyperview Expo PR is used only as dependency-matrix guidance.

## Sessions and CSRF over token authentication

Django sessions exercise the framework's standard authentication and the package's HXML CSRF helper. Successful login and logout return direct HXML rather than redirects so React Native can retain the session cookie reliably.

## Database source before filesystem

Physical XML is the deployable default; an active exact-name database row is the live override. This provides safe fallback while demonstrating real-time admin editing.

## Shared Redis with hard isolation

The project reuses the user's running Redis. Database 15 is reserved for development cache and database 14 for integration tests, with separate namespaces. The project never owns the Redis process and never flushes it.

## Server-driven UI boundary

Django owns screen composition, filtering, and mutation outcomes. The mobile shell owns native bootstrapping, navigation hosting, transport, and loading/error presentation. No custom Hyperview component is introduced until a verified product requirement demands one.

## Focused mobile testing

Strict TDD and a branch-aware 95 percent threshold apply to owned Django behavior. The client gets focused tests and mandatory native smoke checks, not a misleading coverage target over third-party Hyperview behavior.
