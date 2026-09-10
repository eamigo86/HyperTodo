# Session-owned App composition

The candidate App uses one session supervisor and a generation-bound public
Hyperview Root. **Normal App now connects the generation-owned SSE transport**
through explicit `expo/fetch`; see the current
[event-stream contract](realtime-event-stream.md). This reference began with the
earlier HTTP-only composition unit. Its real Hyperview renderer, navigator and
Parser tests use controlled HTTP and native ports, not native network proof.

## Ownership and foreground safety

- Confirm session state before loading ordinary HXML. Only the matching focused
  boundary's actual layout marks the Root ready.
- Login/logout await their genuine accepted effects and confirmation before
  replacing the entire Root. No transition body is returned as a synthetic
  Response or replayed as SDK store/reload events.
- Inactive, background and unknown initial AppState retain an opaque accessible
  shield. Pausing preserves the Root, navigation stack and drafts; foreground
  confirms the same owner. Revocation cannot restart ordinary bootstrap.
- Matching422/401/429 panels use the captured operation and real layout.401 clears
  credentials once;429 does not.403 keeps the form and displays one safe notice.
  A canceled/timed-out POST is not proof of server rollback; there is no automatic
  POST replay.
- Native probes, unlock and picker continuations use captured source authority.
  A removed source or old generation cannot read credentials, update XML, submit
  into another account or display a late snackbar. Settings clears require the
  gate's private successful-response provenance, not an arbitrary empty token.

## Explicit neutral Sign in

After an identity mismatch, Retry cannot adopt the unexpected cookie. The shield's
explicit **Sign in** action requests a revocable recovery capability from the same
supervisor; it never invents an anonymous Identity or recreates the supervisor.

The capability permits only the negotiated neutral navigator/login GETs and exact
password/biometric POSTs. The backend projects public context and real masked CSRF;
profile data, private routes, theme publication and resource dispatch are not
available to this Root. Native recovery behaviors are limited to probe, unlock and
consuming genuine auth receipts. Successful authentication still needs its own
returned binding, effect settlement and final confirmation before normal App work.

Recovery returns a finite `busy` while an actual submitted HTTP/auth/native write
is unsettled. The shield remains usable for another explicit attempt after
settlement. Revoked read-only prompts do not create a new global barrier. A
binding-less auth500 is uncertain, not evidence of rollback or successful login;
confirmation never repeats that POST. Neutral HXML is bounded to262144 UTF-8 bytes
without truncation; this does not claim a peak native-fetch memory bound.

## Resource and language ports

`createAppSession().captureResources()` returns a receiver only after confirmed
identity and actual Root readiness. A connection must retain that receiver, not
look up the current one when an old callback arrives. Its Identity/generation/epoch
cannot authorize another account. The same receiver backs owned
`notify-resources` behaviors; dependencies remain explicit HXML metadata.

The gate handles page1 document refresh and form/multipage notices. It keeps
filters and uses ordinary validated HTTP. App notice text follows accepted
`Content-Language` (ES/EN, safe English fallback) through the same ownership checks
as theme; no language metadata is published from bare HTTP, session observations
or unconfirmed auth responses. Changing labels does not remount Root or lose drafts.

## Isolated native fixture

`createSessionApp(options, themeStore)` is an internal composition factory, not a
public configuration toggle. The normal App retains its existing API URL and
credential/theme keys. A fixture supplies its own origin, HTTP implementation,
credential port, native port and theme store to the **same App and SDK**.

- Create the credential port with a unique fixture key and pass its `read` method
  into the native adapter too. Never let probe/unlock fall through to a singleton.
- Theme stores are lazy: importing App/theme does not access SecureStore. The
  injected provider covers existing shell hooks and retains exact palettes.
- Historical HTTP-only fixtures provide a stream-stop port but no transport.
  An SSE fixture must explicitly supply the same `expo/fetch` stream port used
  by normal App; the stop port alone does not open a connection.
- Use synthetic accounts/DB, cookies and storage namespaces. Do not run the fixture
  against existing development data or the original Expo Go credential keys.

## Verification and remaining work

Permanent suites cover actual App navigator/login, form serialization,422 retry,
401/429,403, Settings clear, logout retention, held background response, late native
completion, lifecycle notifications, language and source-owned resource hints.
Separate supervisor tests cover neutral capability bounds, stale body/identity,
settlement barriers and failure outcomes. Legacy shell/biometric behavior contracts
remain tested; no SDK source is patched.

The evidence directory preserves the chronological RED phases, commands and hashes,
including the earlier inconclusive foreground-confirmation trace. Later finite
Gate0 acceptance is recorded separately; it does not establish native production
SSE delivery. The producer, broker, authenticated endpoint and normal App connection
are now implemented and software-tested. **The current end-to-end/native SSE verdict
remains a separate coordinated check**, described in the
[event-stream verification boundary](realtime-event-stream.md#verification-and-remaining-scope).

## Confirmation failure is not a login result

The shield says **We could not confirm your session** / **No pudimos confirmar
tu sesión** after an unsuccessful confirmation. This reports uncertainty, not
logout, expiry or its cause. **Retry session confirmation** retries confirmation;
**Sign in** remains an explicit recovery action, never an automatic redirect.

Paused sessions retain their paused heading. Initial `bootstrap-required` retains
the confirming heading because no failure is known yet. A retry can retain the
last failure message while working; the UI does not infer a new busy state.
Identity, retained Root, drafts, buttons and auth policy are unchanged.

Real-SDK tests cover two lifecycle cycles with a resource notice, a held fragment,
three controlled failed confirmation attempts, and explicit retry preserving the
same Identity/Root/draft. EN/ES failure headings and initial bootstrap are covered.
These controlled HTTP tests do **not** identify or fix why the physical iPhone's
second foreground confirmation failed. That native cause remains unresolved.
