# Run the published package, without source-path shortcuts

**Use the locked `dj-hyperview[editor,realtime]==0.1.0a21` and Uvicorn in the selected environment.**
No local package checkout, source METADATA fixture or appended Python environment is needed for normal HyperTodo.

## Development startup

The README shows the complete HYPERVIEW mapping first. `make backend-run-sse` selects
`config.settings_sse`: filesystem templates, central realtime Redis15/namespace
`hypertodo-development`, normal auth/DB/cache/schema. It never modifies stored
DB-template rows. Plain settings remain DB-first with realtime disabled.
Redis must already be available; the Python extra installs only its client.
Uvicorn serves the actual ASGI app, including stream ownership. DEBUG alone enables
Django's development Admin/static handler. Do not use that handler for production.

For Expo Go, `LAN_IP=<private-IP> make mobile-start-go` explicitly enables local HTTP
and uses `--go`; the app's release HTTPS guard is unchanged. No native build is needed
for this workflow. Migration/fresh setup are separate: never seed an existing database
just to update dependencies or refresh templates.

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
native evidence is not a reproducible installed-package command or a21 native proof.

## Verification

Permanent tests cover installed/source separation, wrong versions, missing RECORD,
shadowed imports, explicit private workspace/unsafe-path rejection, genuine Admin
asset serving only in DEBUG, and authenticated SSE/disconnect through that wrapper.
Run the full backend gates with installed dependencies; opt into the separate scoped
Redis acceptance only against the authorized test service/UUID namespaces.
