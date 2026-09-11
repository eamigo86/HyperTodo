# Run the published package, without source-path shortcuts

**Use the locked beta `dj-hyperview[editor,realtime]==0.1.0b1` and Uvicorn in the selected environment.** No local package checkout, source METADATA fixture or appended Python environment is needed for normal HyperTodo.

This published package provides both invalidation wire versions `(1, 2)`. The matching backend and mobile host negotiate contextual v2 metadata; old clients still receive v1. Upgrade/roll back the package and backend workers together, without mixing old a21 Redis readers and v2 producers in the same namespace.

## Development startup

Use the repository [Makefile commands](../../README.md#makefile-commands) with Python 3.14/uv, Node 22.19.0 via nvm/Corepack and Expo Go for SDK 57. From the repository root, `make setup` installs both dependency sets without migration or seeding. Keep the reviewed package/app pair together.

### New disposable database

**Only for a new disposable local database:**

```console
make backend-migrate
make backend-seed
```

The development seed creates `admin` / `admin123` and `demo` / `demo123`, with separate owned tasks/categories. It can reset demo fields, so these credentials and commands belong only to trusted local development without real data. Use `HYPERTODO_ADMIN_PASSWORD` / `HYPERTODO_DEMO_PASSWORD` for chosen local passwords.

### Existing database

Run `make setup` for the reviewed dependency changes. Take a verified backup and review the migration plan before deliberately applying migrations. **Do not run `make backend-seed`** as an upgrade or repair: it changes demo data and does not replace existing template edits. Review effective [DB overrides](#adopt-database-overrides-explicitly) separately.

### Backend terminal

Redis must already be running; the Python extra installs only its client. `make lan-ip` prints a candidate address: verify it is reachable from the phone, then replace the example in both terminals with the same private computer IP.

```console
LAN_IP=192.168.1.20 make backend-run-sse
```

Every backend launcher selects Uvicorn/ASGI and the same `config.settings`, never WSGI `runserver` or a filesystem-only profile. Startup never starts Redis, migrates, seeds or changes stored template rows. Endpoints: `/hv/`, authenticated `/realtime/events/`, and `/admin/`. Normal login establishes the stream session; opening its URL in a browser is not an authentication test.

### Expo Go terminal

```console
LAN_IP=192.168.1.20 make mobile-start-go
```

Scan the QR and sign in. This uses `--go` plus explicit local HTTP opt-in; the release HTTPS guard is unchanged. No native build is needed. Keep the phone and computer on a trusted reachable network, permit development ports only as needed, and stop both terminals with Ctrl+C. Without `LAN_IP`, `backend-run-sse` binds loopback only. `mobile-start`/`mobile-start-device` use a development client, not Expo Go. `backend-run` and `backend-run-redis` bind all interfaces; `backend-run-device` also requires `LAN_IP` and sets device host/CSRF allowances. All four backend commands support SSE; only cache and bind policy differ.

## Configuration boundaries

[Application settings](../config/settings.py) always resolve active DB templates first, then filesystem fallback. `HYPERVIEW["REALTIME"]` is enabled in that same file:

```python
HYPERVIEW["REALTIME"] = {
    "REDIS_URL": REDIS_URL,
    "NAMESPACE": "hypertodo-development",
}
```

`REDIS_URL` comes from the environment and defaults to `redis://127.0.0.1:6379/15`; Make forwards its `REDIS_URL` variable to every launcher. All writers, including Admin and management commands, must use the same endpoint and namespace as stream workers. Review the namespace for each separate deployment: Redis PubSub is not isolated by database number. Do not mix old/new package workers on one namespace.

Realtime does not turn on template caching. `backend-run` and `backend-run-sse` use local-memory cache by default; `backend-run-redis` and `backend-run-device` enable Redis cache. Redis must already be available for notifications even with local-memory caching. If Redis is unavailable, committed database changes are not rolled back and notifications are not guaranteed; a later successful HTTP refresh still reads the effective template. No launcher provides replay.

Auth, database sessions, CSRF, cache and schema extensions remain in effect. Test-only settings isolate database/cache and disable transport unless a test explicitly enables it; they are not application profiles. Only DEBUG enables the development Admin/static handler; production assets belong to the web server/CDN.

## Check a real Admin update

1. Sign in as `demo` in Expo Go and keep a task visible in Tasks.
2. Open `http://192.168.1.20:8000/admin/` as `admin`; change that task's title, preserving its owner. Expect refresh **without** navigation or manual refresh, followed by feedback only after layout. Other accounts must not receive it.
3. Save from the **same device**: own-change warnings stay quiet, while normal Save feedback remains. From **another device** on the same account or Admin, change the record of an open form: expect the localized Update / Go back dialog. Both choices explicitly discard the draft; Go back requires the exact clean previous page. An unrelated task must not create this conflict.

These are manual steps, **not new native verification**. See the [mobile policy](../../mobile/docs/realtime-contextual-updates.md) for full draft, pagination and session behavior.

## Adopt database overrides explicitly

Existing active overrides become effective under **every** launcher, including `backend-run-sse`. A filesystem fix cannot replace a stale DB row. Do not restart an existing environment on the new configuration until its effective templates have been reviewed; this change does not migrate, seed, publish or rewrite them.

1. Obtain authorization for the exact database alias and take a verified backup. Run `check_hyperview_templates --database ALIAS` read-only only after approval: it checks identity integrity, **not XSD compatibility**. Stop on anomalies; do not choose winners, delete duplicates or repair automatically.
2. Review active DB rows before filesystem fallbacks, especially About and Categories. Preserve deliberate Admin edits. Compare each row with its current filesystem counterpart: keep required realtime boundaries, targets, included partials and automatic schema validation. In About, retain the `app:realtime` wrapper and `about-screen` refresh target; receiving a hint alone cannot refresh a screen whose stored HXML has no listener.
3. Validate reviewed contents in an isolated copy with approved synthetic contexts, including themes/languages and authenticated modern-session rendering. Filesystem-only success does not establish effective DB compatibility. `seed_demo` only creates absent template rows and also changes accounts/data, so it is not an upgrade tool.
4. After approval, publish only the reviewed rows with `publish_template`, explicit alias and reviewed `expected_revision`. Concurrent edits require another review, not overwriting. No application source override is needed.
5. Adopt the reviewed package, consumer configuration and lock together after effective-source review. Repeat installed-package acceptance before an authorized restart. On a synthetic account, save a reviewed About change through Admin, expect no hint until commit, then a shared `ui` hint and authenticated refresh showing the changed text. Rollbacks must not notify. Verify the actual device separately; backend tests are not native acceptance.
6. Roll back package/configuration together, never by disabling validation. DB restoration requires a separate approved backup procedure without overwriting concurrent edits. Rotate only Hyperview's namespace if necessary; never flush a shared cache.

## Disposable fixture provenance

The private launchers in `test_support` verify the consumer's exact dependency pin, imported package location, Distribution metadata and installed RECORD checksums before allocating a database. Uvicorn/h11 must come from that same selected venv. Installed mode is the default; it does not require PYTHONPATH or source metadata. A source experiment requires **both** `--source-root` and `--source-metadata`, with matching source pyproject/module path/metadata and Python `-B`; results are explicitly labelled `source`, not installed-artifact acceptance. There is no fallback between modes.

For portable fixtures, first create an empty private workspace (mode0700), then pass `--workspace /absolute/private/workspace`. Parent/report/event paths must stay inside it with no symlink traversal. Only newly allocated `native-app-*` directories with owned private config may be loaded/cleaned; original database paths are never accepted. The equivalent `HYPERTODO_FIXTURE_WORKSPACE`, `HYPERTODO_FIXTURE_SOURCE` and `HYPERTODO_FIXTURE_METADATA` environment variables are **test-support inputs**, not Django/public package settings. The application itself never reads them.

```console
# From backend/, with dependencies installed. Only fixture SQLite is initialized.
python -B -m test_support.sse_demo --workspace /absolute/private/workspace --check-only --report /absolute/private/workspace/check.json
```

This check creates and removes its own synthetic users/data. It is not a native run, never starts Redis or changes DNS, and does not inspect existing accounts or credentials. Reports contain no passwords/tokens. Serving is a separate explicit finite action, with exact bind/port and a maximum600-second lifetime. Historical machine-specific native evidence is not a reproducible installed-package command or new-version native proof.

## Verification

Permanent tests cover installed/source separation, wrong versions, missing RECORD, shadowed imports, explicit private workspace/unsafe-path rejection, genuine Admin asset serving only in DEBUG, and authenticated SSE/disconnect through that wrapper. Run the full backend gates with installed dependencies; opt into the separate scoped Redis acceptance only against the authorized test service/UUID namespaces.
