import React, { useEffect, useState, useSyncExternalStore } from 'react';
import { AppState, Pressable, StyleSheet, Text, View } from 'react-native';
import * as SecureStore from 'expo-secure-store';
import { SafeAreaProvider, initialWindowMetrics, useSafeAreaInsets } from 'react-native-safe-area-context';
import { HvBaseError, HvParserError } from 'hyperview';
import { createSessionApp } from '../../App';
import { createSessionCredentialPort } from '../../src/biometrics/store';
import { createThemeStore } from '../../src/theme';
import { createOwnedNativePorts } from '../../src/behaviors/owned-native';
import { publishSnackbar } from '../../src/feedback/snackbar';
import type { GateObservation } from '../../src/realtime/auth';
import type { ResourceName } from '../../src/behaviors/owned';
import { validateFixtureConfig } from './preflight.cjs';
import { createReporter, CASES, type CaseName, type ReportPart } from './report.cjs';
import { createResponseHold } from './hold.cjs';
import { createFixtureLifetime } from './lifetime.cjs';

/** Apply native insets only to fixture controls, outside the App's own provider. */
function FixtureControls({ children }: { children: React.ReactNode }) {
  const insets = useSafeAreaInsets();
  return <View style={[styles.controls, {
    paddingTop: insets.top + 8,
    paddingLeft: insets.left + 8,
    paddingRight: insets.right + 8,
  }]}>{children}</View>;
}

/** Render only the reporter's closed diagnostic codes, never exception content. */
function reportDiagnostic(state: { state: string; reason: string | null }): string {
  const status = ['recording', 'complete', 'inconclusive'].includes(state.state) ? state.state : 'unavailable';
  const reason = state.reason === null ? 'none' : [
    'sdk-error', 'request-failed', 'hold-timeout', 'report-failed',
    'overflow', 'invalid-record', 'cleanup-failed',
  ].includes(state.reason) ? state.reason : 'unavailable';
  return `Report: ${status} (${reason})`;
}

const DIAGNOSTIC_SINKS = ['on-error', 'logger-error', 'logger-warn'] as const;
type DiagnosticSink = typeof DIAGNOSTIC_SINKS[number];
type DiagnosticClass = 'http' | 'xml' | 'content-type' | 'document' | 'navigation' | 'unknown';
type SafeDiagnostic = Readonly<{ family: DiagnosticClass; status: number | 'unknown' }>;
const UNKNOWN_DIAGNOSTIC: SafeDiagnostic = Object.freeze({ family: 'unknown', status: 'unknown' });

/** Family/name diagnostics, not constructor identity or authority. Never read payloads. */
function classifySdkDiagnostic(value: unknown): SafeDiagnostic {
  try {
    if (!(value instanceof HvBaseError)) return UNKNOWN_DIAGNOSTIC;
    const name = Object.getOwnPropertyDescriptor(value, 'name');
    if (!name || !('value' in name)) return UNKNOWN_DIAGNOSTIC;
    let family: DiagnosticClass;
    switch (name.value) {
      case 'ServerError': family = 'http'; break;
      case 'ParserError': case 'ParserWarning': case 'ParserFatalError':
      case 'XMLParserError': case 'XMLParserWarning': case 'XMLParserFatalError':
      case 'XMLRequiredElementNotFound': case 'XMLRestrictedElementFound': family = 'xml'; break;
      case 'UnsupportedContentTypeError': family = 'content-type'; break;
      case 'HvDocError': family = 'document'; break;
      case 'HvRouteError': case 'HvNavigatorError': case 'HvRenderError': family = 'navigation'; break;
      default: return UNKNOWN_DIAGNOSTIC;
    }
    let status: SafeDiagnostic['status'] = 'unknown';
    if (family === 'http' || value instanceof HvParserError) {
      const own = Object.getOwnPropertyDescriptor(value, 'status');
      if (own && 'value' in own && typeof own.value === 'number' && Number.isInteger(own.value) && own.value >= 100 && own.value <= 599) status = own.value;
    }
    return Object.freeze({ family, status });
  } catch {
    return UNKNOWN_DIAGNOSTIC;
  }
}

/** Real App composition; this factory creates no request, storage read or native prompt. */
export function createNativeAppRunner(raw: unknown, platform: 'ios' | 'android', http: typeof fetch = globalThis.fetch) {
  const config = validateFixtureConfig(raw);
  const listeners = new Set<() => void>();
  let revision = 0,
    currentCase: CaseName = 'startup';
  let receive: ((resources: readonly ResourceName[]) => boolean) | null = null;
  let completed = false;
  let localCleanup: boolean | undefined;
  const sdkDiagnostics: Partial<Record<DiagnosticSink, SafeDiagnostic>> = {};
  const notify = () => {
    revision++;
    for (const listener of listeners) listener();
  };
  const reporter = createReporter(config.run, platform, async (record, signal) => {
    const result = await http(config.apiOrigin + '/__native__/report/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(record),
      credentials: 'include',
      redirect: 'error',
      signal
    });
    return result.status;
  });
  const emit = (part: Omit<ReportPart, 'case'>) => {
    reporter.send({
      case: currentCase,
      ...part
    });
    notify();
  };
  const hold = createResponseHold(http, emit);
  const life = createFixtureLifetime(createSessionCredentialPort(config.credentialKey), {
    read: () => SecureStore.getItem(config.themeKey),
    write: name => SecureStore.setItemAsync(config.themeKey, name),
    clear: () => SecureStore.deleteItemAsync(config.themeKey)
  });
  const theme = createThemeStore(life.theme),
    routes = new Map<string, number>();
  function observe(event: GateObservation) {
    const key = event.epoch + ':' + event.routeKey;
    if (!routes.has(key)) {
      if (routes.size >= 256) {
        emit({
          kind: 'inconclusive',
          reason: 'overflow'
        });
        return;
      }
      routes.set(key, routes.size + 1);
    }
    emit({
      kind: event.kind,
      route: routes.get(key),
      ...(event.kind === 'terminal' ? {
        operation: event.operation,
        outcome: event.outcome,
        reason: event.reason
      } : {})
    });
  }
  const diagnostic = (sink: DiagnosticSink, value: unknown) => {
    sdkDiagnostics[sink] ??= classifySdkDiagnostic(value);
    emit({
      kind: 'diagnostic',
      reason: 'sdk-error'
    });
  };
  const ActualApp = React.memo(createSessionApp({
    entrypointUrl: config.apiOrigin + '/hv/',
    http: hold.fetch,
    credentials: life.credentials,
    native: createOwnedNativePorts(life.credentials.read, platform),
    onNotice: publishSnackbar,
    stopStream: () => {},
    onGateObservation: observe,
    onResourceReceiver: value => {
      receive = value;
      notify();
    }
  }, theme, {
    logger: {
      error: value => diagnostic('logger-error', value),
      warn: value => diagnostic('logger-warn', value),
      info: () => {},
      log: () => {}
    },
    onError: value => diagnostic('on-error', value)
  }));
  let cleanup: Promise<void> | undefined;
  async function finishAfterUnmount() {
    if (cleanup) return cleanup;
    cleanup = (async () => {
      receive = null;
      hold.dispose();
      const clean = await life.finish();
      localCleanup = clean;
      currentCase = 'cleanup';
      if (clean) emit({
        kind: 'cleanup'
      });else emit({
        kind: 'inconclusive',
        reason: 'cleanup-failed'
      });
      await reporter.complete();
      completed = true;
      notify();
    })();
    return cleanup;
  }
  const subscribe = (listener: () => void) => {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  };
  const snapshot = () => revision;
  /** Controls are outside the actual App; none can set SDK state, auth identity or ACK. */
  return function NativeAppRunner() {
    useSyncExternalStore(subscribe, snapshot, snapshot);
    const [mounted, setMounted] = useState(true);
    // This passive effect runs after the removed App's cleanup effects, not after
    // merely requesting setMounted(false). The original App disposes its authority.
    useEffect(() => {
      if (!mounted) void finishAfterUnmount();
    }, [mounted]);
    useEffect(() => {
      const listener = AppState.addEventListener('change', state => {
        reporter.setActive(state === 'active');
        emit({
          kind: state === 'active' ? 'foreground' : 'paused'
        });
      });
      reporter.setActive(AppState.currentState === 'active');
      return () => {
        listener.remove();
        hold.dispose();
        if (!completed) emit({
          kind: 'inconclusive',
          reason: 'cleanup-failed'
        });
        reporter.dispose();
      };
    }, []);
    const state = reporter.snapshot();
    const action = (label: string, run: () => void, disabled = false) => <Pressable key={label} accessibilityRole="button" accessibilityLabel={label} disabled={disabled} onPress={run} style={[styles.button, disabled && styles.disabled]}><Text>{label}</Text></Pressable>;
    return <View style={styles.root} testID="realtime-native-app-v1">
   <SafeAreaProvider style={styles.controlsProvider} initialMetrics={initialWindowMetrics}>
    <FixtureControls>
    <Text accessibilityRole="header">Native real-App fixture — {currentCase}</Text>
    <Text accessibilityRole="alert">{completed ? state.state === 'complete' ? 'Evidence complete — host review required' : 'INCONCLUSIVE — retain evidence for review' : `${state.records} records; hold ${hold.snapshot()}; no native verdict`}</Text>
    {DIAGNOSTIC_SINKS.map(sink => {
      const code = sdkDiagnostics[sink];
      return code ? <Text key={sink} accessibilityLiveRegion="polite">{`SDK ${sink}: ${code.family}; status ${code.status}`}</Text> : null;
    })}
    {localCleanup !== undefined && <>
     <Text accessibilityLiveRegion="polite">{localCleanup ? 'Local cleanup: confirmed' : 'Local cleanup: not confirmed'}</Text>
     <Text accessibilityLiveRegion="polite">{reportDiagnostic(state)}</Text>
    </>}
    <View style={styles.actions}>
     {action('Next case', () => {
            currentCase = CASES[(CASES.indexOf(currentCase) + 1) % CASES.length];
            notify();
          }, !mounted)}
     {action('Receive tasks hint', () => {
            if (receive?.(['tasks'])) emit({
              kind: 'hint'
            });
          }, !mounted || !receive)}
     {action('Hold next GET', () => {
            hold.arm('get');
            notify();
          }, !mounted)}
     {action('Hold next POST', () => {
            hold.arm('post');
            notify();
          }, !mounted)}
     {action('Release response', () => {
            hold.release();
            notify();
          }, !mounted || hold.snapshot() !== 'held')}
     {action('Finish and clean fixture', () => setMounted(false), !mounted)}
    </View>
    </FixtureControls>
   </SafeAreaProvider>
   <View style={styles.app}>{mounted ? <ActualApp /> : null}</View>
  </View>;
  };
}
const styles = StyleSheet.create({
  root: {
    flex: 1
  },
  controlsProvider: {
    flex: 0
  },
  controls: {
    padding: 8,
    backgroundColor: '#f0f0f0'
  },
  actions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6
  },
  button: {
    padding: 8,
    backgroundColor: '#dce7fa',
    borderRadius: 4
  },
  disabled: {
    opacity: 0.4
  },
  app: {
    flex: 1
  }
});
