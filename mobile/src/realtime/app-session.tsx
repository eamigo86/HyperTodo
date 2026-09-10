import React, { useEffect, useMemo, useSyncExternalStore } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import type Hyperview from "hyperview";
import { createRealtimeGate } from "./gate";
import { createSessionSupervisor, type RecoveryHandle } from "./session";
import type { AuthDelivery, GateObservation } from "./auth";
import { createHyperviewHttpPort, type FetchImplementation } from "../network";
import { snapshotFormRequest } from "./modern-form-body";
import { createOwnedBehaviors, type OwnedNativePorts, type ResourceName } from "../behaviors/owned";
import type { StorageQueue } from "./session-effects";
import { THEME_TOKENS, useThemeName } from "../theme";
import { sessionLabels } from "./app-session-labels";
import type { SnackbarNotice } from "../feedback/snackbar";
import { createEventStream, type StreamClock, type StreamOwner } from "./event-stream";
type PublicPresentation = {
  handle: RecoveryHandle;
  gate: ReturnType<typeof createRealtimeGate>;
  epoch: number;
  fetch: ReturnType<ReturnType<typeof createRealtimeGate>["wrapFetch"]>;
  behaviors: ReturnType<typeof createOwnedBehaviors>;
  entrypointUrl: string;
};
export type CapturedResourceReceiver = (resources: readonly ResourceName[], cause?: "invalidate" | "resync") => boolean;

export type AppSessionOptions = {
  entrypointUrl: string;
  http: FetchImplementation;
  credentials: {
    read(): Promise<string | null>;
    storage: StorageQueue;
  };
  native: OwnedNativePorts;
  onTheme(theme: string | null): void;
  onNotice(notice: SnackbarNotice): void;
  stopStream(): void;
  /** Internal transport DI; normal App supplies the explicit expo/fetch export. */
  stream?: { fetch(url: string, init: RequestInit): Promise<Response>; clock?: StreamClock };
  onGateObservation?: (event: Readonly<GateObservation>) => void;
  onResourceReceiver?: (receive: CapturedResourceReceiver | null) => void;
};

/** Internal composition for normal App and the isolated native fixture. */
export function createAppSession(options: AppSessionOptions) {
  const listeners = new Set<() => void>();
  let disposed = false;
  let labels = sessionLabels(null);
  let recovery: PublicPresentation | null = null;
  let resources: CapturedResourceReceiver | null = null;
  let publishedReceiver: CapturedResourceReceiver | null | undefined;
  const stream = options.stream ? createEventStream({origin:new URL(options.entrypointUrl).origin,...options.stream}) : null;
  let streamOwner: StreamOwner | null = null;
  const observe = options.onGateObservation;
  const receiveResources = options.onResourceReceiver;
  const forwardObservation = (event: Readonly<GateObservation>): void => {
    try {
      observe?.(Object.freeze({ ...event }));
    } catch {
      // Passive diagnostics cannot change a result.
    }
  };
  let generation = -1,
    rootEpoch = 0;
  let behaviors: ReturnType<typeof createOwnedBehaviors> = [];
  let held: {
    generation: number;
    resume: AuthDelivery;
    returnedHeld: boolean;
  } | null = null;
  let started: Promise<unknown> | undefined;
  let supervisor!: ReturnType<typeof createSessionSupervisor>;
  const gate = createRealtimeGate({
    onObservation: forwardObservation,
    noticeLabels: () => labels,
    onReady: ready => {
      if (ready.epoch === rootEpoch && supervisor.snapshot().generation === generation) supervisor.markRootReady(generation);
    },
    authenticate: async (url, init, resume) => {
      if (held) return {
        kind: "busy"
      };
      const owner = {
        generation: supervisor.snapshot().generation,
        resume,
        returnedHeld: false
      };
      held = owner;
      try {
        const result = await supervisor.authenticate(url, snapshotFormRequest(init));
        if (result.kind === "held") owner.returnedHeld = true;
        else if (held === owner) held = null;
        return result;
      } catch (error) {
        // Rejection is not a held transition and cannot block a later action.
        if (held === owner) held = null;
        throw error;
      }
    }
  });
  rootEpoch = gate.resetEpoch();
  const onIdentity = (identity: ReturnType<typeof supervisor.snapshot>["identity"]) => {
    recovery?.gate.resetEpoch();
    recovery = null;
    resources = null;
    streamOwner = null;
    rootEpoch = gate.resetEpoch();
    generation = supervisor.snapshot().generation;
    behaviors = [];
    if (!identity) return;
    const capturedEpoch = rootEpoch,
      capturedGeneration = generation,
      capturedIdentity = identity;
    const receiver: CapturedResourceReceiver = (names, cause = "invalidate") => {
      const state = supervisor.snapshot();
      return !disposed && state.identity === capturedIdentity && state.generation === capturedGeneration
        && state.rootReady && state.availability === "foreground"
        && gate.invalidateResources(capturedEpoch, names, cause);
    };
    resources = receiver;
    if (identity.authenticated) {
      const isCurrent = () => {
        const state = supervisor.snapshot();
        return !disposed && state.identity === capturedIdentity && state.generation === capturedGeneration
          && state.identity.authenticated && state.rootReady && state.availability === "foreground";
      };
      streamOwner = Object.freeze({
        generation: capturedGeneration, binding: capturedIdentity.binding, isCurrent, receive: receiver,
        onAuthRequired: () => { if (isCurrent()) supervisor.invalidate(); },
      });
    }
    behaviors = createOwnedBehaviors({
      supervisor,
      native: {
        ...options.native,
        readToken: options.credentials.read
      },
      bindSource: gate.bindSource,
      isSettingsClear: gate.isSettingsClear,
      notice: options.onNotice,
      notifyResources: (_source, names) => {
        receiver(names);
      }
    });
    gate.resumeEpoch(rootEpoch);
  };
  supervisor = createSessionSupervisor({
    origin: new URL(options.entrypointUrl).origin,
    transport: createHyperviewHttpPort(options.entrypointUrl, options.http),
    storage: options.credentials.storage,
    onIdentity,
    onTheme: options.onTheme,
    onLanguage: language => {
      const next = sessionLabels(language);
      if (next !== labels) {
        labels = next;
        notify();
      }
    },
    stopStream: () => {
      stream?.setOwner(null);
      options.stopStream();
    }
  });
  const readValue = () => Object.freeze({
    session: supervisor.snapshot(),
    resources: "connected" as const,
    behaviors,
    labels,
    recovery
  });
  let value = readValue();
  function captureResources(): CapturedResourceReceiver | null {
    const state = supervisor.snapshot();
    return !disposed && state.identity && state.rootReady && state.availability === "foreground" ? resources : null;
  }
  function publishReceiver(): void {
    const receiver = captureResources();
    if (receiver === publishedReceiver) return;
    publishedReceiver = receiver;
    try {
      receiveResources?.(receiver);
    } catch {
      // Observing availability grants no extra authority.
    }
  }
  function notify() {
    value = readValue();
    // rootReady belongs to the confirmed identity, not individual reloads.
    // Reusing this owner prevents resync -> HTTP -> layout reconnect loops.
    stream?.setOwner(streamOwner?.isCurrent() ? streamOwner : null);
    publishReceiver();
    for (const listener of listeners) listener();
  }
  const unsubscribe = supervisor.subscribe(() => {
    const state = supervisor.snapshot();
    if (recovery) recovery.gate.setRetainedPaused(recovery.epoch, state.availability !== "foreground");
    if (state.identity) gate.setRetainedPaused(rootEpoch, state.availability !== "foreground");
    notify();
  });
  const fetch = gate.wrapFetch((input, init) => supervisor.request(typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url, snapshotFormRequest(init)));
  async function foreground() {
    const owner = held,
      result = await supervisor.foreground();
    if (owner && held === owner && owner.returnedHeld && result.kind !== "held" && result.kind !== "busy") {
      held = null;
      owner.resume(result);
    }
    return result;
  }
  async function beginRecovery() {
    const result = await supervisor.beginRecovery();
    if (result.kind !== "recovery" || disposed) return result;
    const handle = result.handle;
    labels = sessionLabels(null);
    const publicGate = createRealtimeGate({
      onObservation: forwardObservation,
      noticeLabels: () => labels,
      authenticate: async (url, init, resume) => {
        if (held) return {
          kind: "busy"
        };
        const owner = {
          generation: supervisor.snapshot().generation,
          resume,
          returnedHeld: false
        };
        held = owner;
        try {
          const result = await handle.authenticate(url, snapshotFormRequest(init));
          if (result.kind === "held") owner.returnedHeld = true;
          else if (held === owner) held = null;
          return result;
        } catch (error) {
          // Rejection is not a held transition and cannot block a later action.
          if (held === owner) held = null;
          throw error;
        }
      }
    });
    const epoch = publicGate.resetEpoch();
    publicGate.resumeEpoch(epoch);
    const fetch = publicGate.wrapFetch((input, init) => handle.fetch(typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url, snapshotFormRequest(init)));
    const behaviors = createOwnedBehaviors({
      supervisor,
      recovery: handle,
      native: {
        ...options.native,
        readToken: options.credentials.read
      },
      bindSource: publicGate.bindSource,
      isSettingsClear: () => false,
      notice: options.onNotice,
      notifyResources: () => {}
    });
    recovery = {
      handle,
      gate: publicGate,
      epoch,
      fetch,
      behaviors,
      entrypointUrl: new URL("/hv/recovery/", options.entrypointUrl).toString()
    };
    notify();
    return result;
  }
  publishReceiver();
  return {
    captureResources,
    beginRecovery,
    gate,
    supervisor,
    fetch,
    entrypointUrl: options.entrypointUrl,
    snapshot: () => value,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    start: () => started ?? (started = supervisor.bootstrap()),
    pause: () => supervisor.pause(),
    foreground,
    retry: foreground,
    dispose: () => {
      if (disposed) return;
      disposed = true;
      held = null;
      supervisor.invalidate();
      stream?.dispose();
      unsubscribe();
      listeners.clear();
    }
  };
}

/** The exact retained root surface used by App, not a separate native probe UI. */
export function AppSessionSurface({
  session,
  hyperviewProps
}: {
  session: ReturnType<typeof createAppSession>;
  hyperviewProps: Partial<React.ComponentProps<typeof Hyperview>>;
}) {
  useEffect(() => {
    void session.start();
  }, [session]);
  const state = useSyncExternalStore(session.subscribe, session.snapshot, session.snapshot);
  const blocked = state.session.availability !== "foreground";
  const tokens = THEME_TOKENS[useThemeName()];
  const presentation = state.recovery ?? session;
  const Root = presentation.gate.Root;
  const components = useMemo(
    () => [...presentation.gate.components, ...(hyperviewProps.components ?? [])],
    [presentation.gate, hyperviewProps.components],
  );
  return (
    <View style={styles.container}>
      <View
        style={styles.container}
        pointerEvents={blocked ? "none" : "auto"}
        accessibilityElementsHidden={blocked}
        importantForAccessibility={blocked ? "no-hide-descendants" : "auto"}
      >
        {state.session.identity || state.recovery ? (
          <Root
            {...hyperviewProps}
            entrypointUrl={presentation.entrypointUrl}
            fetch={presentation.fetch}
            formatDate={hyperviewProps.formatDate ?? (() => undefined)}
            components={components}
            behaviors={state.recovery?.behaviors ?? state.behaviors}
          />
        ) : null}
      </View>
      {blocked ? (
        <View
          style={[styles.shield, { backgroundColor: tokens.canvas }]}
          accessibilityViewIsModal
          accessibilityLabel={state.labels.shield}
        >
          <Text style={{ color: tokens.ink }} accessibilityRole="alert">
            {state.session.availability === "paused"
              ? state.labels.paused
              : state.session.availability === "uncertain" && state.session.reason !== "bootstrap-required"
                ? state.labels.unconfirmed
                : state.labels.confirming}
          </Text>
          {state.session.availability === "uncertain" ? (
            <>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={state.labels.retry}
                onPress={() => { void session.retry(); }}
              >
                <Text style={{ color: tokens.ink }}>{state.labels.retry}</Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={state.labels.signIn}
                onPress={() => { void session.beginRecovery(); }}
              >
                <Text style={{ color: tokens.ink }}>{state.labels.signIn}</Text>
              </Pressable>
            </>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1
  },
  shield: {
    ...StyleSheet.absoluteFill,
    backgroundColor: "#FFFFFF",
    alignItems: "center",
    justifyContent: "center",
    padding: 24
  }
});
