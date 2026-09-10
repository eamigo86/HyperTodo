# Observe the real App in an isolated native fixture

Use the existing `createSessionApp` factory with injected HTTP, credentials and
theme. The optional hooks below observe the same App, supervisor and public
Hyperview renderer; they do not create a second shell or grant ACK authority.
No SSE connection or native proof is supplied by this unit.

## Passive observations

`AppSessionOptions.onGateObservation` receives a frozen, primitive-only
`GateObservation` exported by the gate. Both the normal and public recovery
Root forward the gate's existing `ready` and `terminal` decisions. A fetch or
parsed response does not become a layout acknowledgement. Return values are
ignored, and observer exceptions cannot change operation retirement or UI.

Persist only the bounded, sanitized event schema of the native runner. Map route
keys to run-local ordinals; never add XML, headers, bindings, credentials or raw
errors. A callback is an observer, not an API for reset, acknowledgement or
session changes.

## Captured resource control

`onResourceReceiver(receive)` publishes the existing generation-bound receiver
only after confirmed foreground identity and real focused layout readiness.
It publishes `null` during pause, uncertainty, revocation and disposal. Recovery
never obtains the private resource receiver. A retained function independently
rechecks its exact identity, generation, foreground readiness and disposal before
calling the gate; retaining an old function cannot attach it to a new account.

The receiver accepts only the gate's declared resource names. It does not accept
owners, topics, URLs or new authority. Confirmation can describe an anonymous
session: **a receiver is not proof of login**. The later authenticated SSE owner
must apply its separate connection/authentication contract.

No Root remount is used for observation, notice or availability changes. Pausing
retains the current stack and draft, and a resumed confirmation can republish the
same valid receiver without rebinding it.

## Fixture-only SDK diagnostics

The third factory argument is optional and accepts exactly both diagnostic ports:

```ts
createSessionApp(options, isolatedTheme, {
  logger: {
    error: (..._context) => recordCode("sdk-error"),
    warn: (..._context) => {},
    info: (..._context) => {},
    log: (..._context) => {},
  },
  onError: (_error) => recordCode("sdk-error"),
});
```

The fixture discards arbitrary SDK context rather than serializing it. App keeps
its real `publishNetworkFailure` notification and existing error components,
without additionally calling the default raw logger. Each injected diagnostic
callback is exception-contained. Without this argument the normal logger and
error handler remain unchanged. There are no console monkeypatches, diagnostic
setters, transport overrides in this argument, or public settings.

Tests use the real pinned Hyperview renderer/parser with controlled HTTP/native
ports and injected theme storage. They cover body-pending versus layout,
normal/recovery forwarding, receiver pause/revocation/disposal/account changes,
retained drafts, failing observers, genuine error UI and default diagnostics.
The splash layout trigger is only the existing visual entrance control, never an
XML ACK. These are JS integration tests, not physical-device evidence.
