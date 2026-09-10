# Native Gate 0 HTTP fixture

**Test-only synthetic I/O probe; not a production SSE endpoint or a completed
native acceptance result.** It does not use Django, Redis, a database, app login,
real user credentials, or application routing.

The fixture lets an existing Expo Go client prove three narrow prerequisites:

1. Ordinary global `fetch` bootstraps a cookie that explicit `expo/fetch` then sends.
2. The client reads the first complete SSE frame before the second can be emitted.
3. `AbortController.abort()` causes a close observed by the server, not just a
   client-side exception.

Passing these checks does **not** prove Hyperview layout correlation, request races,
Android behavior from an iOS run, or full Gate 0. Server observations and client
self-report remain separate for review.

## Run locally

Use an existing Node 24 interpreter; no dependencies, installs or builds:

```sh
cd "$REPO_ROOT" # absolute HyperTodo checkout
NODE=${NODE:-node} # existing Node 24 interpreter
"$NODE" --test mobile/test-support/realtime-native-server.test.cjs
"$NODE" mobile/test-support/realtime-native-server.cjs --help
"$NODE" mobile/test-support/realtime-native-server.cjs
```

The CLI binds `127.0.0.1` on an ephemeral port by default. Its first JSON line is:

```json
{"kind":"ready","baseUrl":"http://127.0.0.1:PORT/probe-RANDOM","runPath":"/probe-RANDOM"}
```

Use the exact fresh `baseUrl` for this run. Treat it as a local test capability;
do not publish it outside the authorized test. Each run is single-use: restart
for another client or attempt. SIGINT/SIGTERM clean up only this fixture.

A physical device cannot reach the host's loopback address. **Do not expose LAN
until the coordinator authorizes the host, unused port and test target.** The
prepared command, only after that authorization, is:

```sh
"$NODE" mobile/test-support/realtime-native-server.cjs --host 192.168.4.43 --port 8787
```

Do not reuse the user's Metro server, inspect session cookies, or launch a client
from this server script. Native client launch is coordinated separately.

## Protocol

All routes are beneath the fresh `baseUrl`; unmatched paths return 404. Use
`credentials: 'include'` for the ordinary and explicit Expo fetch calls.

| Method/path | Contract |
|---|---|
| `GET /bootstrap` | Ordinary global fetch; 200 `{"ok":true}` and a unique synthetic HttpOnly cookie. |
| `GET /stream` | Explicit `expo/fetch`; own cookie required. 200 `text/event-stream`, no compression. |
| `POST /ack` | JSON `{"token":"..."}`, at most 256 bytes. First token unlocks frame 2; second token records that frame 2 was read. Each valid token returns 204 once. |
| `GET /report` | Own cookie required. Returns `{"server":{...},"client":null}` or the accepted client self-report. |
| `POST /client-report` | Allowlisted JSON, at most 2 KiB; 204 on acceptance. Does not alter server observations. |
| `POST /reset` | Expires only this run's cookie and path; 204. No shared cookie clearing. |

Each frame uses `event: probe` and JSON data `{"stage":1,"token":"..."}` or stage 2.
The server splits a frame into separate writes. TCP may coalesce writes; do not
require a specific network chunk count. The decisive streaming proof is the
handshake: frame 2 is not sent until the client returns frame 1's unpredictable
token. The stream never ends normally before that handshake, so a client that
buffers the whole body cannot pass by relying on a timer.

After receiving and acknowledging frame 2:

1. Call `AbortController.abort()` only.
2. Observe the pending reader settle and poll the ordinary-fetch `/report` within
   the client's diagnostic deadline.
3. Require `server.streamClosed`, `server.closeReason === 'client'`,
   `server.activeStreams === 0` and `server.passed`.
4. If abort fails, first record failure/inconclusive evidence. `reader.cancel()`
   may then clean up; it must never receive credit for AbortController behavior.
5. Upload the sanitized client report, capture the server report, and reset the
   run cookie after evidence collection where cleanup is possible.

`closeReason` is `null`, `client`, `deadline` or `shutdown`. `client` means the
server observed remote connection closure, not independent proof of its cause;
review it together with the client's controlled abort sequence.

Server report fields are `bootstrapCount`, `streamAuthorized`, `firstFrameSent`,
`firstAckReceived`, `secondFrameSent`, `secondAckReceived`, `streamClosed`,
`closeReason`, `activeStreams`, and `passed`. `passed` is only the server-side I/O
condition, never an overall native or Gate 0 verdict.

## Sanitized client report

Required fields:

- `platform`: `ios` or `android`.
- `clientVersion`, `expoVersion`, `reactNativeVersion`: bounded version strings.
  Record the actual Expo Go version separately from the JavaScript package version.
- `executionEnvironment`: `storeClient`, `bare`, `standalone`, or `unknown`.
- `checks`: exactly the boolean fields `bootstrapOk`, `firstFrameRead`,
  `secondFrameRead`, `abortRequested`, and `serverCloseObserved`.
- `failedStage`: null or `metadata`, `bootstrap`, `stream`, `first-frame`,
  `first-ack`, `second-frame`, `second-ack`, `abort`, `report`.
- `errorCode`: null or `unsupported-runtime`, `request-failed`, `timeout`,
  `unexpected-status`, `invalid-stream`, `invalid-frame`, `server-not-closed`,
  `cancelled`, `report-upload-failed`.

No exception strings, stack traces, headers, cookies, ACK tokens, URLs, biometric
values or user data are accepted in the report. Errors are generic and malformed
input is not echoed. CLI observation logs use only constructed allowlisted fields;
only its ready line includes the run URL/path. Keep evidence under a separately
allocated `$EVIDENCE_ROOT/native-io/`, outside private credentials/runtime homes.

## Isolation and bounds

Ports do **not** isolate cookies. Every run creates a random cookie **name and
path**. The fixture examines only that cookie; unrelated cookies are ignored and
never logged or cleared. `HttpOnly` prevents client JavaScript from extracting the
fixture value. Bootstrap sets `Max-Age=120`: the cookie expires independently of
server lifetime if explicit cleanup cannot run. Reset retains exactly one
`Max-Age=0` on that same unique path. Plain HTTP is deliberate for synthetic local
test data only.

Defaults: one admitted stream per run, 30-second stream deadline, five-minute
server lifetime, eight connections, 128 requests total, 8-KiB request headers,
5-second configured header/request timeouts, 2-second JSON-read deadline and
1-second idle keep-alive. The constructor bounds deadline/lifetime options; the
CLI exposes only host/port. All bodies are counted while reading, including
chunked requests. Foreign `Origin` is rejected, absent native Origin is allowed,
and no CORS permission is added.

Node tests use explicit synthetic Cookie headers to verify **server behavior**.
They cannot prove native cookie-jar sharing. Deadline tests assert the observed
terminal state, not a fragile performance threshold. No native probe is launched
by the test suite.
