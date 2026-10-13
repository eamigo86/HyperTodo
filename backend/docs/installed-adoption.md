# Run the published package, without source-path shortcuts

**Use the locked beta `dj-hyperview[editor,realtime]==0.1.0b2` and Uvicorn in the selected environment.** No local package checkout, source METADATA fixture or appended Python environment is needed for normal HyperTodo.

This published package provides both invalidation wire versions `(1, 2)`. The matching backend and mobile host negotiate contextual v2 metadata; old clients still receive v1. Upgrade/roll back the package and backend workers together, without mixing old a21 Redis readers and v2 producers in the same namespace.

## Development startup

Use the repository [Makefile commands](../../README.md#makefile-commands) with Python 3.14/uv, Node 22.19.0 via nvm/Corepack and Expo Go for SDK 57. From the repository root, `make setup` installs both dependency sets without migration or seeding. Keep the reviewed package/app pair together.

### New disposable database

**Only for a new disposable local database:**

```console
make backend-migrate
make backend-seed
```

The development seed creates `admin` / `admin123` and `demo` / `demo123`, with separate owned tasks/categories. It can reset demo fields, so these credentials and commands belong only to trusted local development without real data. Use `HYPERTODO_ADMIN_PASSWORD` / `HYPERTODO_DEMO_PASSWORD` for chosen local passwords, and set both before binding beyond loopback.

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

Scan the QR and sign in. This uses `--go` plus explicit local HTTP opt-in; the release HTTPS guard is unchanged. No native build is needed. Keep the phone and computer on a trusted reachable network, permit development ports only as needed, and stop both terminals with Ctrl+C. Without `LAN_IP`, `backend-run-sse` binds loopback only. `mobile-start`/`mobile-start-device` use a development client, not Expo Go. `backend-run` and `backend-run-redis` bind loopback only, which also serves the iOS simulator and, as `10.0.2.2`, the Android emulator; only `backend-run-device` binds all interfaces, requires `LAN_IP` and sets device host/CSRF allowances. All four backend commands support SSE; only cache and bind policy differ.

## Configuration boundaries

[Application settings](../config/settings.py) always resolve active DB templates first, then filesystem fallback. `HYPERVIEW["REALTIME"]` is enabled in that same file:

```python
HYPERVIEW["REALTIME"] = {
    "REDIS_URL": REDIS_URL,
    "NAMESPACE": os.environ.get(
        "HYPERTODO_REALTIME_NAMESPACE", "hypertodo-development"
    ),
}
```

`REDIS_URL` comes from the environment and defaults to `redis://127.0.0.1:6379/15`; Make forwards its `REDIS_URL` variable to every launcher. All writers, including Admin and management commands, must use the same endpoint and namespace as stream workers. Give each separate deployment its own `HYPERTODO_REALTIME_NAMESPACE`: Redis PubSub is not isolated by database number. Do not mix old/new package workers on one namespace.

Realtime does not turn on template caching. `backend-run` and `backend-run-sse` leave the dj-hyperview template cache off; `backend-run-redis` and `backend-run-device` enable the Redis template cache. Redis must already be available for notifications even without it. If Redis is unavailable, committed database changes are not rolled back and notifications are not guaranteed; a later successful HTTP refresh still reads the effective template. No launcher provides replay.

Auth, database sessions, CSRF, cache and schema extensions remain in effect. Test-only settings isolate database/cache and disable transport unless a test explicitly enables it; they are not application profiles. Only DEBUG enables the development Admin/static handler; production assets belong to the web server/CDN.

### Environment variables

| Variable | Default | Effect |
| --- | --- | --- |
| `DJANGO_DEBUG` | `1` | Only the value `1` keeps DEBUG on. Any other value (`0`, `false`, an empty value, a typo) turns DEBUG off and marks the session and CSRF cookies `Secure`. Startup then refuses the public development secret key. |
| `DJANGO_SECRET_KEY` | public development key | Required when DEBUG is off (`DJANGO_DEBUG` set to anything but `1`), also for `manage.py` commands and `make backend-seed DJANGO_DEBUG=0`. Whitespace around the value is ignored, so an empty or whitespace-only value counts as unset. |
| `DJANGO_SECURE_PROXY_SSL_HEADER` | unset | Header a TLS-terminating proxy sets, written as the header (`X-Forwarded-Proto`) or as its META key (`HTTP_X_FORWARDED_PROTO`); a header name is converted to the META key, which is what Django compares. A value of `https` then counts as a secure request. Set it only behind a proxy that overwrites that header. |
| `HYPERTODO_REALTIME_NAMESPACE` | `hypertodo-development` | Redis PubSub namespace shared by every writer and stream worker of one deployment. |
| `HYPERTODO_SOURCE_PROBE` | follows `DJANGO_DEBUG` | Only the value `1` routes `/hv/source-probe/`, the anonymous source-precedence acceptance screen; any other value (`0`, `true`, an empty value, a typo) never does. Unset, it is routed in development only. The backend tests turn it on in their own settings. |

Behind a reverse proxy, every client reaches uvicorn from the proxy's address, and the sign-in limits below are keyed on that address (`REMOTE_ADDR`). All clients then share one budget, so anyone can lock a known username out, or every password sign-in out, for 15 minutes. Run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy address>` so `REMOTE_ADDR` carries the real client, trust only the address of the proxy in front of it, and make that proxy overwrite any client-supplied `X-Forwarded-For`. The Makefile development targets keep `--no-proxy-headers` on purpose, because nothing trusted sits in front of them.

The same goes for a unix socket (`uvicorn --uds`). A socket has no peer address, so `REMOTE_ADDR` is empty and every client shares one fixed bucket, exactly as behind a proxy that is not trusted; an address that does not parse lands in the same bucket. Uvicorn only reads the forwarded headers of a peer it trusts, and a socket peer can be trusted with nothing but `--forwarded-allow-ips='*'`: pass it together with `--proxy-headers` only when the socket's file permissions leave the reverse proxy as the one process able to connect, and the proxy overwrites any client-supplied `X-Forwarded-For`.

Django's four standard password validators are active for Admin and `changepassword`. `seed_demo` sets its development passwords with `set_password`, which skips them. Password sign-in, in the app and in the Django Admin login, allows 10 attempts per 15 minutes for each client address and username, and 100 failed attempts per 15 minutes for each client address across all usernames. A client is its address with two normalisations: an IPv6 client is its whole /64 network, because one machine is handed 2**64 addresses and could otherwise refill its budget by writing another, and an IPv4-mapped IPv6 address (`::ffff:10.1.1.1`) is the IPv4 address it wraps. A success resets the counter of the account that signed in and gives back the one address attempt it claimed, so the address budget counts failures only and a shared office address is not locked out by its own successful sign-ins; a guesser's failures stay counted whatever else they sign in to. Further attempts answer 429 (the Admin shows a form error) without checking the password. The counters live in Django's default cache: shared by all workers with `backend-run-redis` and `backend-run-device`, per process otherwise, where the local-memory cache holds up to 100,000 entries so that junk traffic cannot push a running counter out. If the cache cannot be reached, sign-in keeps working without limits and a warning is logged.

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
