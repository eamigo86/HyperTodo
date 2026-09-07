export type FailureKind = "offline" | "server";

export type FailureCopy = {
  title: string;
  body: string;
  action: string;
};

// whatwg-fetch (React Native's built-in fetch, and the one still installed under jest)
// rejects with these exact messages when the host is unreachable or the request times out.
const WHATWG_OFFLINE_MESSAGES = new Set([
  "Network request failed",
  "Network request timed out",
]);

// Expo SDK 57 replaces the global fetch (expo/src/winter/runtime.native.ts:52), so on a
// device every reachability failure arrives as expo's FetchError, which prefixes the
// message with "fetch failed: " and never sets `name` (so `error.name` is just "Error").
// Treating the whole prefix as offline is deliberate: expo only builds a FetchError when
// the native transport itself fails, never for a response that arrived with a bad status.
// A misclassification would only downgrade "Something went wrong" to "No connection", and
// neither string exposes anything technical, so the blast radius is a wording nuance.
const EXPO_OFFLINE_PREFIX = "fetch failed:";

export function classifyFailure(error: Error | null | undefined): FailureKind {
  if (!error) {
    return "server";
  }
  const message = error.message ?? "";
  if (message.startsWith(EXPO_OFFLINE_PREFIX) || WHATWG_OFFLINE_MESSAGES.has(message)) {
    return "offline";
  }
  return "server";
}

export const FAILURE_COPY: Record<FailureKind, FailureCopy> = {
  offline: {
    title: "No connection",
    body: "We can't reach HyperTodo right now. Check your connection and try again.",
    action: "Try again",
  },
  server: {
    title: "Something went wrong",
    body: "HyperTodo is having trouble right now. Please try again in a moment.",
    action: "Try again",
  },
};

type FailureListener = () => void;

const listeners = new Set<FailureListener>();

export function publishNetworkFailure(): void {
  listeners.forEach((listener) => listener());
}

export function subscribeToNetworkFailures(listener: FailureListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
