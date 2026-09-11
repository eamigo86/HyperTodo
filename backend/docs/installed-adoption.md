# Run the published package, without source-path shortcuts

**Use the locked beta `dj-hyperview[editor,realtime]==0.1.0b1` and Uvicorn in the selected environment.**
No local package checkout, source METADATA fixture or appended Python environment is needed for normal HyperTodo.

This published package provides both invalidation wire versions `(1, 2)`. The
matching backend and mobile host negotiate contextual v2 metadata; old clients
still receive v1. Upgrade/roll back the package and backend workers together,
without mixing old a21 Redis readers and v2 producers in the same namespace.

## Development startup

Use the repository [Makefile commands](../../README.md#makefile-commands) with
Python 3.14/uv, Node 22.19.0 via nvm/Corepack and Expo Go for SDK 57. From the
repository root, `make setup` installs both dependency sets without migration or
seeding. Keep the reviewed package/app pair together.

### New disposable database

**Only for a new disposable local database:**

```console
make backend-migrate
make backend-seed
```

The development seed creates `admin` / `admin123` and `demo` / `demo123`, with
separate owned tasks/categories. It can reset demo fields, so these credentials
and commands belong only to trusted local development without real data. Use
`HYPERTODO_ADMIN_PASSWORD` / `HYPERTODO_DEMO_PASSWORD` for chosen local passwords.

### Existing database

Run `make setup` for the reviewed dependency changes. Take a verified backup and
review the migration plan before deliberately applying migrations.
**Do not run `make backend-seed`** as an upgrade or repair: it changes demo data
and does not replace existing template edits. Review effective
[DB overrides](#adopt-database-overrides-explicitly) separately.

### Backend terminal

Redis must already be running; the Python extra installs only its client.
`make lan-ip` prints a candidate address: verify it is reachable from the phone,
then replace the example in both terminals with the same private computer IP.

```console
LAN_IP=192.168.1.20 make backend-run-sse
```

This selects Uvicorn/ASGI and `config.settings_sse`, not WSGI `runserver`. It
never starts Redis, migrates, seeds or changes stored template rows. Endpoints:
`/hv/`, authenticated `/realtime/events/`, and `/admin/`. Normal login establishes
the stream session; opening its URL in a browser is not an authentication test.

### Expo Go terminal

```console
LAN_IP=192.168.1.20 make mobile-start-go
```

Scan the QR and sign in. This uses `--go` plus explicit local HTTP opt-in;
the release HTTPS guard is unchanged. No native build is needed. Keep the phone
and computer on a trusted reachable network, permit development ports only as
needed, and stop both terminals with Ctrl+C. Without `LAN_IP`, the backend binds
loopback only. `mobile-start`/`mobile-start-device` use a development client,
not Expo Go; the older backend targets use WSGI, not SSE.

## Configuration boundaries

[Normal settings](../config/settings.py) are DB-template-first with realtime
`None`. [settings_sse.py](../config/settings_sse.py) preserves the full mapping
except filesystem-only SOURCES and the explicit transport block:

```python
HYPERVIEW["REALTIME"] = {
    "REDIS_URL": "redis://127.0.0.1:6379/15",
    "NAMESPACE": "hypertodo-development",
}
```

This is an edit to the existing profile, not standalone settings. Change that
block for another reviewed endpoint; the Make `REDIS_URL` variable used by cache
targets does not override it. PubSub is not isolated by database number: use a
separate app/environment namespace. It does not configure CACHE.

The profile leaves stored DB-template rows untouched and does not use them as
HXML. For reviewed DB overrides, retain normal SOURCES, set REALTIME explicitly
and serve `config.asgi:application` through ASGI. Do not mix old/new package
workers on one SSE namespace. Omitted/None disables transport, never validation;
remove retired `HYPERTODO_REALTIME` even if None. No CACHE alias adapter exists.
Auth, database sessions, CSRF, cache and schema extensions remain in effect.
Only DEBUG enables the development Admin/static handler; production assets
belong to the web server/CDN.

## Check a real Admin update

1. Sign in as `demo` in Expo Go and keep a task visible in Tasks.
2. Open `http://192.168.1.20:8000/admin/` as `admin`; change that task's title,
   preserving its owner. Expect refresh **without** navigation or manual refresh,
   followed by feedback only after layout. Other accounts must not receive it.
3. Save from the **same device**: own-change warnings stay quiet, while normal
   Save feedback remains. From **another device** on the same account or Admin,
   change the record of an open form: expect the localized Update / Go back dialog.
   Both choices explicitly discard the draft; Go back requires the exact clean
   previous page. An unrelated task must not create this conflict.

These are manual steps, **not new native verification**. See the
[mobile policy](../../mobile/docs/realtime-contextual-updates.md) for full draft,
pagination and session behavior.

## Adopt database overrides explicitly

1. Obtain authorization for the exact alias and take a verified backup. Run
   `check_hyperview_templates --database ALIAS` read-only: it checks identity
   integrity, **not XSD compatibility**. Stop on anomalies; do not choose winners,
   delete duplicates or repair automatically.
2. Review active DB rows before filesystem fallbacks, especially About and
   Categories. Preserve deliberate Admin edits; `seed_demo` only creates absent
   template rows and also changes accounts/data, so it is not an upgrade tool.
3. Validate reviewed contents in an isolated copy with approved synthetic
   contexts. Filesystem-only success does not establish effective DB compatibility.
4. After approval, publish with `publish_template`, explicit alias and reviewed
   `expected_revision`. Concurrent edits require another review, not overwriting.
5. Adopt the reviewed package, consumer configuration and lock together after
   effective-source review. Repeat installed-package acceptance before restart;
   if validation fails, keep the existing reviewed pair. There is no later toggle.
6. Roll back package/configuration together, never by disabling validation. DB
   restoration requires a separate approved backup procedure without overwriting
   concurrent edits. Rotate only Hyperview's namespace if necessary; never flush
   a shared cache.

## Disposable fixture provenance

The private launchers in `test_support` verify the consumer's exact dependency pin,
imported package location, Distribution metadata and installed RECORD checksums
before allocating a database. Uvicorn/h11 must come from that same selected venv.
Installed mode is the default; it does not require PYTHONPATH or source metadata.
A source experiment requires **both** `--source-root` and `--source-metadata`, with
matching source pyproject/module path/metadata and Python `-B`; results are explicitly
labelled `source`, not installed-artifact acceptance. There is no fallback between modes.

For portable fixtures, first create an empty private workspace (mode0700), then pass
`--workspace /absolute/private/workspace`. Parent/report/event paths must stay inside
it with no symlink traversal. Only newly allocated `native-app-*` directories with
owned private config may be loaded/cleaned; original database paths are never accepted.
The equivalent `HYPERTODO_FIXTURE_WORKSPACE`, `HYPERTODO_FIXTURE_SOURCE` and
`HYPERTODO_FIXTURE_METADATA` environment variables are **test-support inputs**, not
Django/public package settings. The application itself never reads them.

```console
# From backend/, with dependencies installed. Only fixture SQLite is initialized.
python -B -m test_support.sse_demo --workspace /absolute/private/workspace --check-only --report /absolute/private/workspace/check.json
```

This check creates and removes its own synthetic users/data. It is not a native run,
never starts Redis or changes DNS, and does not inspect existing accounts or credentials.
Reports contain no passwords/tokens. Serving is a separate explicit finite action,
with exact bind/port and a maximum600-second lifetime. Historical machine-specific
native evidence is not a reproducible installed-package command or new-version native proof.

## Verification

Permanent tests cover installed/source separation, wrong versions, missing RECORD,
shadowed imports, explicit private workspace/unsafe-path rejection, genuine Admin
asset serving only in DEBUG, and authenticated SSE/disconnect through that wrapper.
Run the full backend gates with installed dependencies; opt into the separate scoped
Redis acceptance only against the authorized test service/UUID namespaces.
