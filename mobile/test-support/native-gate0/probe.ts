/** Synthetic native-I/O experiment; never connect this module to application data. */
export type ProbeMetadata = {
  platform: string;
  /** Raw Expo Go client identifier: observed native build or version, not the SDK. */
  clientVersion: string;
  expoVersion: string;
  executionEnvironment: string;
  reactNativeVersion: string;
};
export type ProbeStage = "metadata" | "bootstrap" | "stream" | "first-frame" | "first-ack" | "second-frame" | "second-ack" | "abort" | "report";
export type ProbeChecks = {
  bootstrapOk: boolean; firstFrameRead: boolean; secondFrameRead: boolean;
  abortRequested: boolean; serverCloseObserved: boolean;
};
export type ProbeResult = {
  status: "PASS" | "FAIL" | "INCONCLUSIVE";
  checks: ProbeChecks;
  failedStage: ProbeStage | null;
  errorCode: string | null;
  reported: boolean;
  cookieCleanup: "done" | "pending" | "not-created";
};
type Fetch = (url: string, init?: RequestInit) => Promise<Response>;
type Options = {
  baseUrl: string;
  metadata: ProbeMetadata;
  bootstrapFetch: Fetch;
  streamFetch: Fetch;
  timeoutMs?: number;
  onProgress?: (stage: ProbeStage | "complete" | "failed") => void;
};
class ProbeFailure extends Error {
  constructor(readonly code: string) { super(code); }
}

/** Observe two ACK-gated frames, then attribute server closure to abort alone. */
export async function runNativeProbe(options: Options): Promise<ProbeResult> {
  const { metadata, bootstrapFetch, streamFetch } = options;
  const timeout = Math.min(options.timeoutMs ?? 6000, 10000);
  const checks: ProbeChecks = {bootstrapOk:false,firstFrameRead:false,secondFrameRead:false,abortRequested:false,serverCloseObserved:false};
  const result: ProbeResult = {status:"FAIL",checks,failedStage:null,errorCode:null,reported:false,cookieCleanup:"not-created"};
  const controller = new AbortController();
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  let stage: ProbeStage = "metadata";
  const progress = (next: ProbeStage) => { stage = next; options.onProgress?.(next); };
  const bounded = async <T,>(promise: Promise<T>): Promise<T> => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([promise, new Promise<T>((_resolve, reject) => {
        timer = setTimeout(() => reject(new ProbeFailure("timeout")), timeout);
      })]);
    } finally { clearTimeout(timer); }
  };
  const init: RequestInit = {credentials:"include",cache:"no-store",redirect:"error"};
  let base = "";
  try {
    progress("metadata");
    const identifier = (value: string, format: RegExp) => typeof value === "string"
      && value.length > 0 && value.length <= 32 && value.trim() === value && format.test(value);
    // Constants.expoVersion is a native client identifier, observed as build 1017880
    // on iOS. Establish the source SDK separately; never invent a client version.
    if (!["ios","android"].includes(metadata.platform) || metadata.executionEnvironment !== "storeClient"
      || !identifier(metadata.clientVersion, /^\d+(?:\.\d+){0,3}$/)
      || !identifier(metadata.expoVersion, /^57\.\d+\.\d+$/)
      || !identifier(metadata.reactNativeVersion, /^\d+\.\d+\.\d+$/)) {
      throw new ProbeFailure("unsupported-runtime");
    }
    const parsed = new URL(options.baseUrl);
    if (parsed.protocol !== "http:" || parsed.username || parsed.password || parsed.search || parsed.hash || !/^\/probe-[a-z0-9]+$/.test(parsed.pathname)) throw new ProbeFailure("unsupported-runtime");
    base = parsed.toString().replace(/\/$/, "");
    progress("bootstrap");
    result.cookieCleanup = "pending";
    const bootstrap = await bounded(bootstrapFetch(`${base}/bootstrap`, init));
    if (bootstrap.status !== 200) throw new ProbeFailure("unexpected-status");
    checks.bootstrapOk = true;
    progress("stream");
    const response = await bounded(streamFetch(`${base}/stream`, {...init,headers:{Accept:"text/event-stream"},signal:controller.signal}));
    if (response.status !== 200) throw new ProbeFailure("unexpected-status");
    if (!response.headers.get("Content-Type")?.startsWith("text/event-stream") || !response.body) throw new ProbeFailure("invalid-stream");
    reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let bytes = 0;
    let reads = 0;
    let firstAckRead = -1;
    for (const expected of [1, 2]) {
      progress(expected === 1 ? "first-frame" : "second-frame");
      let token: string | undefined;
      while (!token) {
        const separator = /\r?\n\r?\n/.exec(buffer);
        if (separator?.index !== undefined) {
          const event = buffer.slice(0, separator.index);
          buffer = buffer.slice(separator.index + separator[0].length);
          if (!event || event.startsWith(":")) continue;
          const lines = event.split(/\r?\n/);
          try {
            if (!lines.includes("event: probe")) throw new Error();
            const data = JSON.parse(lines.filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n"));
            if (data.stage !== expected || typeof data.token !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(data.token) || (expected === 2 && reads <= firstAckRead)) throw new Error();
            token = data.token;
          } catch { throw new ProbeFailure("invalid-frame"); }
        } else {
          const part = await bounded(reader.read());
          if (part.done || !part.value) throw new ProbeFailure("invalid-stream");
          bytes += part.value.byteLength;
          if (bytes > 16384) throw new ProbeFailure("invalid-stream");
          reads += 1;
          buffer += decoder.decode(part.value, {stream:true});
        }
      }
      if (expected === 1) checks.firstFrameRead = true;
      else checks.secondFrameRead = true;
      progress(expected === 1 ? "first-ack" : "second-ack");
      const ack = await bounded(bootstrapFetch(`${base}/ack`, {...init,method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token})}));
      if (ack.status !== 204) throw new ProbeFailure("unexpected-status");
      if (expected === 1) firstAckRead = reads;
    }
    progress("abort");
    checks.abortRequested = true;
    controller.abort();
    // Never call cancel() here: doing so would conceal a broken native abort.
    const ended = await bounded(reader.read().then(part => part.done, () => true));
    if (!ended) throw new ProbeFailure("invalid-stream");
    progress("report");
    const deadline = Date.now() + timeout;
    while (true) {
      const report = await bounded(bootstrapFetch(`${base}/report`, init));
      if (report.status !== 200) throw new ProbeFailure("unexpected-status");
      const {server} = await bounded(report.json());
      const booleanFields = ["passed", "streamAuthorized", "firstFrameSent", "firstAckReceived", "secondFrameSent", "secondAckReceived", "streamClosed"];
      if (!server || booleanFields.some(name => typeof server[name] !== "boolean") || !Number.isInteger(server.activeStreams)) throw new ProbeFailure("server-not-closed");
      if (booleanFields.every(name => server[name] === true) && server.activeStreams === 0 && server.closeReason === "client") {
        checks.serverCloseObserved = true;
        break;
      }
      if (server?.closeReason === "deadline" || Date.now() >= deadline) throw new ProbeFailure("server-not-closed");
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    result.status = "PASS";
  } catch (error) {
    result.failedStage = stage;
    result.errorCode = error instanceof ProbeFailure ? error.code : "request-failed";
    if (stage === "metadata") result.status = "INCONCLUSIVE";
    options.onProgress?.("failed");
  }
  // Record the failed abort outcome BEFORE cleanup can close its stream.
  if (base) {
    const payload = {
      platform:metadata.platform,clientVersion:metadata.clientVersion,
      expoVersion:metadata.expoVersion,executionEnvironment:metadata.executionEnvironment,
      reactNativeVersion:metadata.reactNativeVersion,
      checks,failedStage:result.failedStage,errorCode:result.errorCode,
    };
    try {
      const saved = await bounded(bootstrapFetch(`${base}/client-report`, {...init,method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}));
      if (saved.status !== 204) throw new Error();
      result.reported = true;
    } catch {
      result.status = "INCONCLUSIVE";
      result.failedStage = "report";
      result.errorCode = "report-upload-failed";
    }
  }
  try {
    if (result.status !== "PASS") {
      controller.abort();
      try { await bounded(reader?.cancel() ?? Promise.resolve()); } catch { /* Failed cleanup is not a passing abort observation. */ }
    }
  } finally {
    // This endpoint expires only the unique synthetic cookie and run path.
    // It runs after the result was recorded and cannot establish abort success.
    if (base && result.cookieCleanup === "pending") {
      try {
        const reset = await bounded(bootstrapFetch(`${base}/reset`, {...init,method:"POST"}));
        if (reset.status === 204) result.cookieCleanup = "done";
      } catch { /* Report pending cleanup; never clear a shared cookie jar. */ }
    }
    try { reader?.releaseLock(); } catch { /* No private reader state is exposed. */ }
  }
  options.onProgress?.(result.status === "PASS" ? "complete" : "failed");
  return result;
}
