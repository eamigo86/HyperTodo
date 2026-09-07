import { publishNetworkFailure } from "./failure";

// React Native turns `console.error` and `console.warn` into LogBox overlays that sit on top
// of the running app. Hyperview reports every failed request through its logger, and the app
// already answers those with a designed error surface (ErrorScreen, ElementErrorBanner), so
// using those console levels stacks a second, technical notice over the first one the user is
// meant to read. Everything is written at `log` level with an explicit prefix instead: still
// visible in Metro and in any log drain, no overlay. A crash reporter belongs in
// `reportHyperviewError`, not in these console levels.
// Hyperview calls every level with a message plus arbitrary context, so the silent levels
// must accept the same arguments as the forwarded ones or the call sites stop type-checking.
const silent = (..._args: unknown[]): void => {};

export const hyperviewLogger = {
  error: (...args: unknown[]): void => console.log("[hyperview:error]", ...args),
  warn: (...args: unknown[]): void => console.log("[hyperview:warn]", ...args),
  // Hyperview logs routine navigation at these levels; forwarding them buries the two above.
  info: silent,
  log: silent,
};

/**
 * Handle a failed Hyperview request.
 *
 * Called for both document loads (hv-doc.tsx) and fragment loads (hyperview.tsx). Publishing
 * the failure unsticks the list refresh spinner, which hyperview 0.110 leaves spinning because
 * it skips `onEnd()` when a fragment fetch fails. The error itself only ever reaches the log.
 */
export function reportHyperviewError(error: Error): void {
  publishNetworkFailure();
  hyperviewLogger.error("request failed", error);
}
