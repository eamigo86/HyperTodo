# Verify the isolated native-app backend fixture

> Current portable installed-package commands and provenance are described in
> [installed adoption](installed-adoption.md). Machine-specific paths below are
> historical evidence, not defaults required to run HyperTodo.

This **test-only source fixture** exercises real Django session/auth/CSRF and
ordinary ASGI HTTP. It does not implement SSE, enable the production transport,
advertise Bonjour, launch Metro or claim native/Android/full Gate0 acceptance.
Its launcher defaults to **127.0.0.1 on an ephemeral port**. An explicit test-only
RFC1918 IPv4 and unprivileged port can be selected for a later coordinated native
run; wildcard/public/hostname binds are rejected. It cleans its own temporary
database and credentials when it finishes. This unit tested only loopback; private
LAN/interface availability, fresh DNS and device execution remain pending.

## Run only from the isolated worktree

Use the existing Python3.14/Django6.1.1 consumer dependencies read-only. The source
METADATA fixture must already have been generated from the isolated package's
actual `pyproject.toml`; this is **source integration, not installed packaging**.
The launcher verifies package `__file__`, distribution path/name/version and
Python/Django before allocating a database. A serving run also verifies existing
Uvicorn0.34/h110.14 via process-local **append-only** resolution of the known
pure-Python dependency directory, before database setup. Nothing is installed.

```sh
ROOT=/private/tmp/djhv-sse-20260908
cd "$ROOT/hypertodo/backend"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$ROOT/evidence/runtime-source-metadata:$ROOT/django-hv/src:$ROOT/hypertodo/backend"
PYTHON='/Users/eamigo/Documents/Mis Tests/dj-hyperview-test/backend/.venv/bin/python'

# No listener: migrate/seed a NEW temporary database, verify Django, clean it.
"$PYTHON" -B -m test_support.native_app --check-only \
  --report "$ROOT/evidence/environment/native-app-fixture-check.json"

# Optional authorized loopback run, never a phone/LAN handoff.
"$PYTHON" -B -m test_support.native_app --seconds 30 \
  --report "$ROOT/evidence/environment/native-app-fixture-loopback.json"
```

The stdout listener record contains only the fresh hostname and actual port.
A loopback HTTP probe must connect to127.0.0.1 but send exactly that hostname and
port in `Host`; using the original IP/hostname as Host is rejected. The record
indicates a bound listener, not successful HTTP/native evidence. The permanent
socket test makes an actual request and verifies exit, refused subsequent
connection and deleted private resources. A report `passed` means fixture checks
and finite lifecycle completed; it is not a native stream/abort claim.

## Resource and security contract

- Each invocation creates a **new**0700 `native-app-*` directory below the
  isolated run's `runtime-private` directory. SQLite, media/uploads/tmp and0600
  configuration/credentials stay there; parent/symlink/path checks prevent
  falling through to the original project DB. Secrets are generated for this
  run. No original DB, auth state, environment credentials or enrollment is copied.
- Existing migrations run only on the newly allocated SQLite file; no migrations
  are edited and `seed_demo` is never invoked. Two fictional owners get separate
  categories and two tasks each; a separate fictional admin is created. Only
  explicit `--paginated` adds20 owner-A tasks (22A+2B total), verified through real
  filtered page1/document and page2/items requests. Default4-task checks remain. Normal
  Django hashing/authentication and model ownership remain authoritative.
- Explicit fixture settings replace database/cache/media/secret/cookie resources
  while retaining the real C3 guard/finalizer order, Session/Auth/CSRF middleware
  and schema configuration. Default cache is isolated LocMem, never inherited
  Redis. The fixture adds no biometric enrollment or production stream endpoint.
- The conventional `config.asgi` may use normal `config.settings` like Django's
  WSGI entry. **The fixture launcher does not**: it requires its freshly created
  private configuration before importing ASGI. Do not use the normal ASGI entry
  directly as an isolated fixture launcher.

## Cookie isolation is filtering, not a claim that the native jar is empty

The original code/config uses host-only session/CSRF/language cookie scopes and
the hardcoded `theme` preference cookie. Ports do not isolate them. Every fixture
has a fresh random `hvt-<run>.local` host and unique session/CSRF/language names,
domains `None`, paths `/`,600s session/CSRF/language lifetime and SameSite/session
HttpOnly semantics retained. HTTP non-Secure settings are test-only for fictional
credentials; this is not a TLS deployment recommendation.

Before **any Django handling**, the ASGI boundary retains only those three
generated cookie names; it does not decode, interpret or log unknown cookie
values. Thus even a parent-scope `theme`, `sessionid` or other unrelated cookie
cannot become application input. Duplicate owned names are rejected. Outgoing
Set-Cookie is likewise limited to the generated names: logout cannot clear the
original theme cookie. No shared-jar reads/clear operations or theme monkeypatch
are used. Theme-cookie retention and cookie-backed Admin flash messages are
outside this fixture's acceptance; authentication and Task persistence are not.

Wrong Host and off-origin redirects are rejected. Relative same-origin redirects
continue unchanged. Later phone work still needs real fresh-host resolution and
a separate fresh Metro alias; neither a new port nor this loopback test proves
native resolution. No global DNS/hosts changes are supplied by this unit.

## Bounds, failure and cleanup

Ordinary HTTP requests have a64KiB total body limit (including chunked input),
10s body deadline,15s response deadline and exact Content-Length consistency.
The boundary forwards actual subsequent disconnect events; it does not invent
abort or ACK. Errors before headers produce bounded empty400/408/413/502/504;
errors after headers propagate rather than falsely returning completed success.
Uvicorn uses asyncio/h11/no WebSocket,16 concurrent connections/backlog,300 requests,
3s keepalive and5s graceful shutdown. The listener window is at most600s, plus
initialization and bounded shutdown; this is not an SSE lifetime policy.

Django's source static handler serves Admin assets without build/collectstatic.
Access logs are disabled; reports contain stages/counts/provenance, never raw
Cookie/Set-Cookie, secret/password, session binding or auth XML. Setup failure and
normal/expired server completion close DB connections and remove only the owned
private tree. No original services, native jar or Redis keys are cleared.

## Evidence and next boundary

Permanent tests cover private paths/settings, setup failure, request/redirect/
cookie bounds, actual Django auth/CSRF/foreign-owner denial, real loopback ASGI
and finite listener/database cleanup. TDD logs, runtime origins and exact frozen
hashes live under `evidence/environment/native-app-fixture-*` in the isolated run.
An existing anyio Python3.14 SyntaxWarning remains visible, not suppressed.

Next: independent review, then coordinated hostname/standalone auth-layout native
acceptance. Production SSE and the Admin-rename owner-notification demo remain
separate later work. The earlier physical iOS synthetic-I/O PASS is preserved;
Android AVD presence still does not prove an installed compatible client.


## Prepare the real-App campaign without enabling a transport

The following flags are test-only launcher inputs, not Django/package settings:

- `--bind IPV4 --port PORT`: exact `127.0.0.1` or canonical RFC1918 IPv4;
  ports1024–65535, with0 allowed only for default loopback. The OS must accept that
  local interface. Failure releases the socket and never retries on wildcard,
  another interface or a public address. No DNS/Bonjour registration is performed.
- `--paginated`:22 fictional A tasks plus2 B tasks. Filters/ownership and actual
 20+2 page contents are checked before listener handoff.
- `--events-report /absolute/isolated/evidence/events.jsonl`: opt in to the bounded
  report sink. Both JSONL and `.status.json` sidecar must be new paths under this
  isolated run's evidence directory; existing files/symlinks are rejected. Files
  are0600. Default mode keeps the report route inactive404.

Use a verified private address and a fresh `hvt-<run>.local` Host for any future
LAN run, plus a separate fresh Metro alias. A configured option or loopback pass
is not evidence that those names resolve on the phone. Do not start the600s window
before App/manifest/development-payload preparation is complete. No build,
collectstatic, install or production SSE endpoint is involved.

### Sanitized evidence contract

Only `POST /__native__/report/`, without query and exact `Content-Type:
application/json`, accepts one UTF-8 JSON record after the existing Host/cookie/
body/deadline envelope. It never reaches Django or invokes a business control.
Inactive mode404, wrong method405, invalid shape/scope400, oversized413 and body
timeout408 are bounded empty responses. Valid upload204 is not an XML ACK.

Wire version1 has exactly these10 keys, including explicit nulls:

```json
{"v":1,"run":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","sequence":1,"platform":"ios","case":"startup","kind":"ready","operation":null,"route":1,"outcome":null,"reason":null}
```

`run` must match this fixture's32 lowercase hex ID; sequence is consecutive1–500;
platform is ios/android; operation is null or the real bounded `gate-N-N-N` ID;
route is null or a local ordinal1–256, never a URL/owner key. Closed case/kind/
outcome/terminal/diagnostic enums are declared in `native_app_evidence.py`.
Python literals are independent; permanent tests compare shared test vectors,
not a runtime mobile import. Only the four actual layout reasons can pair with
ack; fetch/parse/ready/complete cannot manufacture one. Unknown fields, free text,
booleans in integer fields, invalid IDs, duplicate/reused/out-of-order sequences,
records above2KiB and records above500 are rejected, not truncated.

Status is `recording`, `recorded` (upload completed), or sticky `inconclusive`.
Schema/upload/overflow and known cleanup failures cannot become recorded by a
later complete. Missing complete at shutdown is inconclusive. Disk/status write
failures do not leave a successful status or leaked owned file handles. A record
is an observation, not proof that its asserted event occurred on a real device;
server records, screenshots and real observer evidence must be reviewed together.
No cookie/header/binding/XML/body/credential/user ID/raw URL enters JSONL.

Default launcher `passed` retains its historical fixture-check meaning. New
`--events-report` mode omits that field, separates `fixture_checks_passed` from
`events.state`, and **never derives native PASS**. It finalizes sanitized evidence
before ending, while keeping report artifacts outside the deleted private DB tree.

### Host-only synthetic controls

`apply_control(fixture, "rename-task")` changes exactly one fictional owner-A
Task through the existing service to a fixed fictional title. `revoke-session`
deletes only that fixture owner's Django Session records; B's tasks/sessions stay
untouched. The caller must load its existing private fixture and initialize Django
with `test_support.native_app_settings`/the explicit fixture root. The function
checks the exact configured private database before ORM work. It returns only a
closed control code and affected count; it reads no native cookie jar, exposes no
LAN mutator endpoint, and never changes auth/views/models/schema or real data.
The coordinator invokes these methods from the host, not from the report sink.

New campaign tests and RED/GREEN logs are under
`evidence/gate0-mobile/native-app-campaign-*`; the earlier fixture/I/O proofs remain
historical. The separate `native-app-format-*` patch only formats the two already
reported baseline files with Python AST/Markdown-content equivalence.
