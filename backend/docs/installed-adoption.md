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

The default SQLite database begins every write transaction with `BEGIN IMMEDIATE` and waits up to 20 seconds for the write lock (`DATABASES["default"]["OPTIONS"]` in [application settings](../config/settings.py)). Without that, SQLite's deferred transactions refuse the second of two simultaneous writers at once with `database is locked`, and a double tap, two devices or two accounts saving together answered a 500 for a race the views already answer with a 422 on the right field. Writers now queue behind one another instead. A deployment on another database engine drops both options. [The concurrency test](../tests/test_sqlite_concurrency.py) runs the real write endpoints from two threads against a scratch file database; to see the failure, remove the options from a scratch copy of the settings and run `python -m tests.sqlite_race` with `DJANGO_SETTINGS_MODULE` and `HYPERTODO_RACE_DATABASE` set the way that test sets them (never against `db.sqlite3`).

### Environment variables

| Variable | Default | Effect |
| --- | --- | --- |
| `DJANGO_DEBUG` | `1` | Only the value `1` keeps DEBUG on. Any other value (`0`, `false`, an empty value, a typo) turns DEBUG off and marks the session and CSRF cookies `Secure`. Startup then refuses the public development secret key. |
| `DJANGO_SECRET_KEY` | public development key | Required when DEBUG is off (`DJANGO_DEBUG` set to anything but `1`), also for `manage.py` commands and `make backend-seed DJANGO_DEBUG=0`. Whitespace around the value is ignored, so an empty or whitespace-only value counts as unset. |
| `DJANGO_SECURE_PROXY_SSL_HEADER` | unset | Header a TLS-terminating proxy sets, written as the header (`X-Forwarded-Proto`) or as its META key (`HTTP_X_FORWARDED_PROTO`); a header name is converted to the META key, which is what Django compares. A value of `https` then counts as a secure request. Set it only behind a proxy that overwrites that header. |
| `TIME_ZONE` | `America/New_York` | Server zone: the one a request runs in when it carries no usable `X-Timezone` header ([client time zone](#client-time-zone)), and the one management commands use. |
| `HYPERTODO_REALTIME_NAMESPACE` | `hypertodo-development` | Redis PubSub namespace shared by every writer and stream worker of one deployment. |
| `HYPERTODO_SOURCE_PROBE` | follows `DJANGO_DEBUG` | Only the value `1` routes `/hv/source-probe/`, the anonymous source-precedence acceptance screen; any other value (`0`, `true`, an empty value, a typo) never does. Unset, it is routed in development only. The backend tests turn it on in their own settings. |

Behind a reverse proxy, every client reaches uvicorn from the proxy's address, and the sign-in limits below are keyed on that address (`REMOTE_ADDR`). All clients then share one budget, so anyone can lock a known username out, or every password sign-in out, for up to 15 minutes. Run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy address>` so `REMOTE_ADDR` carries the real client, trust only the address of the proxy in front of it, and make that proxy overwrite any client-supplied `X-Forwarded-For`. The Makefile development targets keep `--no-proxy-headers` on purpose, because nothing trusted sits in front of them.

The same goes for a unix socket (`uvicorn --uds`). A socket has no peer address, so `REMOTE_ADDR` is empty and every client shares one fixed bucket, exactly as behind a proxy that is not trusted; an address that does not parse lands in the same bucket. Uvicorn only reads the forwarded headers of a peer it trusts, and a socket peer can be trusted with nothing but `--forwarded-allow-ips='*'`: pass it together with `--proxy-headers` only when the socket's file permissions leave the reverse proxy as the one process able to connect, and the proxy overwrites any client-supplied `X-Forwarded-For`.

Django's four standard password validators are active for Admin and `changepassword`. `seed_demo` sets its development passwords with `set_password`, which skips them. Password sign-in, in the app and in the Django Admin login, allows 10 attempts per 15 minutes for each client address and username, and 100 failed attempts per wall-clock 15-minute window for each client address across all usernames. The address window is fixed to the clock, so a client can burst up to 200 failures across a window boundary; the average is unchanged. The account limit counts 15 minutes from its first attempt and is unaffected. A client is its address with two normalisations: an IPv6 client is its whole /64 network, because one machine is handed 2**64 addresses and could otherwise refill its budget by writing another, and an IPv4-mapped IPv6 address (`::ffff:10.1.1.1`) is the IPv4 address it wraps. A success resets the counter of the account that signed in and gives back the one address attempt it claimed, so the address budget counts failures only and a shared office address is not locked out by its own successful sign-ins; a guesser's failures stay counted whatever else they sign in to. Further attempts answer 429 (the Admin shows a form error) without checking the password. The counters live in Django's default cache: shared by all workers with `backend-run-redis` and `backend-run-device`, per process otherwise, where the local-memory cache holds up to 100,000 entries so that junk traffic cannot push a running counter out. If the cache cannot be reached, sign-in keeps working without limits and a warning is logged.

### Client time zone

A client sends `X-Timezone: <IANA name>` on every `/hv/` request, for example `X-Timezone: Europe/Madrid`; the mobile app reads it from `Intl.DateTimeFormat().resolvedOptions().timeZone`. The backend runs that request in the named zone, so the dashboard greeting, Today, Scheduled and every date a screen shows are the person's own, and the end of a date-only deadline is the last instant of that day in that zone. Overdue compares instants and needs no zone. The date an edit screen shows for a date-only deadline is read in the zone of that request, so a deadline set in another zone can show a neighbouring day; saving the screen without changing its date or time leaves the stored deadline exactly as it was, even when the zone changed while the screen was open or another device moved the deadline since: the screen carries the date and time it showed in two hidden fields, and the save compares the posted ones with those.

The value must be a name from the IANA tz database of at most 64 characters. A missing, empty, longer, malformed or unknown value is ignored without an error, and the server zone (`TIME_ZONE`, default `America/New_York`) stays in force. The zone is active only while the request runs. Every response, errors included, carries `Vary: X-Timezone` whether or not the request sent the header, so a cache never serves one zone's screen to a client in another. The event stream (`/realtime/events/`) neither reads the header nor varies on it, and Admin pages, which a browser requests without it, keep the server zone.

A date-only deadline is stored as an instant, the end of its day in the zone it was created in. A person who later reports another zone sees that same instant in the new zone, so its date can move by a day; nothing is rewritten.

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

## Verification

Permanent tests cover genuine Admin asset serving only in DEBUG, and authenticated SSE/disconnect through the DEBUG static wrapper. Run the full backend gates with installed dependencies; opt into the separate scoped Redis acceptance only against the authorized test service/UUID namespaces.
