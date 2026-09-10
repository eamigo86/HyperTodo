# Exact-interface Metro fixture proxy

**Keep the real authenticated Expo CLI on loopback; expose only the fixture's
chosen private IPv4 through this finite test helper.** This does not replace
Expo's manifest server, modify dependencies, or expose inspector/devtools.
Loopback tests verify HTTP and WebSocket transport, **not native HMR or Gate 0**.

## Future launch, after runtime approval

Do not run this sequence while another owner is preparing or reviewing the
fixture. First allocate unused ports other than the user's 8081, a new fixture
run, and distinct API/Metro hostnames. The API is `hvt-<run>.local`; Metro is
`hvtm-<run>.local`. Resolve each fresh name only through the separately approved
private-network setup. This helper changes neither DNS nor firewall rules.

```sh
# Values come from the reviewed fresh-run configuration, not client input.
# REPO_ROOT is the absolute HyperTodo checkout; MODULES is its readonly modules.
NODE=${NODE:-node}
HELPER="$REPO_ROOT/mobile/test-support/native-app/metro-proxy.cjs"
EXPO_CLI="$MODULES/@expo/cli/build/bin/cli"

# In the fresh generated Expo launcher directory. Set this BEFORE CLI startup.
EXPO_PACKAGER_PROXY_URL="http://${METRO_HOST}:${METRO_EXTERNAL_PORT}" \
  "$NODE" "$EXPO_CLI" start --localhost --port "$METRO_INTERNAL_PORT" --go

# In a separate managed process, after verifying Expo's actual loopback listener.
# UPSTREAM_IP is exactly 127.0.0.1 OR ::1; do not infer the family from localhost.
"$NODE" "$HELPER" "$PRIVATE_IPV4" "$METRO_EXTERNAL_PORT" "$METRO_HOST" \
  "$UPSTREAM_IP" "$METRO_INTERNAL_PORT"
```

`PRIVATE_IPV4` must be one exact RFC1918 IPv4 assigned to the approved interface;
no wildcard, tunnel or public address is accepted. Hostname must match
`hvtm-[0-9a-f]{32}.local`. Both ports are explicit, different and nonzero; 8081 is
rejected. The CLI rejects loopback listen addresses; the exported
`startMetroProxy` permits explicit127.0.0.1/ephemeral port 0 **for finite tests**.
No upstream hostname is resolved: only literal 127.0.0.1 or ::1 is accepted.

Verify the actual authenticated served manifest, development JavaScript and
native HMR path using the existing independent fixture preflight before making
any device-readiness claim. `EXPO_PACKAGER_PROXY_URL` announces a URL; it does
not bind a socket or prove forwarding. All HTTP bodies, authentication headers,
Set-Cookie fields, status codes and approved Upgrade query strings are passed to
and from the **fixed** existing loopback server. The proxy neither consumes an
Expo account nor signs a substitute manifest. The device still needs the
compatible existing Expo client and its own authorized account.

## Closed boundary and limits

- Host must be exactly the configured hostname plus actual external port. Reject
  missing/duplicate/wrong Host, absolute-form URLs, CONNECT and non-origin paths.
- Origin may be absent (native) or exactly the advertised HTTP origin; other
  origins are rejected. This Host/Origin boundary is **not LAN authentication**:
  a LAN peer that knows the hostname can reach the bounded Expo development
  server. Only the approved private interface is exposed, for this finite run.
- Only WebSocket version 13 upgrades for `/hot`, `/message`, `/events` are accepted.
  Query strings and WebSocket head/frame bytes remain unchanged. No inspector,
  arbitrary devtools/plugin upgrades, CONNECT tunneling or general open proxy.
- HTTP still forwards normal origin-form Metro/Expo paths to the fixed server;
  this is not a static-asset sandbox or an authorization replacement. No added
  forwarding headers, cookie rewriting, redirect rewriting or CORS policy.
- 600s hard process lifetime; 120s maximum HTTP request and socket-idle time;
  10s Upgrade handshake deadline; 32 incoming connections and 32 in-flight requests
  (including upgraded connections); 16KiB headers; 8KiB request target; 1MiB request
  body; 500 HTTP requests per connection. Tests lower these bounds only.
- Response bodies are piped with backpressure, not accumulated or transformed.
  Chunked HTTP refusals to Upgrade use Node's HTTP framing rather than raw
  decoded bytes. Slow/stalled transfers terminate at their deadline; an idle
  HMR connection may therefore reconnect during a run. The finite helper does
  not promise production-proxy behavior.
- SIGINT/SIGTERM, deadline or explicit close destroys only sockets owned by this
  proxy. It never stops Expo, another process or the user's original Metro.
  Upstream errors/rejections are bounded; cancellation is transport closure,
  not an application rollback. CLI logs contain only ready/closed, address,
  port and lifetime; no URL, headers, cookies, payloads or private exception.

## Reproduce the permanent tests

```sh
cd "$REPO_ROOT"
"$NODE" \
  --test mobile/test-support/native-app/metro-proxy.test.cjs
```

All listeners in the suite are ephemeral loopback servers, cleaned up in test
hooks. There is no Expo, DNS, LAN, phone or persistent server launch. The initial
RED preceded implementation; a separate chunk-framing RED reproduces the HTTP
parser failure before its fix. Test deadlines bound cleanup, not performance
claims. Fixtures use synthetic header values only.

## Verified installed source

Historical source inspection used the existing readonly module root. Resolve
these package-relative paths under your explicitly selected `MODULES` directory;
the historic line numbers are not a compatibility guarantee for another version.

- `@expo/cli/build/src/start/server/metro/MetroBundlerDevServer.js:913` chooses
  localhost listen host; `runServer-fork.js:140–145` actually binds it.
- `@expo/cli/build/src/start/server/UrlCreator.js:162–200,224–227` uses
  `EXPO_PACKAGER_PROXY_URL` before localhost normalization and reads it before
  dotenv. This installed seam is marked deprecated, so retain served guards.
- `runServer-fork.js:149–159` registers `/hot`;
  `dev-server/createMessageSocket.js:57` and `createEventSocket.js:60` register
  `/message` and `/events`.

The separate evidence report `native-app-metro-bind-review.md` records versions
Expo 57.0.21, CLI 57.0.23 and Metro 0.84.6. No source was patched. The official
[Expo Server URL documentation](https://docs.expo.dev/more/expo-cli/#server-url)
is explanatory evidence only, not a native acceptance result.
