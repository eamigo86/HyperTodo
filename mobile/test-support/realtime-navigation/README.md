# Owned screen reload and navigation proof

**Historical C3c checkpoint.** The temporary evidence path below identifies that
past run; it is not a launcher default or proof for a later published package.
For current behavior, see [the App integration documentation](../../docs/realtime-app.md).

This unregistered C3c unit uses Hyperview 0.110.0's public APIs. It is implemented
and covered by JavaScript tests; independent review and native integration remain
pending. It does not activate SSE or modify the production app registration.

## Contract

- A screen reload reserves its route, epoch and operation before HTTP. A private
  instance-bound object attributes the request and is removed before transport.
  The canonical URL, including filters, contains no correlation query parameter.
- Public `Parser` and `createStylesheets` prepare one `doc/screen` containing one
  owned boundary and its matching request marker. The actual supplied screen
  `onUpdateCallbacks.setState` replaces the doc, styles and local URL. It does not
  call `updateUrl`, initiate another fetch or remount the root navigator.
- Only layout of that actual replacement document acknowledges the reload. Old
  layouts, parsing, response completion and `onEnd` cannot release its barrier.
  An admitted append waits until that commit. Once, public indicators, no-document,
  errors, cancellation and identity-reset rejection retain explicit outcomes.
- `navigate` and `back` are delegated to the real SDK. Public navigator state
  observes a known destination or a no-op; the result is `no-document`, **not** an
  XML ACK. Canonical navigation URLs, form handling and the SDK back stack remain
  SDK-owned. Missing destinations return an explicit non-document result.

The public reload callback clears screen errors and carries the Parser's stale
header metadata, as the normal SDK load does. This is not a recreation of the
SDK's private element-error overlay. Errors also keep the boundary's app-owned
uncertainty notice; the final translated notice UI belongs to app integration.

## Reproduce

Use the recorded no-install commands in
`/private/tmp/djhv-sse-20260908/evidence/gate0-mobile/c3-navigation-commands.sh`.
The dedicated test is `mobile/__tests__/realtime-navigation.test.tsx`. Its twelve
cases use the real pinned Hyperview renderer, public Parser, actual supplied
screen callbacks and real React Navigation stack. Native primitives and WebView
use the declared Jest/native shims; HTTP responses are controlled test fixtures.

The evidence report distinguishes initial permanent REDs, later regression
controls, the unchanged C1/C2 suites, and concurrent session-core tests. No native
layout, auth integration, full Gate 0 or production SSE result follows from Jest.

## Remaining integration boundary

This unit does not implement session/auth delivery, background suspension, SSE,
resource-event wiring or production registration. Root startup's navigator
scaffold has no ready-page marker: its existing unowned pending record is not a
screen ACK and is not a serialization barrier. Epoch reset clears it. The later
initial-load integration must account for scaffold lifetime without inventing a
fetch/parse ACK. Native route focus, layout, draft retention and device transport
remain separate required proofs.
