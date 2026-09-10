# Disposable Android origin routing

Use this **test-only closed proxy** when the disposable guest cannot resolve the
run's fresh `.local` origins. App URLs, Host, cookies and backend guards stay unchanged.
It is not production transport, DNS, TLS interception or a general Internet proxy.

`startAndroidSystemProxy({port, lifetimeMs, api, metro})` binds only `127.0.0.1`.
Both routes contain `{authority, upstreamPort}`: same fresh run nonce, distinct
`hvt-…local:port` and `hvtm-…local:port`; upstream addresses are fixed loopback.
Point Metro at the existing strict `startMetroProxy` listener, not raw Metro.
Use an owned ADB reverse for the System Proxy port. Configure only the disposable
guest's ordinary Android System Proxy; restore its previous setting and remove
the exact reverse before teardown. Never use Emulator `-http-proxy`, global host
configuration, original guest settings, auth keys, certificates or CONNECT.

The proxy accepts matching absolute HTTP (and origin-form for Metro websocket
clients), preserving encoded path/query, body, method and response headers.
Credentials in URLs, foreign/conflicting authorities, proxy credentials, CONNECT,
oversized bodies and non-Metro upgrades are rejected. Metro `/hot`, `/message`
and `/events` upgrades delegate real handshake semantics to the existing proxy.
Hard bounds: 600s lifetime, 120s requests/idle, 16KiB headers, 1MiB request body,
32 in-flight operations, 64 total incoming/upstream sockets; close is idempotent.

Tests establish host-side routing only. Android System Proxy is advisory to apps:
real Expo manifest/bundle and actual App HTTP must be observed before claiming
native routing works. A failed `.local` ping and GREEN Node tests are not that proof.
